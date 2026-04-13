from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from aim_node.core.auth import AuthError, AuthService
from aim_node.core.config import AIMCoreConfig
from aim_node.core.market_client import (
    MarketClient,
    MarketClientError,
    MarketClientHTTPError,
)
from aim_node.management.errors import make_market_error
from aim_node.management.facade import FacadeError, MarketplaceFacade


@pytest.fixture
def facade_config(tmp_path: Path) -> AIMCoreConfig:
    return AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-123",
        data_dir=tmp_path,
        api_key="api-key",
        node_id="node-backend-123",
    )


@pytest.mark.asyncio
async def test_facade_get_injects_bearer_auth(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    captured: dict[str, object] = {}

    async def fake_get_auth_headers(self) -> dict[str, str]:
        return {"Authorization": "Bearer token-123"}

    async def fake_request(self, method, path, *, params=None, json_body=None):
        captured["method"] = method
        captured["path"] = path
        captured["params"] = params
        captured["headers"] = await self._auth_headers()
        return {"ok": True}

    monkeypatch.setattr(AuthService, "get_auth_headers", fake_get_auth_headers)
    monkeypatch.setattr(MarketClient, "_request", fake_request)

    facade = MarketplaceFacade.create(facade_config)
    payload = await facade.get("/aim/nodes/mine")

    assert payload == {"ok": True}
    assert captured["method"] == "GET"
    assert captured["path"] == "/aim/nodes/mine"
    assert captured["headers"] == {"Authorization": "Bearer token-123"}


@pytest.mark.asyncio
async def test_facade_cache_hit_skips_request(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    calls = 0

    async def fake_request(self, method, path, *, params=None, json_body=None):
        nonlocal calls
        calls += 1
        return {"calls": calls}

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)

    first = await facade.get("/aim/nodes/mine", cache_ttl_s=30.0)
    second = await facade.get("/aim/nodes/mine", cache_ttl_s=30.0)

    assert first == {"calls": 1}
    assert second == {"calls": 1}
    assert calls == 1


@pytest.mark.asyncio
async def test_facade_cache_miss_after_ttl(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    calls = 0
    monotonic_values = iter([100.0, 102.0, 102.0, 102.0, 102.0])

    async def fake_request(self, method, path, *, params=None, json_body=None):
        nonlocal calls
        calls += 1
        return {"calls": calls}

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    monkeypatch.setattr(
        "aim_node.management.facade.time.monotonic",
        lambda: next(monotonic_values),
    )
    facade = MarketplaceFacade.create(facade_config)

    first = await facade.get("/aim/nodes/mine", cache_ttl_s=1.0)
    second = await facade.get("/aim/nodes/mine", cache_ttl_s=1.0)

    assert first == {"calls": 1}
    assert second == {"calls": 2}
    assert calls == 2


@pytest.mark.asyncio
async def test_facade_market_error_wraps_to_facade_error(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    async def fake_request(self, method, path, *, params=None, json_body=None):
        raise MarketClientHTTPError(403, "forbidden")

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)

    with pytest.raises(FacadeError) as exc_info:
        await facade.get("/aim/nodes/mine")

    assert exc_info.value.http_status == 502
    assert exc_info.value.normalized.code == "market_error"


@pytest.mark.asyncio
async def test_facade_network_error_wraps_to_market_unreachable(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    async def fake_request(self, method, path, *, params=None, json_body=None):
        raise MarketClientError("connection refused")

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)

    with pytest.raises(FacadeError) as exc_info:
        await facade.get("/aim/nodes/mine")

    assert exc_info.value.http_status == 502
    assert exc_info.value.normalized.code == "market_unreachable"


@pytest.mark.asyncio
async def test_facade_timeout_wraps_to_market_timeout(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    async def fake_request(self, method, path, *, params=None, json_body=None):
        raise MarketClientError("read timeout")

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)

    with pytest.raises(FacadeError) as exc_info:
        await facade.get("/aim/nodes/mine")

    assert exc_info.value.http_status == 504
    assert exc_info.value.normalized.code == "market_timeout"


def test_make_market_error_passthrough_shape() -> None:
    err = make_market_error(502, "upstream bad gateway", "/aim/test")

    assert err.code == "market_error"
    assert err.details == {
        "status": 502,
        "backend_error": "upstream bad gateway",
        "endpoint": "/aim/test",
    }


@pytest.mark.asyncio
async def test_facade_retry_on_401_refreshes_and_succeeds(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    calls = 0
    refresh = AsyncMock()

    async def fake_request(self, method, path, *, params=None, json_body=None):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise MarketClientHTTPError(401, "expired")
        return {"ok": True}

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)
    facade.client.auth_service.refresh = refresh

    payload = await facade.get("/aim/nodes/mine")

    assert payload == {"ok": True}
    assert calls == 2
    refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_facade_retry_on_401_refresh_fails_raises(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    async def fake_request(self, method, path, *, params=None, json_body=None):
        raise MarketClientHTTPError(401, "expired")

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)
    facade.client.auth_service.refresh = AsyncMock(
        side_effect=AuthError("refresh failed")
    )

    with pytest.raises(FacadeError) as exc_info:
        await facade.get("/aim/nodes/mine")

    assert exc_info.value.http_status == 401
    assert exc_info.value.normalized.code == "auth_failed"


@pytest.mark.asyncio
async def test_facade_no_double_retry_on_401(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    calls = 0
    refresh = AsyncMock()

    async def fake_request(self, method, path, *, params=None, json_body=None):
        nonlocal calls
        calls += 1
        raise MarketClientHTTPError(401, "still expired")

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)
    facade.client.auth_service.refresh = refresh

    with pytest.raises(FacadeError) as exc_info:
        await facade.get("/aim/nodes/mine")

    assert calls == 2
    refresh.assert_awaited_once()
    assert exc_info.value.normalized.code == "market_error"
    assert exc_info.value.normalized.details == {
        "status": 401,
        "backend_error": "still expired",
        "endpoint": "/aim/nodes/mine",
    }


@pytest.mark.asyncio
async def test_facade_invalidate_cache_clears_prefix(
    monkeypatch: pytest.MonkeyPatch,
    facade_config: AIMCoreConfig,
) -> None:
    async def fake_request(self, method, path, *, params=None, json_body=None):
        return {"path": path}

    monkeypatch.setattr(MarketClient, "_request", fake_request)
    facade = MarketplaceFacade.create(facade_config)

    await facade.get(f"/aim/nodes/{facade.node_id}/tools", cache_ttl_s=30.0)
    await facade.get("/aim/payouts/summary", cache_ttl_s=30.0)
    facade.invalidate_cache(f"GET:/aim/nodes/{facade.node_id}/tools")

    assert (
        facade._get_cache(f"GET:/aim/nodes/{facade.node_id}/tools:None") is None
    )
    assert facade._get_cache("GET:/aim/payouts/summary:None") == {
        "path": "/aim/payouts/summary"
    }
