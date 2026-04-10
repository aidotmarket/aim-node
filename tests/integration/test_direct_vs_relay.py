"""Scenario 3: Direct vs relay mode session manager integration tests.

Tests both explicit branches in session_manager.py: direct mode (HTTP)
and relay mode (WebSocket relay transport).
"""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from aim_node.consumer.proxy import LocalProxy
from aim_node.consumer.session_manager import SessionInvokeError, SessionManager, SessionState
from aim_node.core.crypto import DeviceCrypto


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value
    return _inner


def _fake_market_client(payload):
    return SimpleNamespace(
        negotiate_session=_async_return(payload),
        close_session=_async_return(None),
        keepalive_session=_async_return(None),
        search_listings=_async_return([]),
        get_listing=_async_return({}),
    )


# ---------------------------------------------------------------------------
# Direct mode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_direct_connect_and_invoke(core_config, monkeypatch):
    """Connect via direct mode, invoke, verify request flows through."""
    captured = {}

    async def seller_endpoint(request: Request) -> Response:
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = await request.json()
        return JSONResponse({"answer": "42"})

    seller_app = Starlette(routes=[Route("/invoke", seller_endpoint, methods=["POST"])])
    seller_transport = httpx.ASGITransport(app=seller_app)
    original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs.setdefault("transport", seller_transport)
        return original_client(*args, **kwargs)

    monkeypatch.setattr("aim_node.consumer.session_manager.httpx.AsyncClient", patched_client)

    market = _fake_market_client({
        "session_id": "sess-direct-1",
        "connection_mode": "direct",
        "endpoint_url": "http://seller.test/invoke",
        "session_token": "jwt-abc",
        "expires_at": "2026-04-10T12:00:00Z",
    })
    manager = SessionManager(core_config, market)
    try:
        session = await manager.connect("listing-1", 500)
        assert session["connection_mode"] == "direct"
        assert session["session_token"] == "jwt-abc"

        body, headers = await manager.invoke("sess-direct-1", b'{"prompt":"test"}')
        assert b"42" in body
        assert captured["auth"] == "Bearer jwt-abc"
        assert captured["body"] == {"prompt": "test"}
    finally:
        await manager.close_session("sess-direct-1")


@pytest.mark.asyncio
async def test_direct_invoke_timeout_error(core_config, monkeypatch):
    """Direct invoke raises SessionInvokeError on timeout."""
    _original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        transport = httpx.MockTransport(
            lambda req: (_ for _ in ()).throw(httpx.ReadTimeout("timeout", request=req))
        )
        kwargs["transport"] = transport
        return _original_client(*args, **kwargs)

    monkeypatch.setattr("aim_node.consumer.session_manager.httpx.AsyncClient", patched_client)

    market = _fake_market_client({
        "session_id": "sess-timeout",
        "connection_mode": "direct",
        "endpoint_url": "http://seller.test/invoke",
        "session_token": None,
        "expires_at": "2026-04-10T12:00:00Z",
    })
    manager = SessionManager(core_config, market)
    try:
        await manager.connect("listing-timeout", 500)
        with pytest.raises(SessionInvokeError) as exc_info:
            await manager.invoke("sess-timeout", b'{"prompt":"timeout"}')
        assert exc_info.value.code == 1007
    finally:
        await manager.close_session("sess-timeout")


@pytest.mark.asyncio
async def test_direct_invoke_5xx_error(core_config, monkeypatch):
    """Direct invoke raises SessionInvokeError on 5xx from adapter."""
    _original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda req: httpx.Response(503, json={"error": "down"}, request=req)
        )
        return _original_client(*args, **kwargs)

    monkeypatch.setattr("aim_node.consumer.session_manager.httpx.AsyncClient", patched_client)

    market = _fake_market_client({
        "session_id": "sess-503",
        "connection_mode": "direct",
        "endpoint_url": "http://seller.test/invoke",
        "session_token": None,
        "expires_at": "2026-04-10T12:00:00Z",
    })
    manager = SessionManager(core_config, market)
    try:
        await manager.connect("listing-503", 500)
        with pytest.raises(SessionInvokeError) as exc_info:
            await manager.invoke("sess-503", b'{"prompt":"fail"}')
        assert exc_info.value.code == 1006
    finally:
        await manager.close_session("sess-503")


@pytest.mark.asyncio
async def test_direct_invoke_rate_limit(core_config, monkeypatch):
    """Direct invoke raises SessionInvokeError(1005) on HTTP 429."""
    _original_client = httpx.AsyncClient

    def patched_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(
            lambda req: httpx.Response(429, json={"error": "rate limit"}, request=req)
        )
        return _original_client(*args, **kwargs)

    monkeypatch.setattr("aim_node.consumer.session_manager.httpx.AsyncClient", patched_client)

    market = _fake_market_client({
        "session_id": "sess-429",
        "connection_mode": "direct",
        "endpoint_url": "http://seller.test/invoke",
        "session_token": None,
        "expires_at": "2026-04-10T12:00:00Z",
    })
    manager = SessionManager(core_config, market)
    try:
        await manager.connect("listing-429", 500)
        with pytest.raises(SessionInvokeError) as exc_info:
            await manager.invoke("sess-429", b'{"prompt":"rate"}')
        assert exc_info.value.code == 1005
    finally:
        await manager.close_session("sess-429")


# ---------------------------------------------------------------------------
# Relay mode tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_relay_connect_creates_transport(core_config, monkeypatch):
    """Relay mode connect creates a RelayTransport and calls connect."""
    _, seller_pub = DeviceCrypto.generate_ed25519_keypair()
    connect_calls = []

    async def fake_connect(self, **kwargs):
        connect_calls.append(kwargs)

    monkeypatch.setattr(
        "aim_node.consumer.session_manager.RelayTransport.connect", fake_connect
    )

    market = _fake_market_client({
        "session_id": "sess-relay-1",
        "connection_mode": "relay",
        "relay_url": "ws://relay.test",
        "provider_node_id": "seller-node",
        "provider_ed25519_pubkey": base64.b64encode(
            seller_pub.public_bytes_raw()
        ).decode("ascii"),
        "expires_at": "2026-04-10T12:00:00Z",
    })
    manager = SessionManager(core_config, market)
    try:
        session = await manager.connect("listing-relay", 700)
        assert session["connection_mode"] == "relay"
        assert len(connect_calls) == 1
        assert connect_calls[0]["relay_url"] == "ws://relay.test"
        assert connect_calls[0]["is_initiator"] is True
    finally:
        await manager.close_session("sess-relay-1")


@pytest.mark.asyncio
async def test_relay_invoke_uses_transport(core_config, monkeypatch):
    """Relay invoke dispatches through the transport's send_request."""
    _, seller_pub = DeviceCrypto.generate_ed25519_keypair()

    async def fake_connect(self, **kwargs):
        pass

    monkeypatch.setattr(
        "aim_node.consumer.session_manager.RelayTransport.connect", fake_connect
    )

    market = _fake_market_client({
        "session_id": "sess-relay-inv",
        "connection_mode": "relay",
        "relay_url": "ws://relay.test",
        "provider_node_id": "seller-node",
        "provider_ed25519_pubkey": base64.b64encode(
            seller_pub.public_bytes_raw()
        ).decode("ascii"),
        "expires_at": "2026-04-10T12:00:00Z",
    })
    manager = SessionManager(core_config, market)
    try:
        session = await manager.connect("listing-relay-inv", 700)
        state = manager._sessions["sess-relay-inv"]

        # Mock the transport's send_request
        from aim_node.relay.protocol import ResponsePayload

        mock_response = ResponsePayload(
            trace_id="trace-r1",
            sequence=1,
            content_type="application/json",
            body=b'{"relay":"ok"}',
            latency_ms=10,
        )
        state.transport.send_request = AsyncMock(return_value=mock_response)

        body, headers = await manager.invoke("sess-relay-inv", b'{"prompt":"relay"}')
        assert body == b'{"relay":"ok"}'
        assert headers["X-AIM-Trace-Id"] == "trace-r1"
    finally:
        await manager.close_session("sess-relay-inv")


@pytest.mark.asyncio
async def test_invoke_nonexistent_session_raises_1004(core_config):
    """Invoking a session that doesn't exist raises SessionInvokeError(1004)."""
    market = _fake_market_client({})
    manager = SessionManager(core_config, market)
    with pytest.raises(SessionInvokeError) as exc_info:
        await manager.invoke("nonexistent", b'{"prompt":"hi"}')
    assert exc_info.value.code == 1004


@pytest.mark.asyncio
async def test_unsupported_connection_mode_raises(core_config):
    """Unsupported connection_mode raises ValueError."""
    market = _fake_market_client({
        "session_id": "sess-bad",
        "connection_mode": "pigeon",
        "expires_at": "2026-04-10T12:00:00Z",
    })
    manager = SessionManager(core_config, market)
    with pytest.raises(ValueError, match="unsupported connection_mode"):
        await manager.connect("listing-bad", 500)


@pytest.mark.asyncio
async def test_close_session_calls_market_and_transport(core_config, monkeypatch):
    """Closing a relay session calls market close and transport close."""
    _, seller_pub = DeviceCrypto.generate_ed25519_keypair()
    close_calls = []

    async def fake_connect(self, **kwargs):
        pass

    monkeypatch.setattr(
        "aim_node.consumer.session_manager.RelayTransport.connect", fake_connect
    )

    market_close_calls = []

    async def fake_close_session(session_id):
        market_close_calls.append(session_id)

    market = _fake_market_client({
        "session_id": "sess-close-relay",
        "connection_mode": "relay",
        "relay_url": "ws://relay.test",
        "provider_node_id": "seller-node",
        "provider_ed25519_pubkey": base64.b64encode(
            seller_pub.public_bytes_raw()
        ).decode("ascii"),
        "expires_at": "2026-04-10T12:00:00Z",
    })
    market.close_session = fake_close_session
    manager = SessionManager(core_config, market)

    try:
        await manager.connect("listing-close", 700)
        state = manager._sessions["sess-close-relay"]
        transport_close_calls = []

        async def fake_transport_close(reason="buyer_requested"):
            transport_close_calls.append(reason)

        state.transport.close = fake_transport_close

        await manager.close_session("sess-close-relay")
        assert market_close_calls == ["sess-close-relay"]
        assert transport_close_calls == ["buyer_requested"]
        assert "sess-close-relay" not in manager._sessions
    finally:
        pass
