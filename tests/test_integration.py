from __future__ import annotations

import asyncio
import base64
import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli

from aim_node.config_loader import generate_default_config, load_adapter_config, load_config
from aim_node.consumer.proxy import LocalProxy
from aim_node.consumer.session_manager import SessionInvokeError, SessionManager
from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.handshake import HandshakeManager
from aim_node.core.relay_crypto import decrypt_frame, encrypt_frame
from aim_node.provider.adapter import AdapterConfig, HttpJsonAdapter
from aim_node.provider.session_handler import ProviderSessionHandler


def _core_config(tmp_path: Path, node_serial: str) -> AIMCoreConfig:
    return AIMCoreConfig(
        keystore_path=tmp_path / f"{node_serial}-keystore.json",
        node_serial=node_serial,
        data_dir=tmp_path / f"{node_serial}-data",
        api_key="test-api-key",
    )


def _proxy_client(proxy: LocalProxy) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=proxy._app),
        base_url="http://testserver",
    )


class StubProxySessionManager:
    def __init__(self, error: SessionInvokeError | None = None) -> None:
        self._market_client = SimpleNamespace(
            search_listings=lambda query: [],
            get_listing=lambda listing_id: {},
        )
        self.error = error
        self.calls: list[tuple[str, bytes]] = []

    async def invoke(self, session_id: str, body: bytes) -> tuple[bytes, dict[str, str]]:
        self.calls.append((session_id, body))
        if self.error is not None:
            raise self.error
        return b"{}", {}


@dataclass
class FakeMarketClient:
    negotiate_payload: dict[str, object]

    def __post_init__(self) -> None:
        self.keepalive_calls: list[str] = []
        self.close_calls: list[str] = []

    async def negotiate_session(self, **_: object) -> dict[str, object]:
        return dict(self.negotiate_payload)

    async def keepalive_session(self, session_id: str) -> None:
        self.keepalive_calls.append(session_id)

    async def close_session(self, session_id: str) -> None:
        self.close_calls.append(session_id)

    async def search_listings(self, query: str) -> list[dict[str, str]]:
        return [{"query": query}]

    async def get_listing(self, listing_id: str) -> dict[str, str]:
        return {"id": listing_id}


class FakeTrustChannel:
    def __init__(self) -> None:
        self.handlers: dict[str, object] = {}
        self.buyer_node_id: str | None = None
        self.buyer_ed25519_pubkey: str | None = None

    def register_handler(self, action: str, handler) -> None:
        self.handlers[action] = handler


_CLOSE = object()


class InMemoryWebSocket:
    def __init__(self, inbound: asyncio.Queue[object], outbound: asyncio.Queue[object]) -> None:
        self._inbound = inbound
        self._outbound = outbound
        self.closed = False

    async def send(self, data: object) -> None:
        await self._outbound.put(data)

    async def recv(self) -> object:
        message = await self._inbound.get()
        if message is _CLOSE:
            raise RuntimeError("websocket closed")
        return message

    async def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        await self._inbound.put(_CLOSE)
        await self._outbound.put(_CLOSE)


class WebSocketPairFactory:
    def __init__(self) -> None:
        buyer_inbound: asyncio.Queue[object] = asyncio.Queue()
        seller_inbound: asyncio.Queue[object] = asyncio.Queue()
        self._endpoints = [
            InMemoryWebSocket(seller_inbound, buyer_inbound),
            InMemoryWebSocket(buyer_inbound, seller_inbound),
        ]

    async def connect(self, url: str) -> InMemoryWebSocket:
        assert url == "ws://relay.test"
        if not self._endpoints:
            raise RuntimeError("no websocket endpoints remaining")
        return self._endpoints.pop(0)


@pytest.mark.asyncio
async def test_full_buyer_seller_relay_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buyer_config = _core_config(tmp_path, "buyer-node")
    seller_config = _core_config(tmp_path, "seller-node")
    buyer_priv, buyer_pub = DeviceCrypto.generate_ed25519_keypair()
    seller_priv, seller_pub = DeviceCrypto.generate_ed25519_keypair()
    recorded: dict[str, object] = {}

    async def invoke_endpoint(request: Request) -> Response:
        recorded["method"] = request.method
        recorded["path"] = request.url.path
        recorded["json"] = await request.json()
        return JSONResponse({"result": "relay-ok", "session": "session-relay"})

    adapter = HttpJsonAdapter(AdapterConfig(endpoint_url="http://seller.test/invoke"))
    adapter._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=Starlette(routes=[Route("/invoke", invoke_endpoint, methods=["POST"])])
        ),
        base_url="http://seller.test",
    )
    trust_channel = FakeTrustChannel()
    provider = ProviderSessionHandler(seller_config, adapter, trust_channel)  # type: ignore[arg-type]
    buyer_handshake = HandshakeManager(buyer_config.node_serial, buyer_priv, buyer_pub)
    seller_handshake = HandshakeManager(seller_config.node_serial, seller_priv, seller_pub)
    buyer_market = FakeMarketClient(
        {
            "session_id": "session-relay",
            "connection_mode": "relay",
            "relay_url": "ws://relay.test",
            "provider_node_id": seller_config.node_serial,
            "provider_ed25519_pubkey": base64.b64encode(seller_pub.public_bytes_raw()).decode("ascii"),
            "expires_at": "2026-04-07T12:00:00Z",
        }
    )
    buyer_manager = SessionManager(buyer_config, buyer_market)  # type: ignore[arg-type]
    proxy = LocalProxy(buyer_config, buyer_manager)
    ws_factory = WebSocketPairFactory()

    monkeypatch.setattr("aim_node.relay.transport.websockets.connect", ws_factory.connect)
    monkeypatch.setattr(buyer_manager, "_build_handshake_manager", lambda: buyer_handshake)
    monkeypatch.setattr(provider, "_build_handshake_manager", lambda: seller_handshake)

    async def fake_heartbeat(self) -> None:
        return None

    monkeypatch.setattr("aim_node.relay.transport.RelayTransport._heartbeat_loop", fake_heartbeat)

    seller_task = asyncio.create_task(
        provider.on_session_negotiate(
            {
                "payload": {
                    "session_id": "session-relay",
                    "connection_mode": "relay",
                    "relay_url": "ws://relay.test",
                    "buyer_node_id": buyer_config.node_serial,
                    "buyer_ed25519_pubkey": base64.b64encode(buyer_pub.public_bytes_raw()).decode("ascii"),
                }
            }
        )
    )
    await asyncio.sleep(0)

    session = await buyer_manager.connect("listing-relay", 500)
    assert session["connection_mode"] == "relay"
    await seller_task

    async with _proxy_client(proxy) as client:
        response = await client.post(
            f"/aim/invoke/{session['session_id']}",
            json={"prompt": "relay", "value": 1},
        )

    assert response.status_code == 200
    assert response.json() == {"result": "relay-ok", "session": "session-relay"}
    assert recorded == {
        "method": "POST",
        "path": "/invoke",
        "json": {"prompt": "relay", "value": 1},
    }

    await buyer_manager.close_session("session-relay")
    await provider.stop()


@pytest.mark.asyncio
async def test_full_buyer_seller_direct_flow(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buyer_config = _core_config(tmp_path, "buyer-node")
    captured: dict[str, object] = {}

    async def seller_endpoint(request: Request) -> Response:
        captured["authorization"] = request.headers.get("authorization")
        captured["content_type"] = request.headers.get("content-type")
        captured["json"] = await request.json()
        return JSONResponse({"result": "direct-ok"})

    seller_app = Starlette(routes=[Route("/invoke", seller_endpoint, methods=["POST"])])
    transport = httpx.ASGITransport(app=seller_app)
    original_async_client = httpx.AsyncClient

    def patched_async_client(*args, **kwargs):
        kwargs.setdefault("transport", transport)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr("aim_node.consumer.session_manager.httpx.AsyncClient", patched_async_client)

    market_client = FakeMarketClient(
        {
            "session_id": "session-direct",
            "connection_mode": "direct",
            "endpoint_url": "http://seller.test/invoke",
            "session_token": "jwt-token",
            "expires_at": "2026-04-07T12:00:00Z",
        }
    )
    manager = SessionManager(buyer_config, market_client)  # type: ignore[arg-type]
    proxy = LocalProxy(buyer_config, manager)

    session = await manager.connect("listing-direct", 700)
    assert session["connection_mode"] == "direct"

    async with _proxy_client(proxy) as client:
        response = await client.post(
            f"/aim/invoke/{session['session_id']}",
            json={"prompt": "direct"},
        )

    assert response.status_code == 200
    assert response.json() == {"result": "direct-ok"}
    assert captured == {
        "authorization": "Bearer jwt-token",
        "content_type": "application/json",
        "json": {"prompt": "direct"},
    }

    await manager.close_session("session-direct")


def test_handshake_produces_matching_keys() -> None:
    buyer_priv, buyer_pub = DeviceCrypto.generate_ed25519_keypair()
    seller_priv, seller_pub = DeviceCrypto.generate_ed25519_keypair()
    buyer = HandshakeManager("buyer-node", buyer_priv, buyer_pub)
    seller = HandshakeManager("seller-node", seller_priv, seller_pub)

    init = buyer.create_init("session-keys")
    seller.verify_init(init, "session-keys", "buyer-node", buyer_pub)
    accept = seller.create_accept("session-keys", init.ephemeral_pubkey)
    buyer_result = buyer.verify_accept(accept, seller_pub)
    seller_keys = seller._compute_shared_secret_and_keys(
        base64.b64decode(init.ephemeral_pubkey, validate=True),
        "session-keys",
    )

    assert buyer_result.traffic_keys == seller_keys
    assert buyer_result.traffic_keys.buyer_to_seller_key != buyer_result.traffic_keys.seller_to_buyer_key


def test_encrypted_frame_roundtrip_through_relay() -> None:
    buyer_priv, buyer_pub = DeviceCrypto.generate_ed25519_keypair()
    seller_priv, seller_pub = DeviceCrypto.generate_ed25519_keypair()
    buyer = HandshakeManager("buyer-node", buyer_priv, buyer_pub)
    seller = HandshakeManager("seller-node", seller_priv, seller_pub)

    init = buyer.create_init("session-crypto")
    seller.verify_init(init, "session-crypto", "buyer-node", buyer_pub)
    accept = seller.create_accept("session-crypto", init.ephemeral_pubkey)
    buyer_keys = buyer.verify_accept(accept, seller_pub).traffic_keys

    plaintext = b'{"prompt":"roundtrip"}'
    outbound_frame = encrypt_frame(
        buyer_keys.buyer_to_seller_key,
        buyer_keys.buyer_to_seller_nonce_prefix,
        0,
        0x10,
        plaintext,
    )
    frame_type, sequence_number, decrypted = decrypt_frame(
        buyer_keys.buyer_to_seller_key,
        buyer_keys.buyer_to_seller_nonce_prefix,
        outbound_frame,
    )

    assert frame_type == 0x10
    assert sequence_number == 0
    assert decrypted == plaintext
    assert buyer_keys.buyer_to_seller_key != buyer_keys.seller_to_buyer_key


@pytest.mark.asyncio
async def test_session_keepalive_fires(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    buyer_config = _core_config(tmp_path, "buyer-node")
    market_client = FakeMarketClient(
        {
            "session_id": "session-keepalive",
            "connection_mode": "direct",
            "endpoint_url": "http://seller.test/invoke",
            "session_token": "jwt-token",
            "expires_at": "2026-04-07T12:00:00Z",
        }
    )
    manager = SessionManager(buyer_config, market_client)  # type: ignore[arg-type]
    monkeypatch.setattr("aim_node.consumer.session_manager.KEEPALIVE_INTERVAL_S", 0.01)

    await manager.connect("listing-keepalive", 100)
    await asyncio.sleep(0.03)

    assert market_client.keepalive_calls == ["session-keepalive", "session-keepalive"]
    await manager.close_session("session-keepalive")


@pytest.mark.asyncio
async def test_adapter_transform_pipeline() -> None:
    captured: dict[str, object] = {}

    async def invoke_endpoint(request: Request) -> Response:
        captured["json"] = await request.json()
        return JSONResponse({"result": "ok", "meta": "ignored"})

    adapter = HttpJsonAdapter(
        AdapterConfig(
            endpoint_url="http://seller.test/invoke",
            input_path="$.data",
            wrap_key="input",
            output_path="$.result",
        )
    )
    adapter._client = httpx.AsyncClient(
        transport=httpx.ASGITransport(
            app=Starlette(routes=[Route("/invoke", invoke_endpoint, methods=["POST"])])
        ),
        base_url="http://seller.test",
    )

    body, _ = await adapter.forward_request(b'{"data":{"value":42}}')

    assert captured["json"] == {"input": {"value": 42}}
    assert json.loads(body) == "ok"
    await adapter.stop()


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
    ],
)
async def test_error_code_to_http_status_mapping(
    tmp_path: Path, code: int, status_code: int
) -> None:
    proxy = LocalProxy(
        _core_config(tmp_path, f"buyer-node-{code}"),
        StubProxySessionManager(SessionInvokeError(code, "boom")),  # type: ignore[arg-type]
    )

    async with _proxy_client(proxy) as client:
        response = await client.post("/aim/invoke/session-1", json={"prompt": "x"})

    assert response.status_code == status_code
    assert response.json()["code"] == code


@pytest.mark.asyncio
async def test_oversized_body_rejected_at_proxy(tmp_path: Path) -> None:
    session_manager = StubProxySessionManager()
    proxy = LocalProxy(_core_config(tmp_path, "buyer-node"), session_manager)  # type: ignore[arg-type]
    payload = {"data": "x" * (33 * 1024)}

    async with _proxy_client(proxy) as client:
        response = await client.post("/aim/invoke/session-1", json=payload)

    assert response.status_code == 413
    assert session_manager.calls == []


@pytest.mark.asyncio
async def test_health_check_degradation_and_recovery() -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["count"] += 1
        if attempts["count"] <= 3:
            return httpx.Response(503, request=request)
        return httpx.Response(200, request=request)

    adapter = HttpJsonAdapter(
        AdapterConfig(
            endpoint_url="http://seller.test/invoke",
            health_check_url="http://seller.test/health",
        )
    )
    adapter._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    assert await adapter.health_check() is False
    assert adapter._healthy is True
    assert await adapter.health_check() is False
    assert adapter._healthy is True
    assert await adapter.health_check() is False
    assert adapter._healthy is False
    assert await adapter.health_check() is True
    assert adapter._healthy is True
    await adapter.stop()


def test_config_loader_roundtrip(tmp_path: Path) -> None:
    config_path = tmp_path / "aim-node.toml"
    config_path.write_text(
        generate_default_config().replace("__NODE_SERIAL__", "node-roundtrip"),
        encoding="utf-8",
    )

    with config_path.open("rb") as handle:
        raw = tomli.load(handle)

    core_config = load_config(raw)
    adapter_config = load_adapter_config(raw)

    assert core_config.node_serial == "node-roundtrip"
    assert core_config.keystore_path == Path(".aim-node/keystore.json")
    assert core_config.data_dir == Path(".aim-node")
    assert core_config.market_api_url == "https://api.ai.market"
    assert core_config.market_ws_url == "wss://api.ai.market/ws"
    assert core_config.reconnect_delay_s == 5.0
    assert core_config.reconnect_max_delay_s == 60.0
    assert core_config.reconnect_jitter == 0.3
    assert core_config.api_key == ""

    assert adapter_config == AdapterConfig(
        endpoint_url="http://127.0.0.1:8000/invoke",
        health_check_url="http://127.0.0.1:8000/health",
        timeout_seconds=30,
        max_concurrent=10,
        max_body_bytes=32768,
        input_path="$",
        wrap_key="input",
        output_path="$",
    )
