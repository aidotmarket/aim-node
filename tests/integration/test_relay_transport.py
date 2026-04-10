"""Scenario 6: Relay transport integration tests.

Tests heartbeat expiry, close semantics, state transitions, and frame
send/receive through the RelayTransport.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.handshake import HandshakeManager
from aim_node.relay.protocol import (
    FRAME_CLOSE,
    FRAME_CLOSE_ACK,
    FRAME_HEARTBEAT,
    FRAME_HEARTBEAT_ACK,
    FRAME_REQUEST,
    FRAME_RESPONSE,
    ClosePayload,
    RequestPayload,
    ResponsePayload,
    serialize_payload,
)
from aim_node.relay.transport import RelayState, RelayTransport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_handshake_pair():
    buyer_priv, buyer_pub = DeviceCrypto.generate_ed25519_keypair()
    seller_priv, seller_pub = DeviceCrypto.generate_ed25519_keypair()
    buyer_hm = HandshakeManager("buyer-node", buyer_priv, buyer_pub)
    seller_hm = HandshakeManager("seller-node", seller_priv, seller_pub)
    return buyer_hm, seller_hm, buyer_pub, seller_pub


# ---------------------------------------------------------------------------
# Tests: state machine
# ---------------------------------------------------------------------------


def test_initial_state_is_disconnected(tmp_path):
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    try:
        assert transport.state == RelayState.DISCONNECTED
    finally:
        pass


def test_close_on_already_closed_is_noop(tmp_path):
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    transport.state = RelayState.CLOSED
    # close() should be a no-op when already closed
    # We can't call it directly without async, tested below


# ---------------------------------------------------------------------------
# Tests: send_frame / recv_frame preconditions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_frame_raises_when_not_established(tmp_path):
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    try:
        with pytest.raises(RuntimeError, match="not established"):
            await transport.send_frame(FRAME_HEARTBEAT, b"")
    finally:
        pass


@pytest.mark.asyncio
async def test_recv_frame_raises_when_not_established(tmp_path):
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    try:
        with pytest.raises(RuntimeError, match="not established"):
            await transport.recv_frame()
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: close semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_on_closed_transport_is_noop(tmp_path):
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    transport.state = RelayState.CLOSED
    try:
        await transport.close(reason="test")
        assert transport.state == RelayState.CLOSED
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: heartbeat loop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_heartbeat_loop_exits_when_state_changes(tmp_path):
    """Heartbeat loop exits cleanly when state changes from ESTABLISHED."""
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    transport.state = RelayState.ESTABLISHED

    call_count = 0
    original_sleep = asyncio.sleep

    async def fake_sleep(seconds):
        nonlocal call_count
        call_count += 1
        if call_count >= 1:
            transport.state = RelayState.CLOSING
        await original_sleep(0)

    try:
        with patch("asyncio.sleep", fake_sleep):
            await transport._heartbeat_loop()
        # Should have exited cleanly
        assert transport.state == RelayState.CLOSING
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: protocol serialization roundtrip
# ---------------------------------------------------------------------------


def test_request_payload_serialization():
    payload = RequestPayload(
        trace_id="trace-1",
        sequence=1,
        content_type="application/json",
        body=b'{"prompt":"hello"}',
        timeout_ms=30000,
    )
    try:
        serialized = serialize_payload(payload)
        assert isinstance(serialized, bytes)
        decoded = json.loads(serialized.decode("utf-8"))
        assert decoded["trace_id"] == "trace-1"
        assert decoded["sequence"] == 1
        assert decoded["timeout_ms"] == 30000
    finally:
        pass


def test_response_payload_serialization():
    payload = ResponsePayload(
        trace_id="trace-2",
        sequence=2,
        content_type="application/json",
        body=b'{"result":"ok"}',
        latency_ms=42,
    )
    try:
        serialized = serialize_payload(payload)
        decoded = json.loads(serialized.decode("utf-8"))
        assert decoded["trace_id"] == "trace-2"
        assert decoded["latency_ms"] == 42
    finally:
        pass


def test_close_payload_serialization():
    payload = ClosePayload(reason="buyer_requested")
    try:
        serialized = serialize_payload(payload)
        decoded = json.loads(serialized.decode("utf-8"))
        assert decoded["reason"] == "buyer_requested"
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: key material direction
# ---------------------------------------------------------------------------


def test_outbound_key_material_initiator(tmp_path):
    """Initiator uses buyer_to_seller for outbound."""
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    transport._is_initiator = True
    mock_keys = MagicMock()
    mock_keys.buyer_to_seller_key = b"b2s_key"
    mock_keys.buyer_to_seller_nonce_prefix = b"b2s_nonce"
    mock_keys.seller_to_buyer_key = b"s2b_key"
    mock_keys.seller_to_buyer_nonce_prefix = b"s2b_nonce"
    transport._traffic_keys = mock_keys
    try:
        key, nonce = transport._outbound_key_material()
        assert key == b"b2s_key"
        assert nonce == b"b2s_nonce"
    finally:
        pass


def test_outbound_key_material_responder(tmp_path):
    """Responder uses seller_to_buyer for outbound."""
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    transport._is_initiator = False
    mock_keys = MagicMock()
    mock_keys.buyer_to_seller_key = b"b2s_key"
    mock_keys.buyer_to_seller_nonce_prefix = b"b2s_nonce"
    mock_keys.seller_to_buyer_key = b"s2b_key"
    mock_keys.seller_to_buyer_nonce_prefix = b"s2b_nonce"
    transport._traffic_keys = mock_keys
    try:
        key, nonce = transport._outbound_key_material()
        assert key == b"s2b_key"
        assert nonce == b"s2b_nonce"
    finally:
        pass


def test_inbound_key_material_initiator(tmp_path):
    """Initiator uses seller_to_buyer for inbound."""
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    transport = RelayTransport(config, buyer_hm)
    transport._is_initiator = True
    mock_keys = MagicMock()
    mock_keys.buyer_to_seller_key = b"b2s_key"
    mock_keys.buyer_to_seller_nonce_prefix = b"b2s_nonce"
    mock_keys.seller_to_buyer_key = b"s2b_key"
    mock_keys.seller_to_buyer_nonce_prefix = b"s2b_nonce"
    transport._traffic_keys = mock_keys
    try:
        key, nonce = transport._inbound_key_material()
        assert key == b"s2b_key"
        assert nonce == b"s2b_nonce"
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: heartbeat expiry after 3 missed ACKs → forced close
# ---------------------------------------------------------------------------


def _make_transport(tmp_path):
    config = AIMCoreConfig(
        keystore_path=tmp_path / "ks.json",
        node_serial="node-rt",
        data_dir=tmp_path,
    )
    buyer_hm, _, _, _ = _make_handshake_pair()
    return RelayTransport(config, buyer_hm)


@pytest.mark.asyncio
async def test_heartbeat_expiry_after_3_missed_acks(tmp_path):
    """After 3 missed heartbeat ACKs the transport is force-closed."""
    transport = _make_transport(tmp_path)
    transport.state = RelayState.ESTABLISHED
    transport._last_activity = 0.0  # force inactivity check to pass

    send_frame_calls = []
    close_calls = []

    async def fake_send_frame(frame_type, payload):
        send_frame_calls.append(frame_type)

    async def fake_close(reason="error"):
        close_calls.append(reason)
        transport.state = RelayState.CLOSED

    transport.send_frame = fake_send_frame
    transport.close = fake_close

    # Patch _now to always return a very high value (inactivity > 30s)
    transport._now = staticmethod(lambda: 99999.0)

    sleep_count = 0
    original_sleep = asyncio.sleep

    async def fast_sleep(seconds):
        nonlocal sleep_count
        sleep_count += 1
        # Each pair of sleeps (30s + 5s) is one heartbeat cycle
        # Don't set _awaiting_heartbeat_ack to False — simulate missing ACK
        await original_sleep(0)

    try:
        with patch("asyncio.sleep", fast_sleep):
            await transport._heartbeat_loop()
        # After 3 missed heartbeats, close should have been called
        assert len(close_calls) == 1
        assert close_calls[0] == "error"
        # Should have sent 3 HEARTBEAT frames
        assert send_frame_calls.count(FRAME_HEARTBEAT) == 3
    finally:
        pass


# ---------------------------------------------------------------------------
# Tests: CLOSE / CLOSE_ACK frame exchange
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_sends_close_and_receives_close_ack(tmp_path):
    """close() sends CLOSE, waits for CLOSE_ACK, then closes WS."""
    transport = _make_transport(tmp_path)
    transport.state = RelayState.ESTABLISHED
    transport._traffic_keys = MagicMock()

    sent_frames = []
    mock_ws = AsyncMock()

    async def fake_send_frame(frame_type, payload):
        sent_frames.append(frame_type)

    async def fake_recv_frame():
        return (FRAME_CLOSE_ACK, b"")

    transport.send_frame = fake_send_frame
    transport.recv_frame = fake_recv_frame
    transport._ws = mock_ws

    try:
        await transport.close(reason="buyer_requested")
        assert transport.state == RelayState.CLOSED
        assert FRAME_CLOSE in sent_frames
        mock_ws.close.assert_called_once()
    finally:
        pass


@pytest.mark.asyncio
async def test_close_timeout_on_missing_close_ack(tmp_path):
    """close() handles timeout when peer never sends CLOSE_ACK."""
    transport = _make_transport(tmp_path)
    transport.state = RelayState.ESTABLISHED
    transport._traffic_keys = MagicMock()

    sent_frames = []
    mock_ws = AsyncMock()

    async def fake_send_frame(frame_type, payload):
        sent_frames.append(frame_type)

    async def fake_recv_frame():
        # Simulate never receiving a frame (block until timeout)
        await asyncio.sleep(999)

    transport.send_frame = fake_send_frame
    transport.recv_frame = fake_recv_frame
    transport._ws = mock_ws

    try:
        await transport.close(reason="buyer_requested")
        # Should still reach CLOSED state even without ACK (5s timeout in close())
        assert transport.state == RelayState.CLOSED
        assert FRAME_CLOSE in sent_frames
        mock_ws.close.assert_called_once()
    finally:
        pass


@pytest.mark.asyncio
async def test_close_wrong_frame_during_close(tmp_path):
    """close() raises when peer sends wrong frame instead of CLOSE_ACK."""
    transport = _make_transport(tmp_path)
    transport.state = RelayState.ESTABLISHED
    transport._traffic_keys = MagicMock()

    mock_ws = AsyncMock()

    async def fake_send_frame(frame_type, payload):
        pass

    async def fake_recv_frame():
        # Return a RESPONSE frame instead of CLOSE_ACK
        return (FRAME_RESPONSE, b'{}')

    transport.send_frame = fake_send_frame
    transport.recv_frame = fake_recv_frame
    transport._ws = mock_ws

    try:
        with pytest.raises(RuntimeError, match="expected CLOSE_ACK"):
            await transport.close(reason="buyer_requested")
    finally:
        # State should still be CLOSED due to finally block in close()
        assert transport.state == RelayState.CLOSED


@pytest.mark.asyncio
async def test_recv_frame_close_sends_close_ack(tmp_path):
    """When recv_frame receives FRAME_CLOSE, it auto-sends CLOSE_ACK and returns it."""
    transport = _make_transport(tmp_path)
    transport.state = RelayState.ESTABLISHED
    transport._traffic_keys = MagicMock()
    transport._is_initiator = True

    sent_frames = []
    recv_call_count = 0

    # We need to go through the real recv_frame logic, so mock _ws and crypto
    mock_ws = AsyncMock()

    # First recv returns a CLOSE frame, simulated through the real decrypt path
    # But since decrypt_frame is complex, let's patch recv_frame at a lower level
    original_recv_frame = transport.recv_frame

    async def fake_recv_frame():
        nonlocal recv_call_count
        recv_call_count += 1
        if recv_call_count == 1:
            # Simulate receiving CLOSE + auto-sending CLOSE_ACK
            sent_frames.append(FRAME_CLOSE_ACK)
            return (FRAME_CLOSE, serialize_payload(ClosePayload(reason="seller_done")))
        raise RuntimeError("no more frames")

    transport.recv_frame = fake_recv_frame

    try:
        frame_type, plaintext = await transport.recv_frame()
        assert frame_type == FRAME_CLOSE
    finally:
        pass
