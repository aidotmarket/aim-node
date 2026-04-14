from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from aim_node.core.crypto import DeviceCrypto
from aim_node.management.app import create_management_app
from aim_node.management.config_writer import write_config
from aim_node.management.process import ProcessManager
from aim_node.management.state import ProcessStateStore, read_store, write_store
from aim_node.management.tools import TOOLS_STORE_KEY


@pytest.fixture(autouse=True)
def _reset_state():
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)
    yield
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)


def _create_keystore(data_dir: Path, passphrase: str = "") -> None:
    config = type(
        "C",
        (),
        {"keystore_path": data_dir / "keystore.json", "data_dir": data_dir},
    )()
    DeviceCrypto(config, passphrase=passphrase).get_or_create_keypairs()


def _write_runtime_config(
    data_dir: Path,
    *,
    mode: str = "provider",
    upstream_url: str = "http://127.0.0.1:9000/mcp",
) -> None:
    config = {
        "core": {
            "node_serial": "node-tools-test",
            "keystore_path": str(data_dir / "keystore.json"),
            "data_dir": str(data_dir),
            "market_api_url": "https://api.example.test",
            "api_key": "api-key",
        },
        "management": {
            "setup_complete": True,
            "setup_step": 5,
            "mode": mode,
        },
        "provider": {"adapter": {"endpoint_url": upstream_url}},
    }
    write_config(data_dir, config)


def _build_app(data_dir: Path):
    app = create_management_app(data_dir)
    state = ProcessStateStore(data_dir)
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    return app


def _make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost"},
    )


class _FakeResponse:
    def __init__(self, status_code: int = 200, json_data=None):
        self.status_code = status_code
        self._json_data = json_data if json_data is not None else {}
        self.request = httpx.Request("GET", "http://testserver")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "error",
                request=self.request,
                response=httpx.Response(self.status_code, request=self.request),
            )

    def json(self):
        return self._json_data


class _FakeAsyncClient:
    next_get = []
    next_post = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        item = self.next_get.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    async def post(self, *args, **kwargs):
        item = self.next_post.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def _patch_httpx(monkeypatch, *, gets=None, posts=None):
    _FakeAsyncClient.next_get = list(gets or [])
    _FakeAsyncClient.next_post = list(posts or [])
    monkeypatch.setattr("aim_node.management.tools._AsyncClient", _FakeAsyncClient)


def _tool_payload(name: str = "echo", version: str = "1.0.0"):
    return {
        "tools": [
            {
                "name": name,
                "version": version,
                "description": "Echo tool",
                "input_schema": {
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                    "required": ["ok"],
                },
            }
        ]
    }


@pytest.fixture
def tools_app(tmp_path: Path):
    _write_runtime_config(tmp_path)
    _create_keystore(tmp_path)
    return _build_app(tmp_path), tmp_path


async def test_tools_list_local_empty_cache(tools_app):
    app, _ = tools_app
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/tools")
    assert response.status_code == 200
    assert response.json() == {"tools": [], "scanned_at": None}


async def test_tools_discover_happy_path(tools_app, monkeypatch):
    app, data_dir = tools_app
    _patch_httpx(monkeypatch, gets=[_FakeResponse(json_data=_tool_payload())])
    async with _make_client(app) as client:
        response = await client.post("/api/mgmt/tools/discover")
    assert response.status_code == 200
    body = response.json()
    assert len(body["tools"]) == 1
    cached = read_store(data_dir, TOOLS_STORE_KEY)
    assert cached is not None
    assert cached["tools"][0]["name"] == "echo"


async def test_tools_list_local_returns_cached_tools(tools_app, monkeypatch):
    app, _ = tools_app
    _patch_httpx(monkeypatch, gets=[_FakeResponse(json_data=_tool_payload())])
    async with _make_client(app) as client:
        await client.post("/api/mgmt/tools/discover")
        response = await client.get("/api/mgmt/tools")
    assert response.status_code == 200
    assert response.json()["tools"][0]["validation_status"] == "pending"


async def test_tools_detail_happy_path(tools_app, monkeypatch):
    app, _ = tools_app
    _patch_httpx(monkeypatch, gets=[_FakeResponse(json_data=_tool_payload())])
    async with _make_client(app) as client:
        discover = await client.post("/api/mgmt/tools/discover")
        tool_id = discover.json()["tools"][0]["tool_id"]
        response = await client.get(f"/api/mgmt/tools/{tool_id}")
    assert response.status_code == 200
    assert response.json()["input_schema"]["type"] == "object"


async def test_tools_validate_passes_and_updates_cache(tools_app, monkeypatch):
    app, data_dir = tools_app
    _patch_httpx(
        monkeypatch,
        gets=[_FakeResponse(json_data=_tool_payload())],
        posts=[_FakeResponse(json_data={"result": {"ok": True}})],
    )
    async with _make_client(app) as client:
        discover = await client.post("/api/mgmt/tools/discover")
        tool_id = discover.json()["tools"][0]["tool_id"]
        response = await client.post(f"/api/mgmt/tools/{tool_id}/validate")
    assert response.status_code == 200
    assert response.json()["status"] == "passed"
    cached = read_store(data_dir, TOOLS_STORE_KEY)
    assert cached["tools"][0]["validation_status"] == "passed"
    assert cached["tools"][0]["last_validated_at"] is not None


async def test_setup_test_upstream_happy_path(tools_app, monkeypatch):
    app, _ = tools_app
    _patch_httpx(monkeypatch, gets=[_FakeResponse(json_data=_tool_payload())])
    async with _make_client(app) as client:
        response = await client.post(
            "/api/mgmt/setup/test-upstream",
            json={"url": "http://127.0.0.1:9000/mcp", "timeout_s": 3},
        )
    assert response.status_code == 200
    assert response.json()["reachable"] is True
    assert response.json()["tools_found"] == 1


async def test_setup_test_upstream_counts_multiple_tools(tools_app, monkeypatch):
    app, _ = tools_app
    payload = _tool_payload()
    payload["tools"].append(
        {
            "name": "sum",
            "version": "2.0.0",
            "description": "Sum tool",
            "input_schema": {"type": "object"},
            "output_schema": {"type": "object"},
        }
    )
    _patch_httpx(monkeypatch, gets=[_FakeResponse(json_data=payload)])
    async with _make_client(app) as client:
        response = await client.post(
            "/api/mgmt/setup/test-upstream",
            json={"url": "http://127.0.0.1:9000/mcp"},
        )
    assert response.status_code == 200
    assert response.json()["tools_found"] == 2


async def test_tools_discover_upstream_unreachable_returns_502(tools_app, monkeypatch):
    app, _ = tools_app
    _patch_httpx(monkeypatch, gets=[httpx.ConnectError("boom")])
    async with _make_client(app) as client:
        response = await client.post("/api/mgmt/tools/discover")
    assert response.status_code == 502
    assert response.json()["code"] == "upstream_unreachable"


async def test_tools_discover_upstream_timeout_returns_504(tools_app, monkeypatch):
    app, _ = tools_app
    _patch_httpx(monkeypatch, gets=[httpx.ReadTimeout("slow")])
    async with _make_client(app) as client:
        response = await client.post("/api/mgmt/tools/discover")
    assert response.status_code == 504
    assert response.json()["code"] == "upstream_timeout"


async def test_setup_test_upstream_unreachable_returns_502(tools_app, monkeypatch):
    app, _ = tools_app
    _patch_httpx(monkeypatch, gets=[httpx.ConnectError("boom")])
    async with _make_client(app) as client:
        response = await client.post(
            "/api/mgmt/setup/test-upstream",
            json={"url": "http://127.0.0.1:9000/mcp"},
        )
    assert response.status_code == 502
    assert response.json()["code"] == "upstream_unreachable"


async def test_setup_test_upstream_timeout_returns_504(tools_app, monkeypatch):
    app, _ = tools_app
    _patch_httpx(monkeypatch, gets=[httpx.ReadTimeout("slow")])
    async with _make_client(app) as client:
        response = await client.post(
            "/api/mgmt/setup/test-upstream",
            json={"url": "http://127.0.0.1:9000/mcp"},
        )
    assert response.status_code == 504
    assert response.json()["code"] == "upstream_timeout"


async def test_tools_detail_cache_miss_returns_404(tools_app):
    app, _ = tools_app
    async with _make_client(app) as client:
        response = await client.get("/api/mgmt/tools/missing-tool")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_tools_validate_cache_miss_returns_404(tools_app):
    app, _ = tools_app
    async with _make_client(app) as client:
        response = await client.post("/api/mgmt/tools/missing-tool/validate")
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"


async def test_tools_discover_rescan_overwrites_cache(tools_app, monkeypatch):
    app, data_dir = tools_app
    _patch_httpx(
        monkeypatch,
        gets=[
            _FakeResponse(json_data=_tool_payload(name="first", version="1")),
            _FakeResponse(json_data=_tool_payload(name="second", version="2")),
        ],
    )
    async with _make_client(app) as client:
        await client.post("/api/mgmt/tools/discover")
        await client.post("/api/mgmt/tools/discover")
    cached = read_store(data_dir, TOOLS_STORE_KEY)
    assert len(cached["tools"]) == 1
    assert cached["tools"][0]["name"] == "second"
    assert cached["tools"][0]["validation_status"] == "pending"


async def test_tools_validate_schema_failure_returns_422(tools_app, monkeypatch):
    app, data_dir = tools_app
    _patch_httpx(
        monkeypatch,
        gets=[_FakeResponse(json_data=_tool_payload())],
        posts=[_FakeResponse(json_data={"result": {"ok": "yes"}})],
    )
    async with _make_client(app) as client:
        discover = await client.post("/api/mgmt/tools/discover")
        tool_id = discover.json()["tools"][0]["tool_id"]
        response = await client.post(f"/api/mgmt/tools/{tool_id}/validate")
    assert response.status_code == 422
    assert response.json()["code"] == "tool_validation_failed"
    cached = read_store(data_dir, TOOLS_STORE_KEY)
    assert cached["tools"][0]["validation_status"] == "failed"


async def test_tools_validate_http_failure_returns_422(tools_app, monkeypatch):
    app, data_dir = tools_app
    _patch_httpx(
        monkeypatch,
        gets=[_FakeResponse(json_data=_tool_payload())],
        posts=[_FakeResponse(status_code=500, json_data={"error": "bad"})],
    )
    async with _make_client(app) as client:
        discover = await client.post("/api/mgmt/tools/discover")
        tool_id = discover.json()["tools"][0]["tool_id"]
        response = await client.post(f"/api/mgmt/tools/{tool_id}/validate")
    assert response.status_code == 422
    assert response.json()["code"] == "tool_validation_failed"
    assert read_store(data_dir, TOOLS_STORE_KEY)["tools"][0]["validation_status"] == "failed"


def test_read_write_store_roundtrip(tmp_path: Path):
    write_store(tmp_path, "example", {"ok": True})
    assert read_store(tmp_path, "example") == {"ok": True}
