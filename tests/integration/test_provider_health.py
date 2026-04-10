"""Scenario 5: Provider health and negotiation refusal tests.

Tests that the provider session handler refuses negotiation when the
adapter is unhealthy, and accepts when healthy.
"""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.handshake import HandshakeManager
from aim_node.provider.adapter import AdapterConfig, HttpJsonAdapter
from aim_node.provider.session_handler import ProviderSessionHandler


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


class FakeTrustChannel:
    def __init__(self):
        self.handlers = {}

    def register_handler(self, action, handler):
        self.handlers[action] = handler


def _make_provider(tmp_path, *, adapter_healthy=True):
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="provider-health-test",
        data_dir=tmp_path / "data",
        api_key="test-key",
    )

    async def seller_endpoint(request: Request):
        return JSONResponse({"result": "ok"})

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://seller.test/invoke"))
    adapter._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=Starlette(routes=[Route("/invoke", seller_endpoint, methods=["POST"])])
        ),
        base_url="http://seller.test",
    )
    adapter._healthy = adapter_healthy

    trust_channel = FakeTrustChannel()
    handler = ProviderSessionHandler(config, adapter, trust_channel)
    return handler, adapter, config


def _negotiate_event(buyer_pub_b64):
    return {
        "payload": {
            "session_id": "sess-health-1",
            "connection_mode": "relay",
            "relay_url": "ws://relay.test",
            "buyer_node_id": "buyer-node",
            "buyer_ed25519_pubkey": buyer_pub_b64,
        },
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_negotiate_rejected_when_adapter_unhealthy(tmp_path, monkeypatch):
    """Provider rejects SESSION_NEGOTIATE when adapter is unhealthy."""
    handler, adapter, config = _make_provider(tmp_path, adapter_healthy=False)

    _, buyer_pub = DeviceCrypto.generate_ed25519_keypair()
    buyer_pub_b64 = base64.b64encode(buyer_pub.public_bytes_raw()).decode("ascii")

    try:
        await handler.on_session_negotiate(_negotiate_event(buyer_pub_b64))
        # Should NOT have created any session
        assert len(handler._active_sessions) == 0
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_negotiate_accepted_when_adapter_healthy(tmp_path, monkeypatch):
    """Provider accepts SESSION_NEGOTIATE when adapter is healthy and creates transport."""
    handler, adapter, config = _make_provider(tmp_path, adapter_healthy=True)

    priv, pub = DeviceCrypto.generate_ed25519_keypair()
    buyer_pub_b64 = base64.b64encode(pub.public_bytes_raw()).decode("ascii")

    # Mock websockets.connect and handshake to avoid real connections
    connect_calls = []

    async def fake_transport_connect(self, **kwargs):
        connect_calls.append(kwargs)

    monkeypatch.setattr(
        "aim_node.relay.transport.RelayTransport.connect", fake_transport_connect,
    )

    try:
        await handler.on_session_negotiate(_negotiate_event(buyer_pub_b64))
        assert "sess-health-1" in handler._active_sessions
        assert len(connect_calls) == 1
        assert connect_calls[0]["is_initiator"] is False
    finally:
        # Cleanup active session tasks
        for task in handler._session_tasks.values():
            task.cancel()
        for task in handler._session_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        await adapter.stop()


@pytest.mark.asyncio
async def test_negotiate_ignores_direct_mode(tmp_path):
    """Provider ignores direct-mode negotiation (only relay is handled)."""
    handler, adapter, config = _make_provider(tmp_path, adapter_healthy=True)
    try:
        await handler.on_session_negotiate({
            "payload": {
                "session_id": "sess-direct",
                "connection_mode": "direct",
            },
        })
        assert len(handler._active_sessions) == 0
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_negotiate_ignores_unsupported_mode(tmp_path):
    """Provider ignores unsupported connection_mode values."""
    handler, adapter, config = _make_provider(tmp_path, adapter_healthy=True)
    try:
        await handler.on_session_negotiate({
            "payload": {
                "session_id": "sess-pigeon",
                "connection_mode": "pigeon_carrier",
            },
        })
        assert len(handler._active_sessions) == 0
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_negotiate_ignores_missing_fields(tmp_path):
    """Provider ignores negotiate events with missing required fields."""
    handler, adapter, config = _make_provider(tmp_path, adapter_healthy=True)
    try:
        await handler.on_session_negotiate({
            "payload": {
                "session_id": "sess-incomplete",
                "connection_mode": "relay",
                # missing relay_url, buyer_node_id, buyer_ed25519_pubkey
            },
        })
        assert len(handler._active_sessions) == 0
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_negotiate_ignores_duplicate_session(tmp_path, monkeypatch):
    """Provider ignores duplicate SESSION_NEGOTIATE for same session_id."""
    handler, adapter, config = _make_provider(tmp_path, adapter_healthy=True)

    _, buyer_pub = DeviceCrypto.generate_ed25519_keypair()
    buyer_pub_b64 = base64.b64encode(buyer_pub.public_bytes_raw()).decode("ascii")

    async def fake_transport_connect(self, **kwargs):
        pass

    monkeypatch.setattr(
        "aim_node.relay.transport.RelayTransport.connect", fake_transport_connect,
    )

    try:
        await handler.on_session_negotiate(_negotiate_event(buyer_pub_b64))
        assert "sess-health-1" in handler._active_sessions

        # Second negotiate for same session should be ignored
        await handler.on_session_negotiate(_negotiate_event(buyer_pub_b64))
        # Still only one session
        assert len(handler._active_sessions) == 1
    finally:
        for task in handler._session_tasks.values():
            task.cancel()
        for task in handler._session_tasks.values():
            try:
                await task
            except asyncio.CancelledError:
                pass
        await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_health_check_marks_unhealthy_after_3_failures(tmp_path):
    """Adapter becomes unhealthy after 3 consecutive health check failures."""
    adapter = HttpJsonAdapter(
        AdapterConfig(
            endpoint_url="http://seller.test/invoke",
            health_check_url="http://seller.test/health",
        )
    )
    adapter._client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(500, request=req)
        )
    )
    try:
        assert adapter._healthy is True
        await adapter.health_check()
        assert adapter._healthy is True  # 1 failure, still healthy
        await adapter.health_check()
        assert adapter._healthy is True  # 2 failures, still healthy
        await adapter.health_check()
        assert adapter._healthy is False  # 3 failures, now unhealthy
    finally:
        await adapter.stop()


@pytest.mark.asyncio
async def test_adapter_health_check_recovers(tmp_path):
    """Adapter recovers to healthy after a successful health check."""
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] <= 3:
            return httpx.Response(500, request=request)
        return httpx.Response(200, request=request)

    adapter = HttpJsonAdapter(
        AdapterConfig(
            endpoint_url="http://seller.test/invoke",
            health_check_url="http://seller.test/health",
        )
    )
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        # 3 failures -> unhealthy
        for _ in range(3):
            await adapter.health_check()
        assert adapter._healthy is False

        # 1 success -> healthy again
        result = await adapter.health_check()
        assert result is True
        assert adapter._healthy is True
    finally:
        await adapter.stop()
