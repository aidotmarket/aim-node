from __future__ import annotations

import asyncio
import base64
import json

import pytest

from aim_node.core.crypto import DeviceCrypto
from aim_node.core.handshake import HandshakeManager
from aim_node.core.relay_crypto import derive_traffic_keys
from aim_node.relay.protocol import (
    FRAME_CLOSE_ACK,
    CancelPayload,
    ClosePayload,
    ErrorPayload,
    RequestPayload,
    ResponsePayload,
    deserialize_payload,
    serialize_payload,
)
from aim_node.relay.transport import RelayState, RelayTransport


class MockWebSocket:
    def __init__(self, recv_messages: list[object] | None = None):
        self.recv_messages = list(recv_messages or [])
        self.sent_messages: list[object] = []
        self.closed = False

    async def send(self, data: object) -> None:
        self.sent_messages.append(data)

    async def recv(self) -> object:
        if not self.recv_messages:
            raise RuntimeError("no queued websocket messages")
        return self.recv_messages.pop(0)

    async def close(self) -> None:
        self.closed = True


class HandshakeWebSocket(MockWebSocket):
    def __init__(self, seller: HandshakeManager, buyer_pub) -> None:
        super().__init__([])
        self._seller = seller
        self._buyer_pub = buyer_pub

    async def recv(self) -> object:
        if self.recv_messages:
            return await super().recv()
        if not self.sent_messages:
            raise RuntimeError("no init message available")

        init_dict = json.loads(self.sent_messages[0])
        init_msg = type("Init", (), init_dict)
        self._seller.verify_init(init_msg, "session-1", "buyer-1", self._buyer_pub)
        accept = self._seller.create_accept("session-1", init_dict["ephemeral_pubkey"])
        return json.dumps(accept.__dict__)


def _new_handshake_manager(node_id: str) -> tuple[HandshakeManager, object, object]:
    priv, pub = DeviceCrypto.generate_ed25519_keypair()
    return HandshakeManager(node_id, priv, pub), priv, pub


def test_serialize_deserialize_request_roundtrip() -> None:
    payload = RequestPayload(
        trace_id="123e4567-e89b-12d3-a456-426614174000",
        sequence=7,
        content_type="application/json",
        body=b'{"ok":true}',
        timeout_ms=5_000,
    )

    assert deserialize_payload(0x10, serialize_payload(payload)) == payload


def test_serialize_deserialize_response_roundtrip() -> None:
    payload = ResponsePayload(
        trace_id="123e4567-e89b-12d3-a456-426614174001",
        sequence=8,
        content_type="application/json",
        body=b'{"result":"ok"}',
        latency_ms=42,
    )

    assert deserialize_payload(0x11, serialize_payload(payload)) == payload


def test_serialize_deserialize_error_roundtrip() -> None:
    payload = ErrorPayload(trace_id=None, code=500, message="session failed")

    assert deserialize_payload(0x12, serialize_payload(payload)) == payload


def test_serialize_deserialize_cancel_roundtrip() -> None:
    payload = CancelPayload(trace_id="123e4567-e89b-12d3-a456-426614174002")

    assert deserialize_payload(0x30, serialize_payload(payload)) == payload


def test_serialize_deserialize_close_roundtrip() -> None:
    payload = ClosePayload(reason="buyer_requested", message="done")

    assert deserialize_payload(0x40, serialize_payload(payload)) == payload


def test_body_base64_encoding() -> None:
    raw_body = b"\x00\x01binary-payload"
    payload = RequestPayload(
        trace_id="123e4567-e89b-12d3-a456-426614174003",
        sequence=9,
        content_type="application/json",
        body=raw_body,
        timeout_ms=1_000,
    )

    encoded = serialize_payload(payload)
    decoded_json = json.loads(encoded)

    assert decoded_json["body"] == base64.b64encode(raw_body).decode("ascii")
    assert deserialize_payload(0x10, encoded).body == raw_body


@pytest.mark.asyncio
async def test_relay_state_transitions(core_config, monkeypatch: pytest.MonkeyPatch) -> None:
    transport_buyer, _, buyer_pub = _new_handshake_manager("buyer-1")
    seller, _, seller_pub = _new_handshake_manager("seller-1")
    ws = HandshakeWebSocket(seller, buyer_pub)

    async def fake_connect(url: str) -> MockWebSocket:
        assert url == "wss://relay.example"
        return ws

    async def fake_heartbeat(self) -> None:
        return None

    monkeypatch.setattr("aim_node.relay.transport.websockets.connect", fake_connect)
    monkeypatch.setattr(RelayTransport, "_heartbeat_loop", fake_heartbeat)

    transport = RelayTransport(core_config, transport_buyer)
    assert transport.state is RelayState.DISCONNECTED

    await transport.connect(
        relay_url="relay.example",
        session_id="session-1",
        peer_node_id="seller-1",
        peer_ed25519_pubkey=seller_pub,
        is_initiator=True,
    )

    assert transport.state is RelayState.ESTABLISHED

    async def fake_recv_close_ack() -> tuple[int, bytes]:
        return FRAME_CLOSE_ACK, b""

    transport.recv_frame = fake_recv_close_ack  # type: ignore[method-assign]

    await transport.close()

    assert transport.state is RelayState.CLOSED


@pytest.mark.asyncio
async def test_backpressure_max_concurrent(core_config) -> None:
    manager, _, _ = _new_handshake_manager("buyer-1")
    transport = RelayTransport(core_config, manager)
    transport._traffic_keys = derive_traffic_keys(b"\x01" * 32, "session-1")
    transport._ws = MockWebSocket()
    transport.state = RelayState.ESTABLISHED
    transport._max_concurrent = 1
    transport._request_slots = asyncio.Semaphore(1)

    blocker = asyncio.Event()
    release = asyncio.Event()

    async def fake_send_frame(frame_type: int, payload: bytes) -> None:
        return None

    async def fake_recv_frame() -> tuple[int, bytes]:
        blocker.set()
        await release.wait()
        active_trace_id = next(iter(transport._pending_requests))
        response = ResponsePayload(
            trace_id=active_trace_id,
            sequence=1 if active_trace_id == "trace-1" else 2,
            content_type="application/json",
            body=b"{}",
            latency_ms=10,
        )
        return 0x11, serialize_payload(response)

    transport.send_frame = fake_send_frame  # type: ignore[method-assign]
    transport.recv_frame = fake_recv_frame  # type: ignore[method-assign]

    first = asyncio.create_task(
        transport.send_request(
            RequestPayload("trace-1", 1, "application/json", b"{}", 1_000)
        )
    )
    await blocker.wait()

    second_started = asyncio.Event()

    async def second_request() -> ResponsePayload:
        second_started.set()
        return await transport.send_request(
            RequestPayload("trace-2", 2, "application/json", b"{}", 1_000)
        )

    second = asyncio.create_task(second_request())
    await second_started.wait()
    await asyncio.sleep(0)

    assert "trace-2" not in transport._pending_requests

    release.set()
    await first
    result = await second

    assert result.trace_id == "trace-2"


@pytest.mark.asyncio
async def test_heartbeat_miss_counter(core_config) -> None:
    manager, _, _ = _new_handshake_manager("buyer-1")
    transport = RelayTransport(core_config, manager)
    transport.state = RelayState.ESTABLISHED
    transport._last_activity = -100.0

    sent_frames: list[int] = []
    close_calls: list[str] = []

    async def fake_send_frame(frame_type: int, payload: bytes) -> None:
        sent_frames.append(frame_type)

    async def fake_close(reason: str = "buyer_requested") -> None:
        close_calls.append(reason)
        transport.state = RelayState.CLOSED

    sleep_calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        sleep_calls["count"] += 1
        if sleep_calls["count"] >= 7:
            transport.state = RelayState.CLOSED
        return None

    transport.send_frame = fake_send_frame  # type: ignore[method-assign]
    transport.close = fake_close  # type: ignore[method-assign]

    original_sleep = asyncio.sleep
    asyncio.sleep = fake_sleep  # type: ignore[assignment]
    try:
        await transport._heartbeat_loop()
    finally:
        asyncio.sleep = original_sleep  # type: ignore[assignment]

    assert sent_frames == [0x20, 0x20, 0x20]
    assert close_calls == ["error"]


@pytest.mark.asyncio
async def test_close_sends_frame_and_waits_ack(core_config) -> None:
    manager, _, _ = _new_handshake_manager("buyer-1")
    transport = RelayTransport(core_config, manager)
    transport.state = RelayState.ESTABLISHED
    transport._traffic_keys = derive_traffic_keys(b"\x02" * 32, "session-2")
    transport._ws = MockWebSocket()
    transport._heartbeat_task = asyncio.create_task(asyncio.sleep(60))

    received: list[int] = []

    async def fake_send_frame(frame_type: int, payload: bytes) -> None:
        received.append(frame_type)

    async def fake_recv_frame() -> tuple[int, bytes]:
        return FRAME_CLOSE_ACK, b""

    transport.send_frame = fake_send_frame  # type: ignore[method-assign]
    transport.recv_frame = fake_recv_frame  # type: ignore[method-assign]

    await transport.close(reason="buyer_requested")

    assert received == [0x40]
    assert transport._ws.closed is True
    assert transport.state is RelayState.CLOSED
