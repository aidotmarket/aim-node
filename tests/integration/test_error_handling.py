"""Scenario 7: Error handling integration tests.

Tests invalid tokens, expired sessions, malformed requests, and edge
cases across management API, consumer proxy, and protocol layers.
"""

from __future__ import annotations

import json

import httpx
import pytest

from aim_node.consumer.proxy import LocalProxy
from aim_node.consumer.session_manager import SessionInvokeError
from aim_node.relay.protocol import (
    FRAME_HEARTBEAT,
    FRAME_HEARTBEAT_ACK,
    FRAME_CLOSE_ACK,
    FRAME_REQUEST,
    FRAME_RESPONSE,
    ClosePayload,
    ErrorPayload,
    RequestPayload,
    ResponsePayload,
    deserialize_payload,
    serialize_payload,
)

from .conftest import make_client, patch_httpx


# ---------------------------------------------------------------------------
# Stub session manager for proxy error tests
# ---------------------------------------------------------------------------


class ErrorStubSessionManager:
    def __init__(self, error=None):
        self._market_client = type("M", (), {
            "search_listings": staticmethod(lambda q: []),
            "get_listing": staticmethod(lambda lid: {}),
        })()
        self.error = error

    async def invoke(self, session_id, body):
        if self.error:
            raise self.error
        return b'{"ok":true}', {}


def _error_proxy_client(core_config, error=None):
    sm = ErrorStubSessionManager(error)
    proxy = LocalProxy(core_config, sm)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=proxy._app),
        base_url="http://testserver",
    )
    return sm, client


# ---------------------------------------------------------------------------
# Management API error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_locked_provider_start_returns_423(locked_app):
    """Provider start on locked node returns 423."""
    app, state, pm = locked_app
    async with make_client(app) as client:
        r = await client.post("/api/mgmt/provider/start")
    assert r.status_code == 423
    assert "locked" in r.json()["error"].lower() or "unlock" in r.json()["error"].lower()


@pytest.mark.asyncio
async def test_locked_consumer_start_returns_423(locked_app):
    """Consumer start on locked node returns 423."""
    app, state, pm = locked_app
    async with make_client(app) as client:
        r = await client.post("/api/mgmt/consumer/start")
    assert r.status_code == 423


@pytest.mark.asyncio
async def test_setup_incomplete_provider_start_returns_412(fresh_app):
    """Provider start before setup returns 412."""
    app, state, pm = fresh_app
    async with make_client(app) as client:
        r = await client.post("/api/mgmt/provider/start")
    assert r.status_code == 412


@pytest.mark.asyncio
async def test_setup_incomplete_consumer_start_returns_412(fresh_app):
    """Consumer start before setup returns 412."""
    app, state, pm = fresh_app
    async with make_client(app) as client:
        r = await client.post("/api/mgmt/consumer/start")
    assert r.status_code == 412


@pytest.mark.asyncio
async def test_unlock_wrong_passphrase_returns_401(locked_app):
    """Wrong passphrase returns 401."""
    app, state, pm = locked_app
    async with make_client(app) as client:
        r = await client.post("/api/mgmt/unlock", json={"passphrase": "wrong-pass"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_duplicate_keypair_returns_409(setup_consumer_app):
    """Creating keypair when one already exists returns 409."""
    app, state, pm = setup_consumer_app
    async with make_client(app) as client:
        r = await client.post("/api/mgmt/setup/keypair", json={"passphrase": ""})
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_config_update_invalid_mode_returns_422(setup_consumer_app):
    """Invalid mode in config update returns 422."""
    app, state, pm = setup_consumer_app
    async with make_client(app) as client:
        r = await client.put("/api/mgmt/config", json={"mode": "invalid"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_config_update_provider_without_upstream_returns_422(setup_consumer_app):
    """Provider mode without upstream_url returns 422."""
    app, state, pm = setup_consumer_app
    async with make_client(app) as client:
        r = await client.put("/api/mgmt/config", json={"mode": "provider"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_finalize_invalid_url_scheme_returns_422(fresh_app):
    """Finalize with non-HTTP URL returns 422."""
    app, state, pm = fresh_app
    async with make_client(app) as client:
        r = await client.post(
            "/api/mgmt/setup/finalize",
            json={
                "mode": "consumer",
                "api_url": "ftp://api.example.test",
                "api_key": "key",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_finalize_provider_without_upstream_returns_422(fresh_app):
    """Finalize as provider without upstream_url returns 422."""
    app, state, pm = fresh_app
    async with make_client(app) as client:
        r = await client.post(
            "/api/mgmt/setup/finalize",
            json={
                "mode": "provider",
                "api_url": "https://api.example.test",
                "api_key": "key",
            },
        )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_session_detail_nonexistent_returns_404(setup_consumer_app):
    """Session detail for nonexistent session returns 404."""
    app, state, pm = setup_consumer_app
    async with make_client(app) as client:
        r = await client.get("/api/mgmt/sessions/nonexistent-session")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_keypair_info_no_keystore_returns_404(fresh_app):
    """Keypair info with no keystore returns 404."""
    app, state, pm = fresh_app
    async with make_client(app) as client:
        r = await client.get("/api/mgmt/keypair")
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Consumer proxy error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_proxy_expired_session_returns_410(core_config):
    sm, client = _error_proxy_client(
        core_config, SessionInvokeError(1004, "session expired")
    )
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 410
        assert r.json()["code"] == 1004
    finally:
        pass


@pytest.mark.asyncio
async def test_proxy_auth_error_returns_401(core_config):
    sm, client = _error_proxy_client(
        core_config, SessionInvokeError(1003, "unauthorized")
    )
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 401
    finally:
        pass


@pytest.mark.asyncio
async def test_proxy_adapter_error_returns_502(core_config):
    sm, client = _error_proxy_client(
        core_config, SessionInvokeError(1006, "adapter error")
    )
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 502
    finally:
        pass


@pytest.mark.asyncio
async def test_proxy_timeout_returns_504(core_config):
    sm, client = _error_proxy_client(
        core_config, SessionInvokeError(1007, "timeout")
    )
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 504
    finally:
        pass


@pytest.mark.asyncio
async def test_proxy_request_too_large_returns_413(core_config):
    sm, client = _error_proxy_client(
        core_config, SessionInvokeError(1008, "too large")
    )
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 413
    finally:
        pass


@pytest.mark.asyncio
async def test_proxy_session_closing_returns_503(core_config):
    sm, client = _error_proxy_client(
        core_config, SessionInvokeError(1010, "session closing")
    )
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 503
    finally:
        pass


# ---------------------------------------------------------------------------
# Protocol layer error handling
# ---------------------------------------------------------------------------


def test_deserialize_control_frame_with_payload_raises():
    """Control frames (heartbeat, heartbeat_ack, close_ack) must be empty."""
    with pytest.raises(ValueError, match="must not include"):
        deserialize_payload(FRAME_HEARTBEAT, b'{"data": 1}')
    with pytest.raises(ValueError, match="must not include"):
        deserialize_payload(FRAME_HEARTBEAT_ACK, b'{"data": 1}')
    with pytest.raises(ValueError, match="must not include"):
        deserialize_payload(FRAME_CLOSE_ACK, b'{"data": 1}')


def test_deserialize_control_frame_empty_is_ok():
    """Control frames with empty payload succeed."""
    assert deserialize_payload(FRAME_HEARTBEAT, b"") is None
    assert deserialize_payload(FRAME_HEARTBEAT_ACK, b"") is None
    assert deserialize_payload(FRAME_CLOSE_ACK, b"") is None


def test_deserialize_invalid_json_raises():
    """Non-JSON payload raises ValueError."""
    with pytest.raises((ValueError, json.JSONDecodeError)):
        deserialize_payload(FRAME_REQUEST, b"not json")


def test_deserialize_non_object_raises():
    """Array payload raises ValueError."""
    with pytest.raises(ValueError, match="object"):
        deserialize_payload(FRAME_REQUEST, b"[1,2,3]")


def test_deserialize_unsupported_frame_type_raises():
    """Unknown frame type raises ValueError."""
    with pytest.raises(ValueError, match="unsupported"):
        deserialize_payload(0xFF, b'{"key":"val"}')


def test_serialize_non_dataclass_raises():
    """Serializing a non-dataclass raises TypeError."""
    with pytest.raises(TypeError, match="dataclass"):
        serialize_payload({"not": "a dataclass"})


def test_error_payload_message_too_long_raises():
    """Error payload with message > 500 chars raises ValueError."""
    payload = ErrorPayload(trace_id="t1", code=1000, message="x" * 501)
    with pytest.raises(ValueError, match="500"):
        serialize_payload(payload)


def test_request_payload_invalid_timeout_raises():
    """Request payload with timeout_ms > 300000 raises ValueError."""
    payload = RequestPayload(
        trace_id="t1",
        sequence=1,
        content_type="application/json",
        body=b"{}",
        timeout_ms=999999,
    )
    with pytest.raises(ValueError, match="timeout_ms"):
        serialize_payload(payload)


def test_close_payload_message_too_long_raises():
    """Close payload with message > 500 chars raises ValueError."""
    payload = ClosePayload(reason="error", message="x" * 501)
    with pytest.raises(ValueError, match="500"):
        serialize_payload(payload)
