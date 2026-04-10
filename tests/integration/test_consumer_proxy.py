"""Scenario 2: Consumer local proxy integration tests.

Tests the full consumer proxy HTTP layer: /aim/sessions/connect,
/aim/invoke/{session_id}, /aim/sessions listing, detail, and close.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from aim_node.consumer.proxy import LocalProxy
from aim_node.consumer.session_manager import SessionInvokeError, SessionState


# ---------------------------------------------------------------------------
# Stub session manager for proxy-level tests
# ---------------------------------------------------------------------------


class StubSessionManager:
    def __init__(self):
        self._market_client = SimpleNamespace(
            search_listings=self._search_listings,
            get_listing=self._get_listing,
        )
        self.invoke_result = (b'{"ok":true}', {"X-AIM-Trace-Id": "t1"})
        self.invoke_error = None
        self.connect_result = {
            "session_id": "session-proxy-1",
            "connection_mode": "direct",
            "endpoint_url": "https://seller.example/invoke",
            "expires_at": "2026-04-10T12:00:00Z",
        }
        self.sessions = []
        self.session_map = {}
        self.closed = []

    async def invoke(self, session_id, body):
        if self.invoke_error is not None:
            raise self.invoke_error
        return self.invoke_result

    async def connect(self, listing_id, max_spend_cents):
        return dict(self.connect_result)

    async def list_sessions(self):
        return list(self.sessions)

    async def get_session(self, session_id):
        return self.session_map.get(session_id)

    async def close_session(self, session_id):
        self.closed.append(session_id)

    async def _search_listings(self, query):
        return [{"id": "listing-1", "q": query}]

    async def _get_listing(self, listing_id):
        return {"id": listing_id}


def _make_proxy_client(core_config):
    sm = StubSessionManager()
    proxy = LocalProxy(core_config, sm)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=proxy._app),
        base_url="http://testserver",
    )
    return sm, client


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_connect_returns_session(core_config):
    sm, client = _make_proxy_client(core_config)
    try:
        async with client:
            r = await client.post(
                "/aim/sessions/connect",
                json={"listing_id": "listing-1", "max_spend_cents": 500},
            )
        assert r.status_code == 200
        body = r.json()
        assert body["session_id"] == "session-proxy-1"
        assert body["connection_mode"] == "direct"
    finally:
        pass


@pytest.mark.asyncio
async def test_invoke_success_with_headers(core_config):
    sm, client = _make_proxy_client(core_config)
    sm.invoke_result = (
        b'{"result":"ok"}',
        {"X-AIM-Trace-Id": "trace-42", "X-AIM-Latency-Ms": "5", "X-AIM-Sequence": "1"},
    )
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hello"})
        assert r.status_code == 200
        assert r.json() == {"result": "ok"}
        assert r.headers["X-AIM-Trace-Id"] == "trace-42"
        assert r.headers["X-AIM-Latency-Ms"] == "5"
    finally:
        pass


@pytest.mark.asyncio
async def test_invoke_expired_session(core_config):
    sm, client = _make_proxy_client(core_config)
    sm.invoke_error = SessionInvokeError(1004, "session expired")
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-gone", json={"prompt": "hi"})
        assert r.status_code == 410
        assert r.json()["code"] == 1004
    finally:
        pass


@pytest.mark.asyncio
async def test_invoke_rate_limited(core_config):
    sm, client = _make_proxy_client(core_config)
    sm.invoke_error = SessionInvokeError(1005, "rate limited")
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 429
    finally:
        pass


@pytest.mark.asyncio
async def test_invoke_timeout(core_config):
    sm, client = _make_proxy_client(core_config)
    sm.invoke_error = SessionInvokeError(1007, "timeout")
    try:
        async with client:
            r = await client.post("/aim/invoke/sess-1", json={"prompt": "hi"})
        assert r.status_code == 504
    finally:
        pass


@pytest.mark.asyncio
async def test_invoke_invalid_json_body(core_config):
    sm, client = _make_proxy_client(core_config)
    try:
        async with client:
            r = await client.post(
                "/aim/invoke/sess-1",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
        assert r.status_code == 400
    finally:
        pass


@pytest.mark.asyncio
async def test_invoke_wrong_content_type(core_config):
    sm, client = _make_proxy_client(core_config)
    try:
        async with client:
            r = await client.post(
                "/aim/invoke/sess-1",
                content=b"data",
                headers={"Content-Type": "text/plain"},
            )
        assert r.status_code == 415
    finally:
        pass


@pytest.mark.asyncio
async def test_invoke_oversized_body(core_config):
    sm, client = _make_proxy_client(core_config)
    payload = b'{"data":"' + b"x" * 33_000 + b'"}'
    try:
        async with client:
            r = await client.post(
                "/aim/invoke/sess-1",
                content=payload,
                headers={"Content-Type": "application/json"},
            )
        assert r.status_code == 413
    finally:
        pass


@pytest.mark.asyncio
async def test_list_sessions(core_config):
    sm, client = _make_proxy_client(core_config)
    sm.sessions = [
        {"session_id": "s1", "mode": "direct"},
        {"session_id": "s2", "mode": "relay"},
    ]
    try:
        async with client:
            r = await client.get("/aim/sessions")
        assert r.status_code == 200
        assert len(r.json()) == 2
    finally:
        pass


@pytest.mark.asyncio
async def test_session_detail_found(core_config):
    sm, client = _make_proxy_client(core_config)
    sm.session_map["sess-1"] = {"session_id": "sess-1", "mode": "direct"}
    try:
        async with client:
            r = await client.get("/aim/sessions/sess-1")
        assert r.status_code == 200
        assert r.json()["session_id"] == "sess-1"
    finally:
        pass


@pytest.mark.asyncio
async def test_session_detail_not_found(core_config):
    sm, client = _make_proxy_client(core_config)
    try:
        async with client:
            r = await client.get("/aim/sessions/nonexistent")
        assert r.status_code == 404
    finally:
        pass


@pytest.mark.asyncio
async def test_session_delete_closes(core_config):
    sm, client = _make_proxy_client(core_config)
    try:
        async with client:
            r = await client.delete("/aim/sessions/sess-close")
        assert r.status_code == 204
        assert sm.closed == ["sess-close"]
    finally:
        pass


@pytest.mark.asyncio
async def test_marketplace_search(core_config):
    sm, client = _make_proxy_client(core_config)
    try:
        async with client:
            r = await client.get("/aim/marketplace/search?q=llm")
        assert r.status_code == 200
        assert r.json()[0]["q"] == "llm"
    finally:
        pass


@pytest.mark.asyncio
async def test_marketplace_listing_detail(core_config):
    sm, client = _make_proxy_client(core_config)
    try:
        async with client:
            r = await client.get("/aim/marketplace/listings/lst-42")
        assert r.status_code == 200
        assert r.json()["id"] == "lst-42"
    finally:
        pass
