from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from aim_node.core.auth import AuthService
from aim_node.core.config import AIMCoreConfig
from aim_node.core.connectivity_token import ConnectivityTokenService
from aim_node.core.market_client import MarketClient
from aim_node.core.trust_channel import TrustChannelClient


def test_trust_channel_init_with_config(tmp_path: Path) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        market_ws_url="wss://market.example/ws/trust-channel",
    )

    client = TrustChannelClient(config)

    assert client.config is config
    assert client.ws_url == "wss://market.example/ws/trust-channel"


def test_trust_channel_reconnect_params_from_config(tmp_path: Path) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        reconnect_delay_s=1.5,
        reconnect_max_delay_s=9.0,
        reconnect_jitter=0.9,
    )

    client = TrustChannelClient(config)

    assert client.reconnect_delay_s == 1.5
    assert client.reconnect_max_delay_s == 9.0
    assert client.reconnect_jitter == 0.9


@pytest.mark.asyncio
async def test_trust_channel_session_negotiate_handler(core_config: AIMCoreConfig) -> None:
    client = TrustChannelClient(core_config)

    await client._dispatch_message(
        {
            "action": "SESSION_NEGOTIATE",
            "transfer_id": "test-transfer-1",
            "buyer_node_id": "buyer-1",
            "buyer_ed25519_pubkey": "pubkey-xyz",
        }
    )
    await asyncio.sleep(0)

    assert client._negotiations["test-transfer-1"]["buyer_node_id"] == "buyer-1"
    assert client._negotiations["test-transfer-1"]["buyer_ed25519_pubkey"] == "pubkey-xyz"


@pytest.mark.asyncio
async def test_concurrent_negotiations(core_config: AIMCoreConfig) -> None:
    client = TrustChannelClient(core_config)

    await client._dispatch_message(
        {
            "action": "SESSION_NEGOTIATE",
            "transfer_id": "test-transfer-1",
            "buyer_node_id": "buyer-1",
            "buyer_ed25519_pubkey": "pubkey-1",
        }
    )
    await client._dispatch_message(
        {
            "action": "SESSION_NEGOTIATE",
            "transfer_id": "test-transfer-2",
            "buyer_node_id": "buyer-2",
            "buyer_ed25519_pubkey": "pubkey-2",
        }
    )
    await asyncio.sleep(0)

    assert client._negotiations["test-transfer-1"] == {
        "buyer_node_id": "buyer-1",
        "buyer_ed25519_pubkey": "pubkey-1",
    }
    assert client._negotiations["test-transfer-2"] == {
        "buyer_node_id": "buyer-2",
        "buyer_ed25519_pubkey": "pubkey-2",
    }

    assert client.pop_negotiation("test-transfer-1") == {
        "buyer_node_id": "buyer-1",
        "buyer_ed25519_pubkey": "pubkey-1",
    }
    assert "test-transfer-1" not in client._negotiations
    assert client.pop_negotiation("test-transfer-2") == {
        "buyer_node_id": "buyer-2",
        "buyer_ed25519_pubkey": "pubkey-2",
    }
    assert "test-transfer-2" not in client._negotiations


def test_auth_service_init_with_config(core_config: AIMCoreConfig) -> None:
    service = AuthService(core_config)

    assert service.config is core_config
    assert service.token_path == core_config.data_dir / "auth_token.json"


def test_auth_service_uses_market_api_url(tmp_path: Path) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        market_api_url="https://market.example/api",
        api_key="key-123",
    )

    service = AuthService(config)

    assert service.base_url == "https://market.example/api"


def test_connectivity_token_init_with_config(core_config: AIMCoreConfig) -> None:
    auth_service = AuthService(core_config)
    service = ConnectivityTokenService(core_config, auth_service)

    assert service.config is core_config
    assert service.auth_service is auth_service
    assert service.base_url == core_config.market_api_url


class MockAsyncClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float,
        handler,
    ) -> None:
        self.base_url = base_url
        self.timeout = timeout
        self._handler = handler

    async def __aenter__(self) -> MockAsyncClient:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        return None

    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        return self._handler(method, path, kwargs, self.base_url, self.timeout)


@pytest.mark.asyncio
async def test_market_client_negotiate_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        api_key="api-key",
    )
    captured: dict[str, Any] = {}

    def handler(method: str, path: str, kwargs: dict[str, Any], base_url: str, timeout: float) -> httpx.Response:
        captured.update(
            {
                "method": method,
                "path": path,
                "json": kwargs.get("json"),
                "headers": kwargs.get("headers"),
                "base_url": base_url,
                "timeout": timeout,
            }
        )
        request = httpx.Request(method, f"{base_url}{path}")
        return httpx.Response(200, json={"session_id": "sess-1"}, request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: MockAsyncClient(handler=handler, **kwargs),
    )
    client = MarketClient(config)

    payload = await client.negotiate_session("listing-1", "buyer-9", 2500, "interactive")

    assert payload == {"session_id": "sess-1"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/sessions/negotiate"
    assert captured["json"]["listing_id"] == "listing-1"
    assert captured["headers"] == {"X-API-Key": "api-key"}


@pytest.mark.asyncio
async def test_market_client_keepalive(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        api_key="api-key",
    )
    captured: dict[str, Any] = {}

    def handler(method: str, path: str, kwargs: dict[str, Any], base_url: str, timeout: float) -> httpx.Response:
        captured["method"] = method
        captured["path"] = path
        captured["headers"] = kwargs.get("headers")
        request = httpx.Request(method, f"{base_url}{path}")
        return httpx.Response(204, request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: MockAsyncClient(handler=handler, **kwargs),
    )
    client = MarketClient(config)

    await client.keepalive_session("sess-1")

    assert captured == {
        "method": "POST",
        "path": "/sessions/sess-1/keepalive",
        "headers": {"X-API-Key": "api-key"},
    }


@pytest.mark.asyncio
async def test_market_client_close_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        api_key="api-key",
    )
    captured: dict[str, Any] = {}

    def handler(method: str, path: str, kwargs: dict[str, Any], base_url: str, timeout: float) -> httpx.Response:
        captured["method"] = method
        captured["path"] = path
        request = httpx.Request(method, f"{base_url}{path}")
        return httpx.Response(204, request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: MockAsyncClient(handler=handler, **kwargs),
    )
    client = MarketClient(config)

    await client.close_session("sess-2")

    assert captured["method"] == "POST"
    assert captured["path"] == "/sessions/sess-2/close"


@pytest.mark.asyncio
async def test_market_client_search_listings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        api_key="api-key",
    )
    captured: dict[str, Any] = {}

    def handler(method: str, path: str, kwargs: dict[str, Any], base_url: str, timeout: float) -> httpx.Response:
        captured["method"] = method
        captured["path"] = path
        captured["params"] = kwargs.get("params")
        request = httpx.Request(method, f"{base_url}{path}")
        return httpx.Response(200, json={"listings": [{"id": "listing-1"}]}, request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: MockAsyncClient(handler=handler, **kwargs),
    )
    client = MarketClient(config)

    payload = await client.search_listings("gpu")

    assert payload == [{"id": "listing-1"}]
    assert captured["method"] == "GET"
    assert captured["path"] == "/listings/search"
    assert captured["params"] == {"query": "gpu"}
