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
