from __future__ import annotations

import asyncio
import enum
import json
from dataclasses import asdict
from typing import Any

import websockets

from aim_node.core.config import AIMCoreConfig
from aim_node.core.handshake import (
    HandshakeAcceptMessage,
    HandshakeInitMessage,
    HandshakeManager,
)
from aim_node.core.relay_crypto import (
    SequenceTracker,
    TrafficKeys,
    decrypt_frame,
    encrypt_frame,
)

from .protocol import (
    FRAME_CLOSE,
    FRAME_CLOSE_ACK,
    FRAME_ERROR,
    FRAME_HEARTBEAT,
    FRAME_HEARTBEAT_ACK,
    FRAME_REQUEST,
    FRAME_RESPONSE,
    ClosePayload,
    ErrorPayload,
    RequestPayload,
    ResponsePayload,
    deserialize_payload,
    serialize_payload,
)


class RelayState(enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    HANDSHAKING = "handshaking"
    ESTABLISHED = "established"
    CLOSING = "closing"
    CLOSED = "closed"


class RelayTransport:
    """
    Manages a single encrypted relay session over WebSocket.
    """

    def __init__(self, config: AIMCoreConfig, handshake_manager: HandshakeManager):
        self.config = config
        self._handshake = handshake_manager
        self.state = RelayState.DISCONNECTED
        self._ws: Any = None
        self._traffic_keys: TrafficKeys | None = None
        self._send_seq = SequenceTracker()
        self._recv_seq = SequenceTracker()
        self._heartbeat_task: asyncio.Task | None = None
        self._last_activity: float = 0.0
        self._missed_heartbeats: int = 0
        self._pending_requests: dict[str, asyncio.Future[Any]] = {}
        self._max_concurrent: int = 10
        self._request_slots = asyncio.Semaphore(self._max_concurrent)
        self._is_initiator = False
        self._awaiting_heartbeat_ack = False

    async def connect(
        self,
        relay_url: str,
        session_id: str,
        peer_node_id: str,
        peer_ed25519_pubkey,
        is_initiator: bool,
    ) -> None:
        """
        Connect to relay WebSocket, perform handshake, start heartbeat.
        """
        self.state = RelayState.CONNECTING
        self._is_initiator = is_initiator
        websocket_url = relay_url if relay_url.startswith(("ws://", "wss://")) else f"wss://{relay_url}"
        self._ws = await websockets.connect(websocket_url)
        self.state = RelayState.HANDSHAKING

        if is_initiator:
            init_msg = self._handshake.create_init(session_id)
            await self._ws.send(self._json_message(init_msg))
            accept_raw = await self._ws.recv()
            accept_msg = HandshakeAcceptMessage(**json.loads(accept_raw))
            result = self._handshake.verify_accept(accept_msg, peer_ed25519_pubkey)
            self._traffic_keys = result.traffic_keys
        else:
            init_raw = await self._ws.recv()
            init_msg = HandshakeInitMessage(**json.loads(init_raw))
            self._handshake.verify_init(init_msg, session_id, peer_node_id, peer_ed25519_pubkey)
            accept_msg = self._handshake.create_accept(session_id, init_msg.ephemeral_pubkey)
            await self._ws.send(self._json_message(accept_msg))
            self._traffic_keys = self._handshake._compute_shared_secret_and_keys(
                self._decode_b64(init_msg.ephemeral_pubkey),
                session_id,
            )

        self._last_activity = self._now()
        self.state = RelayState.ESTABLISHED
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def send_frame(self, frame_type: int, payload: bytes) -> None:
        """
        Encrypt and send a frame over the relay.
        """
        if self._ws is None or self._traffic_keys is None:
            raise RuntimeError("relay session is not established")

        key, nonce_prefix = self._outbound_key_material()
        sequence_number = self._send_seq.next_sequence
        raw_frame = encrypt_frame(key, nonce_prefix, sequence_number, frame_type, payload)
        await self._ws.send(raw_frame)
        self._send_seq.validate_and_advance(sequence_number)
        self._last_activity = self._now()

    async def recv_frame(self) -> tuple[int, bytes]:
        """
        Receive and decrypt a frame from the relay.
        """
        if self._ws is None or self._traffic_keys is None:
            raise RuntimeError("relay session is not established")

        while True:
            raw_frame = await self._ws.recv()
            key, nonce_prefix = self._inbound_key_material()
            frame_type, sequence_number, plaintext = decrypt_frame(key, nonce_prefix, raw_frame)
            self._recv_seq.validate_and_advance(sequence_number)
            self._last_activity = self._now()

            if frame_type == FRAME_HEARTBEAT:
                await self.send_frame(FRAME_HEARTBEAT_ACK, b"")
                continue

            if frame_type == FRAME_HEARTBEAT_ACK:
                self._awaiting_heartbeat_ack = False
                self._missed_heartbeats = 0
                continue

            if frame_type == FRAME_CLOSE:
                await self.send_frame(FRAME_CLOSE_ACK, b"")

            return frame_type, plaintext

    async def send_request(self, payload: RequestPayload) -> ResponsePayload:
        """
        High-level: serialize request, send REQUEST frame, wait for matching RESPONSE/ERROR.
        """
        await self._request_slots.acquire()
        loop = asyncio.get_running_loop()
        future: asyncio.Future[Any] = loop.create_future()
        self._pending_requests[payload.trace_id] = future
        try:
            await self.send_frame(FRAME_REQUEST, serialize_payload(payload))
            while True:
                frame_type, plaintext = await self.recv_frame()
                decoded = deserialize_payload(frame_type, plaintext)

                if frame_type == FRAME_RESPONSE and isinstance(decoded, ResponsePayload):
                    if decoded.trace_id != payload.trace_id:
                        pending = self._pending_requests.get(decoded.trace_id)
                        if pending is not None and not pending.done():
                            pending.set_result(decoded)
                        continue
                    future.set_result(decoded)
                    return await future

                if frame_type == FRAME_ERROR and isinstance(decoded, ErrorPayload):
                    if decoded.trace_id is None or decoded.trace_id == payload.trace_id:
                        future.set_exception(RuntimeError(f"{decoded.code}: {decoded.message}"))
                        return await future
                    pending = self._pending_requests.get(decoded.trace_id)
                    if pending is not None and not pending.done():
                        pending.set_exception(RuntimeError(f"{decoded.code}: {decoded.message}"))
                    continue
        finally:
            self._pending_requests.pop(payload.trace_id, None)
            self._request_slots.release()

    async def send_response(self, payload: ResponsePayload) -> None:
        """High-level: serialize and send RESPONSE frame."""
        await self.send_frame(FRAME_RESPONSE, serialize_payload(payload))

    async def close(self, reason: str = "buyer_requested") -> None:
        """
        Send CLOSE frame, wait for CLOSE_ACK (5s timeout), close WebSocket.
        """
        if self.state is RelayState.CLOSED:
            return

        self.state = RelayState.CLOSING
        heartbeat_task = self._heartbeat_task
        if (
            heartbeat_task is not None
            and heartbeat_task is not asyncio.current_task()
            and not heartbeat_task.done()
        ):
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

        try:
            if self._traffic_keys is not None and self._ws is not None:
                close_payload = serialize_payload(ClosePayload(reason=reason))
                await self.send_frame(FRAME_CLOSE, close_payload)
                try:
                    frame_type, _ = await asyncio.wait_for(self.recv_frame(), timeout=5)
                    if frame_type != FRAME_CLOSE_ACK:
                        raise RuntimeError("expected CLOSE_ACK")
                except asyncio.TimeoutError:
                    pass
        finally:
            if self._ws is not None:
                await self._ws.close()
            self.state = RelayState.CLOSED

    async def _heartbeat_loop(self) -> None:
        """
        Every 30s of inactivity: send HEARTBEAT.
        """
        try:
            while self.state is RelayState.ESTABLISHED:
                await asyncio.sleep(30)
                if self.state is not RelayState.ESTABLISHED:
                    break
                if self._now() - self._last_activity < 30:
                    continue

                self._awaiting_heartbeat_ack = True
                await self.send_frame(FRAME_HEARTBEAT, b"")
                await asyncio.sleep(5)
                if self.state is not RelayState.ESTABLISHED:
                    break
                if self._awaiting_heartbeat_ack:
                    self._missed_heartbeats += 1
                    self._awaiting_heartbeat_ack = False
                    if self._missed_heartbeats >= 3:
                        await self.close(reason="error")
                        break
        except asyncio.CancelledError:
            raise

    @staticmethod
    def _json_message(message: Any) -> str:
        return json.dumps(asdict(message), separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _decode_b64(value: str) -> bytes:
        import base64

        return base64.b64decode(value.encode("ascii"), validate=True)

    @staticmethod
    def _now() -> float:
        return asyncio.get_running_loop().time()

    def _outbound_key_material(self) -> tuple[bytes, bytes]:
        assert self._traffic_keys is not None
        if self._is_initiator:
            return (
                self._traffic_keys.buyer_to_seller_key,
                self._traffic_keys.buyer_to_seller_nonce_prefix,
            )
        return (
            self._traffic_keys.seller_to_buyer_key,
            self._traffic_keys.seller_to_buyer_nonce_prefix,
        )

    def _inbound_key_material(self) -> tuple[bytes, bytes]:
        assert self._traffic_keys is not None
        if self._is_initiator:
            return (
                self._traffic_keys.seller_to_buyer_key,
                self._traffic_keys.seller_to_buyer_nonce_prefix,
            )
        return (
            self._traffic_keys.buyer_to_seller_key,
            self._traffic_keys.buyer_to_seller_nonce_prefix,
        )
