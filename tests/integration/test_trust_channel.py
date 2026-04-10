"""Scenario 4: Trust channel protocol integration tests.

Tests signed envelope exchange, reconnect/backoff logic, malformed message
handling, and action dispatch/waiter resolution.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import websockets
from websockets.exceptions import ConnectionClosed, InvalidStatus

from aim_node.core.config import AIMCoreConfig
from aim_node.core.trust_channel import TrustChannelClient, TrustChannelError


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_config(tmp_path: Path, **overrides) -> AIMCoreConfig:
    defaults = dict(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-tc-test",
        data_dir=tmp_path / "data",
        market_ws_url="ws://trust.test/ws",
        api_key="tc-api-key",
        reconnect_delay_s=0.01,
        reconnect_max_delay_s=0.05,
        reconnect_jitter=0.0,
    )
    defaults.update(overrides)
    return AIMCoreConfig(**defaults)


# ---------------------------------------------------------------------------
# Tests: message parsing & dispatch
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_valid_json_message(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        msg = tc._parse_message('{"action":"PING","transfer_id":"t1"}')
        assert msg == {"action": "PING", "transfer_id": "t1"}
    finally:
        pass


@pytest.mark.asyncio
async def test_parse_bytes_message(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        msg = tc._parse_message(b'{"action":"PONG"}')
        assert msg == {"action": "PONG"}
    finally:
        pass


@pytest.mark.asyncio
async def test_parse_malformed_json_returns_none(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        assert tc._parse_message("not json") is None
        assert tc._parse_message(b"\xff\xfe") is None
        assert tc._parse_message(12345) is None
    finally:
        pass


@pytest.mark.asyncio
async def test_dispatch_calls_registered_handler(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    received = []

    async def handler(msg):
        received.append(msg)

    tc.register_handler("TEST_ACTION", handler)
    try:
        await tc._dispatch_message({"action": "TEST_ACTION", "transfer_id": "", "data": 42})
        await asyncio.sleep(0.01)  # let the task run
        assert len(received) == 1
        assert received[0]["data"] == 42
    finally:
        pass


@pytest.mark.asyncio
async def test_dispatch_resolves_waiter(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        tc._waiters["MY_ACTION:transfer-1"] = future

        await tc._dispatch_message(
            {"action": "MY_ACTION", "transfer_id": "transfer-1", "result": "ok"}
        )
        assert future.done()
        assert future.result()["result"] == "ok"
    finally:
        pass


@pytest.mark.asyncio
async def test_receive_queue_populated(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        await tc._dispatch_message({"action": "UNKNOWN", "transfer_id": ""})
        msg = await asyncio.wait_for(tc._receive_queue.get(), timeout=1.0)
        assert msg["action"] == "UNKNOWN"
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: SESSION_NEGOTIATE handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_session_negotiate_stores_negotiation(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        await tc._handle_session_negotiate({
            "action": "SESSION_NEGOTIATE",
            "transfer_id": "xfer-1",
            "payload": {
                "buyer_node_id": "buyer-42",
                "buyer_ed25519_pubkey": "pubkey-b64",
            },
        })
        neg = tc.pop_negotiation("xfer-1")
        assert neg is not None
        assert neg["buyer_node_id"] == "buyer-42"
        assert neg["buyer_ed25519_pubkey"] == "pubkey-b64"
    finally:
        pass


@pytest.mark.asyncio
async def test_pop_negotiation_returns_none_when_missing(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        assert tc.pop_negotiation("nonexistent") is None
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: send / receive
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_raises_when_not_connected(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        with pytest.raises(TrustChannelError, match="not connected"):
            await tc.send({"action": "PING"})
    finally:
        pass


@pytest.mark.asyncio
async def test_send_with_mock_ws(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    sent_messages = []
    mock_ws = AsyncMock()
    mock_ws.send = AsyncMock(side_effect=lambda msg: sent_messages.append(msg))
    tc._ws = mock_ws
    try:
        await tc.send({"action": "HEARTBEAT"})
        assert len(sent_messages) == 1
        parsed = json.loads(sent_messages[0])
        assert parsed["action"] == "HEARTBEAT"
    finally:
        tc._ws = None


# ---------------------------------------------------------------------------
# Tests: wait_for_action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_wait_for_action_timeout(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        with pytest.raises(TimeoutError, match="Timed out"):
            await tc.wait_for_action("NEVER", "xfer-never", timeout=0.05)
    finally:
        pass


@pytest.mark.asyncio
async def test_wait_for_action_success(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    try:
        async def resolve_later():
            await asyncio.sleep(0.01)
            await tc._dispatch_message({
                "action": "EXPECTED",
                "transfer_id": "xfer-ok",
                "data": "payload",
            })

        task = asyncio.create_task(resolve_later())
        result = await tc.wait_for_action("EXPECTED", "xfer-ok", timeout=1.0)
        assert result["data"] == "payload"
        await task
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stop_cancels_waiters(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    tc._running = True
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    tc._waiters["ACTION:xfer"] = future
    try:
        await tc.stop()
        assert tc._running is False
        assert future.cancelled()
    finally:
        pass


@pytest.mark.asyncio
async def test_stop_closes_websocket(tmp_path):
    config = _make_config(tmp_path)
    tc = TrustChannelClient(config)
    tc._running = True
    mock_ws = AsyncMock()
    tc._ws = mock_ws
    try:
        await tc.stop()
        mock_ws.close.assert_called_once()
        assert tc._ws is None
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: reconnect backoff properties
# ---------------------------------------------------------------------------


def test_backoff_properties(tmp_path):
    config = _make_config(tmp_path, reconnect_delay_s=2.0, reconnect_max_delay_s=30.0, reconnect_jitter=0.5)
    tc = TrustChannelClient(config)
    try:
        assert tc.reconnect_delay_s == 2.0
        assert tc.reconnect_max_delay_s == 30.0
        assert tc.reconnect_jitter == 0.5
        assert tc.ws_url == "ws://trust.test/ws"
    finally:
        pass


# ---------------------------------------------------------------------------
# Live websocket tests: run() / _connect_and_listen()
# ---------------------------------------------------------------------------


async def _start_ws_server(handler, host="127.0.0.1", port=0):
    """Start a local websocket server, return (server, actual_port)."""
    server = await websockets.serve(handler, host, port)
    actual_port = next(iter(server.sockets)).getsockname()[1]
    return server, actual_port


@pytest.mark.asyncio
async def test_connect_and_listen_receives_messages(tmp_path):
    """run() connects to a real websocket server and receives messages."""
    received = []

    async def server_handler(ws):
        await ws.send(json.dumps({"action": "HELLO", "transfer_id": ""}))
        await ws.send(json.dumps({"action": "WORLD", "transfer_id": ""}))
        # Keep connection open briefly so client can read
        await asyncio.sleep(0.1)
        await ws.close()

    server, port = await _start_ws_server(server_handler)
    config = _make_config(tmp_path, market_ws_url=f"ws://127.0.0.1:{port}")
    tc = TrustChannelClient(config)

    async def collect():
        while len(received) < 2:
            msg = await asyncio.wait_for(tc.receive(timeout=2.0), timeout=3.0)
            received.append(msg)
        await tc.stop()

    try:
        run_task = asyncio.create_task(tc.run())
        collect_task = asyncio.create_task(collect())
        await asyncio.wait_for(collect_task, timeout=5.0)
        await asyncio.wait_for(run_task, timeout=2.0)
        assert len(received) == 2
        assert received[0]["action"] == "HELLO"
        assert received[1]["action"] == "WORLD"
    finally:
        await tc.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_auth_headers_sent_on_connect(tmp_path):
    """_connect_and_listen sends X-Node-Serial and X-API-Key headers."""
    captured_headers = {}

    async def server_handler(ws):
        captured_headers.update(ws.request.headers)
        await ws.close()

    server, port = await _start_ws_server(server_handler)
    config = _make_config(
        tmp_path,
        market_ws_url=f"ws://127.0.0.1:{port}",
        node_serial="node-header-test",
        api_key="secret-key-42",
    )
    tc = TrustChannelClient(config)
    try:
        run_task = asyncio.create_task(tc.run())
        await asyncio.sleep(0.3)
        await tc.stop()
        await asyncio.wait_for(run_task, timeout=2.0)
        assert captured_headers.get("x-node-serial") == "node-header-test"
        assert captured_headers.get("x-api-key") == "secret-key-42"
    finally:
        await tc.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_malformed_frame_discarded_in_live_loop(tmp_path):
    """Malformed messages are discarded; valid ones still arrive."""
    received = []

    async def server_handler(ws):
        await ws.send("not-json-at-all{{{")
        await ws.send(b"\xff\xfe\xfd")
        await ws.send(json.dumps({"action": "VALID", "transfer_id": ""}))
        await asyncio.sleep(0.1)
        await ws.close()

    server, port = await _start_ws_server(server_handler)
    config = _make_config(tmp_path, market_ws_url=f"ws://127.0.0.1:{port}")
    tc = TrustChannelClient(config)

    async def collect():
        msg = await asyncio.wait_for(tc.receive(timeout=3.0), timeout=4.0)
        received.append(msg)
        await tc.stop()

    try:
        run_task = asyncio.create_task(tc.run())
        collect_task = asyncio.create_task(collect())
        await asyncio.wait_for(collect_task, timeout=5.0)
        await asyncio.wait_for(run_task, timeout=2.0)
        assert len(received) == 1
        assert received[0]["action"] == "VALID"
    finally:
        await tc.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_reconnect_backoff_on_disconnect(tmp_path):
    """run() reconnects after the server disconnects, with actual sleep/backoff."""
    connect_count = 0

    async def server_handler(ws):
        nonlocal connect_count
        connect_count += 1
        await ws.close()

    server, port = await _start_ws_server(server_handler)
    config = _make_config(
        tmp_path,
        market_ws_url=f"ws://127.0.0.1:{port}",
        reconnect_delay_s=0.05,
        reconnect_max_delay_s=0.15,
        reconnect_jitter=0.0,
    )
    tc = TrustChannelClient(config)
    try:
        run_task = asyncio.create_task(tc.run())
        # Wait long enough for at least 3 reconnect attempts
        await asyncio.sleep(0.6)
        await tc.stop()
        await asyncio.wait_for(run_task, timeout=2.0)
        assert connect_count >= 3
    finally:
        await tc.stop()
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_signed_envelope_exchange_via_ws(tmp_path):
    """Send and receive a signed envelope (JSON with signature field) over live WS."""
    server_received = []
    envelope = {
        "action": "SIGNED_MSG",
        "transfer_id": "xfer-sig",
        "payload": {"data": "hello"},
        "signature": "fakesig_b64_abc123",
    }

    async def server_handler(ws):
        # Send a signed envelope to client
        await ws.send(json.dumps(envelope))
        # Receive whatever the client sends back
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=2.0)
            server_received.append(json.loads(raw))
        except (asyncio.TimeoutError, websockets.exceptions.ConnectionClosed):
            pass
        await asyncio.sleep(0.1)
        await ws.close()

    server, port = await _start_ws_server(server_handler)
    config = _make_config(tmp_path, market_ws_url=f"ws://127.0.0.1:{port}")
    tc = TrustChannelClient(config)

    try:
        run_task = asyncio.create_task(tc.run())
        # Wait for the signed envelope to arrive
        msg = await asyncio.wait_for(tc.receive(timeout=3.0), timeout=4.0)
        assert msg["action"] == "SIGNED_MSG"
        assert msg["signature"] == "fakesig_b64_abc123"
        assert msg["payload"]["data"] == "hello"

        # Send a signed reply back
        reply = {
            "action": "SIGNED_REPLY",
            "transfer_id": "xfer-sig",
            "payload": {"ack": True},
            "signature": "replysig_b64_xyz",
        }
        await tc.send(reply)
        await asyncio.sleep(0.2)
        await tc.stop()
        await asyncio.wait_for(run_task, timeout=2.0)
        assert len(server_received) == 1
        assert server_received[0]["signature"] == "replysig_b64_xyz"
    finally:
        await tc.stop()
        server.close()
        await server.wait_closed()
