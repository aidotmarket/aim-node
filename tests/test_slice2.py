from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from typing import Any

import httpx
import pytest
from cryptography.hazmat.primitives import serialization

from aim_node.core.auth import AuthService
from aim_node.core.config import AIMCoreConfig
from aim_node.core.connectivity_token import ConnectivityTokenService
from aim_node.core.crypto import DeviceCrypto
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


@pytest.mark.asyncio
async def test_market_client_register_challenge_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        api_key="api-key",
    )
    captured: dict[str, Any] = {}
    _, public_key = DeviceCrypto.generate_ed25519_keypair()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )

    def handler(method: str, path: str, kwargs: dict[str, Any], base_url: str, timeout: float) -> httpx.Response:
        captured["method"] = method
        captured["path"] = path
        captured["json"] = kwargs.get("json")
        request = httpx.Request(method, f"{base_url}{path}")
        return httpx.Response(200, json={"challenge": "challenge-123"}, request=request)

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: MockAsyncClient(handler=handler, **kwargs),
    )
    client = MarketClient(config)

    payload = await client.register_challenge(
        public_key=public_key_bytes,
        endpoint_url="https://example.test/mcp",
        mode="seller",
    )

    assert payload == {"challenge": "challenge-123"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/api/v1/aim/nodes/register/challenge"
    assert captured["json"] == {
        "endpoint_url": "https://example.test/mcp",
        "public_key": base64.b64encode(public_key_bytes).decode("ascii"),
        "mode": "seller",
    }


@pytest.mark.asyncio
async def test_market_client_register_node_two_step_payloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config = AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-42",
        api_key="api-key",
    )
    calls: list[dict[str, Any]] = []
    private_key, public_key = DeviceCrypto.generate_ed25519_keypair()
    public_key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    expected_public_key = base64.b64encode(public_key_bytes).decode("ascii")
    challenge = "challenge-xyz"

    def handler(method: str, path: str, kwargs: dict[str, Any], base_url: str, timeout: float) -> httpx.Response:
        calls.append(
            {
                "method": method,
                "path": path,
                "json": kwargs.get("json"),
            }
        )
        request = httpx.Request(method, f"{base_url}{path}")
        if path == "/api/v1/aim/nodes/register/challenge":
            return httpx.Response(200, json={"challenge": challenge}, request=request)
        if path == "/api/v1/aim/nodes/register":
            return httpx.Response(201, json={"node_id": "node-backend-123"}, request=request)
        raise AssertionError(f"unexpected path: {path}")

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kwargs: MockAsyncClient(handler=handler, **kwargs),
    )
    client = MarketClient(config)

    payload = await client.register_node(
        public_key=public_key_bytes,
        endpoint_url="https://example.test/mcp",
        mode="seller",
        private_key=private_key,
    )

    assert payload == {"node_id": "node-backend-123"}
    assert calls[0] == {
        "method": "POST",
        "path": "/api/v1/aim/nodes/register/challenge",
        "json": {
            "endpoint_url": "https://example.test/mcp",
            "public_key": expected_public_key,
            "mode": "seller",
        },
    }
    expected_signature = base64.urlsafe_b64encode(
        DeviceCrypto.sign(private_key, challenge.encode("utf-8"))
    ).decode("ascii")
    assert calls[1] == {
        "method": "POST",
        "path": "/api/v1/aim/nodes/register",
        "json": {
            "endpoint_url": "https://example.test/mcp",
            "public_key": expected_public_key,
            "mode": "seller",
            "challenge": challenge,
            "pop_signature": expected_signature,
        },
    }
