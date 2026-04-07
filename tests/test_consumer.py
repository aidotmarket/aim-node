from __future__ import annotations

import asyncio
from types import SimpleNamespace

import httpx
import pytest

from aim_node.consumer.proxy import LocalProxy
from aim_node.consumer.session_manager import (
    KEEPALIVE_INTERVAL_S,
    SessionInvokeError,
    SessionManager,
    SessionState,
)
from aim_node.core.crypto import DeviceCrypto
from aim_node.relay.protocol import ResponsePayload


class StubSessionManager:
    def __init__(self) -> None:
        self._market_client = SimpleNamespace(
            search_listings=self._search_listings,
            get_listing=self._get_listing,
        )
        self.invoke_result = (b'{"ok":true}', {})
        self.invoke_error: Exception | None = None

    async def invoke(self, session_id: str, body: bytes):
        if self.invoke_error is not None:
            raise self.invoke_error
        return self.invoke_result

    async def connect(self, listing_id: str, max_spend_cents: int):
        return {
            "session_id": "session-1",
            "connection_mode": "direct",
            "endpoint_url": "https://seller.example/invoke",
            "expires_at": "2026-04-07T12:00:00Z",
        }

    async def list_sessions(self):
        return [{"session_id": "session-1"}]

    async def get_session(self, session_id: str):
        return {"session_id": session_id}

    async def close_session(self, session_id: str) -> None:
        return None

    async def _search_listings(self, query: str):
        return [{"id": "listing-1", "query": query}]

    async def _get_listing(self, listing_id: str):
        return {"id": listing_id}


def _proxy_client(core_config) -> tuple[StubSessionManager, httpx.AsyncClient]:
    session_manager = StubSessionManager()
    proxy = LocalProxy(core_config, session_manager)  # type: ignore[arg-type]
    transport = httpx.ASGITransport(app=proxy._app)
    client = httpx.AsyncClient(transport=transport, base_url="http://testserver")
    return session_manager, client


@pytest.mark.asyncio
async def test_proxy_invoke_success(core_config) -> None:
    session_manager, client = _proxy_client(core_config)
    session_manager.invoke_result = (
        b'{"ok":true}',
        {
            "X-AIM-Trace-Id": "trace-1",
            "X-AIM-Latency-Ms": "12",
            "X-AIM-Sequence": "3",
        },
    )

    async with client:
        response = await client.post("/aim/invoke/session-1", json={"prompt": "hi"})

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert response.headers["X-AIM-Trace-Id"] == "trace-1"
    assert response.headers["X-AIM-Latency-Ms"] == "12"
    assert response.headers["X-AIM-Sequence"] == "3"


@pytest.mark.asyncio
async def test_proxy_invoke_non_post_returns_405(core_config) -> None:
    _, client = _proxy_client(core_config)

    async with client:
        response = await client.get("/aim/invoke/session-1")

    assert response.status_code == 405


@pytest.mark.asyncio
async def test_proxy_invoke_non_json_returns_415(core_config) -> None:
    _, client = _proxy_client(core_config)

    async with client:
        response = await client.post(
            "/aim/invoke/session-1",
            content="not-json",
            headers={"Content-Type": "text/plain"},
        )

    assert response.status_code == 415


@pytest.mark.asyncio
async def test_proxy_invoke_oversized_body_returns_413(core_config) -> None:
    _, client = _proxy_client(core_config)
    payload = b'{' + (b'"a"' * 16_385) + b'}'

    async with client:
        response = await client.post(
            "/aim/invoke/session-1",
            content=payload,
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 413


@pytest.mark.asyncio
async def test_proxy_invoke_invalid_json_returns_400(core_config) -> None:
    _, client = _proxy_client(core_config)

    async with client:
        response = await client.post(
            "/aim/invoke/session-1",
            content=b"{invalid",
            headers={"Content-Type": "application/json"},
        )

    assert response.status_code == 400


@pytest.mark.asyncio
async def test_proxy_invoke_expired_session_returns_410(core_config) -> None:
    session_manager, client = _proxy_client(core_config)
    session_manager.invoke_error = SessionInvokeError(1004, "expired")

    async with client:
        response = await client.post("/aim/invoke/session-1", json={"prompt": "hi"})

    assert response.status_code == 410


@pytest.mark.asyncio
async def test_proxy_invoke_timeout_returns_504(core_config) -> None:
    session_manager, client = _proxy_client(core_config)
    session_manager.invoke_error = SessionInvokeError(1007, "timeout")

    async with client:
        response = await client.post("/aim/invoke/session-1", json={"prompt": "hi"})

    assert response.status_code == 504


@pytest.mark.asyncio
async def test_proxy_invoke_adapter_error_returns_502(core_config) -> None:
    session_manager, client = _proxy_client(core_config)
    session_manager.invoke_error = SessionInvokeError(1006, "adapter")

    async with client:
        response = await client.post("/aim/invoke/session-1", json={"prompt": "hi"})

    assert response.status_code == 502


@pytest.mark.asyncio
async def test_session_connect_direct_mode(core_config) -> None:
    market_client = SimpleNamespace(
        negotiate_session=_async_return(
            {
                "session_id": "session-1",
                "connection_mode": "direct",
                "endpoint_url": "https://seller.example/invoke",
                "session_token": "jwt-1",
                "expires_at": "2026-04-07T12:00:00Z",
            }
        ),
        close_session=_async_return(None),
        keepalive_session=_async_return(None),
    )
    manager = SessionManager(core_config, market_client)  # type: ignore[arg-type]

    session = await manager.connect("listing-1", 500)

    assert session["session_id"] == "session-1"
    assert session["connection_mode"] == "direct"
    assert session["endpoint_url"] == "https://seller.example/invoke"
    assert session["session_token"] == "jwt-1"
    await manager.close_session("session-1")


@pytest.mark.asyncio
async def test_session_connect_relay_mode(core_config, monkeypatch: pytest.MonkeyPatch) -> None:
    _, seller_pub = DeviceCrypto.generate_ed25519_keypair()
    market_client = SimpleNamespace(
        negotiate_session=_async_return(
            {
                "session_id": "session-2",
                "connection_mode": "relay",
                "relay_url": "relay.example",
                "provider_node_id": "seller-1",
                "provider_ed25519_pubkey": seller_pub.public_bytes_raw().hex(),
                "expires_at": "2026-04-07T12:00:00Z",
            }
        ),
        close_session=_async_return(None),
        keepalive_session=_async_return(None),
    )
    connect_calls: list[dict[str, object]] = []

    async def fake_connect(self, **kwargs) -> None:
        connect_calls.append(kwargs)

    monkeypatch.setattr("aim_node.consumer.session_manager.RelayTransport.connect", fake_connect)
    monkeypatch.setattr(
        "aim_node.consumer.session_manager.base64.b64decode",
        lambda value, validate=True: bytes.fromhex(value.decode("ascii") if isinstance(value, bytes) else value),
    )
    manager = SessionManager(core_config, market_client)  # type: ignore[arg-type]

    session = await manager.connect("listing-2", 700)

    assert session["connection_mode"] == "relay"
    assert connect_calls[0]["relay_url"] == "relay.example"
    assert connect_calls[0]["is_initiator"] is True
    await manager.close_session("session-2")


@pytest.mark.asyncio
async def test_session_close_calls_market_api(core_config) -> None:
    close_calls: list[str] = []
    market_client = SimpleNamespace(
        negotiate_session=_async_return({}),
        keepalive_session=_async_return(None),
        close_session=_async_append(close_calls),
    )
    manager = SessionManager(core_config, market_client)  # type: ignore[arg-type]
    manager._sessions["session-1"] = SessionState(
        session_id="session-1",
        connection_mode="direct",
        endpoint_url="https://seller.example",
        session_token="jwt-1",
        transport=None,
        expires_at="2026-04-07T12:00:00Z",
        created_at=0.0,
    )

    await manager.close_session("session-1")

    assert close_calls == ["session-1"]


@pytest.mark.asyncio
async def test_session_list_returns_active(core_config) -> None:
    market_client = SimpleNamespace(
        negotiate_session=_async_return({}),
        keepalive_session=_async_return(None),
        close_session=_async_return(None),
    )
    manager = SessionManager(core_config, market_client)  # type: ignore[arg-type]
    manager._sessions["session-1"] = SessionState(
        session_id="session-1",
        connection_mode="direct",
        endpoint_url="https://seller.example",
        session_token="jwt-1",
        transport=None,
        expires_at="2026-04-07T12:00:00Z",
        created_at=0.0,
    )

    sessions = await manager.list_sessions()

    assert len(sessions) == 1
    assert sessions[0]["session_id"] == "session-1"


@pytest.mark.asyncio
async def test_session_keepalive_runs_every_4_min(core_config, monkeypatch: pytest.MonkeyPatch) -> None:
    keepalive_calls: list[str] = []
    market_client = SimpleNamespace(
        negotiate_session=_async_return({}),
        keepalive_session=_async_append(keepalive_calls),
        close_session=_async_return(None),
    )
    manager = SessionManager(core_config, market_client)  # type: ignore[arg-type]
    manager._sessions["session-1"] = SessionState(
        session_id="session-1",
        connection_mode="direct",
        endpoint_url="https://seller.example",
        session_token="jwt-1",
        transport=None,
        expires_at="2026-04-07T12:00:00Z",
        created_at=0.0,
    )
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        manager._sessions.pop("session-1", None)

    monkeypatch.setattr("aim_node.consumer.session_manager.asyncio.sleep", fake_sleep)

    await manager._keepalive_loop("session-1")

    assert sleep_calls == [KEEPALIVE_INTERVAL_S]
    assert keepalive_calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("code", "status_code"),
    [
        (1004, 410),
        (1005, 429),
        (1006, 502),
        (1007, 504),
        (1008, 413),
        (1009, 499),
        (1010, 503),
        (1011, 502),
    ],
)
async def test_proxy_status_mapping_all_codes(core_config, code: int, status_code: int) -> None:
    session_manager, client = _proxy_client(core_config)
    session_manager.invoke_error = SessionInvokeError(code, f"error-{code}")

    async with client:
        response = await client.post("/aim/invoke/session-1", json={"prompt": "hi"})

    assert response.status_code == status_code


def _async_return(value):
    async def _inner(*args, **kwargs):
        return value

    return _inner


def _async_append(target: list[str]):
    async def _inner(value: str):
        target.append(value)
        return None

    return _inner
