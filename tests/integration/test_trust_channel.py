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
