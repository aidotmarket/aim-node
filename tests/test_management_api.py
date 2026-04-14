"""Tests for the management HTTP API (Slice 2)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from aim_node.core.crypto import DeviceCrypto
from aim_node.management.app import create_management_app
from aim_node.management.config_writer import write_config
from aim_node.management.process import ProcessManager
from aim_node.management.state import NodeState, ProcessStateStore, SessionSnapshot


# ---------- Fixtures & helpers ----------


@pytest.fixture(autouse=True)
def _reset_state():
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)
    yield
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)


def _create_keystore(data_dir: Path, passphrase: str) -> None:
    keystore_path = data_dir / "keystore.json"
    config = type(
        "C",
        (),
        {"keystore_path": keystore_path, "data_dir": data_dir},
    )()
    DeviceCrypto(config, passphrase=passphrase).get_or_create_keypairs()


def _write_runtime_config(
    data_dir: Path,
    *,
    mode: str = "consumer",
    upstream_url: str = "http://127.0.0.1:9000/invoke",
    api_url: str = "https://api.example.test",
    api_key: str = "api-key",
) -> None:
    config = {
        "core": {
            "node_serial": "node-test-123",
            "keystore_path": str(data_dir / "keystore.json"),
            "data_dir": str(data_dir),
            "market_api_url": api_url,
            "api_key": api_key,
        },
        "management": {
            "setup_complete": True,
            "setup_step": 5,
            "mode": mode,
        },
    }
    if mode in ("provider", "both"):
        config["provider"] = {"adapter": {"endpoint_url": upstream_url}}
    write_config(data_dir, config)


def _build_app(data_dir: Path):
    """Create app and manually bootstrap lifespan state (httpx ASGI transport
    does not invoke lifespan)."""
    app = create_management_app(data_dir)
    state = ProcessStateStore(data_dir)
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    return app, state, process_mgr


def _make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost"},
    )


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def fresh_app(tmp_data_dir: Path):
    app, state, pm = _build_app(tmp_data_dir)
    return app, state, pm


@pytest.fixture
def setup_complete_app(tmp_data_dir: Path):
    _write_runtime_config(tmp_data_dir, mode="consumer")
    _create_keystore(tmp_data_dir, passphrase="")
    app, state, pm = _build_app(tmp_data_dir)
    assert state.node_state == NodeState.READY
    return app, state, pm


@pytest.fixture
def setup_complete_provider_app(tmp_data_dir: Path):
    _write_runtime_config(tmp_data_dir, mode="provider")
    _create_keystore(tmp_data_dir, passphrase="")
    app, state, pm = _build_app(tmp_data_dir)
    assert state.node_state == NodeState.READY
    return app, state, pm


@pytest.fixture
def locked_app(tmp_data_dir: Path):
    _write_runtime_config(tmp_data_dir, mode="provider")
    _create_keystore(tmp_data_dir, passphrase="test123")
    app, state, pm = _build_app(tmp_data_dir)
    assert state.node_state == NodeState.LOCKED
    return app, state, pm


class _FakeAsyncClient:
    def __init__(self, status_code=200, json_data=None, raise_exc=None):
        self.status_code = status_code
        self._json = json_data or {}
        self._raise_exc = raise_exc

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, *args, **kwargs):
        if self._raise_exc:
            raise self._raise_exc
        resp = MagicMock()
        resp.status_code = self.status_code
        resp.json = MagicMock(return_value=self._json)
        return resp


def _patch_httpx(monkeypatch, *, status_code=200, json_data=None, raise_exc=None):
    def _factory(*args, **kwargs):
        return _FakeAsyncClient(
            status_code=status_code, json_data=json_data, raise_exc=raise_exc
        )

    monkeypatch.setattr("aim_node.management.routes._AsyncClient", _factory)


# ---------- Tests ----------


# 1
async def test_health_returns_200(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/health")
    assert r.status_code == 200
    body = r.json()
    assert body["healthy"] is True


# 2
async def test_health_shows_setup_incomplete(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/health")
    body = r.json()
    assert body["setup_complete"] is False
    assert body["locked"] is False


# 3
async def test_setup_status_initial(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/setup/status")
    assert r.status_code == 200
    body = r.json()
    assert body["setup_complete"] is False
    assert body["current_step"] == 0


# 4
async def test_setup_status_after_finalize(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/setup/status")
    body = r.json()
    assert body["setup_complete"] is True
    assert body["current_step"] == 5


# 5
async def test_setup_keypair_creates_keystore(fresh_app, tmp_data_dir):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/setup/keypair", json={"passphrase": ""})
    assert r.status_code == 200
    body = r.json()
    assert body["created"] is True
    assert len(body["fingerprint"]) == 64
    assert (tmp_data_dir / "keystore.json").exists()


# 6
async def test_setup_keypair_duplicate_409(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/setup/keypair", json={"passphrase": ""})
    assert r.status_code == 409
    body = r.json()
    assert body["code"] == "already_exists"
    assert body["message"] == "Keypair already exists"
    assert body["request_id"].startswith("req_")


# 7
async def test_setup_test_connection_success(fresh_app, monkeypatch):
    app, *_ = fresh_app
    _patch_httpx(monkeypatch, status_code=200, json_data={"version": "1.2.3"})
    async with _make_client(app) as client:
        r = await client.post(
            "/api/mgmt/setup/test-connection",
            json={"api_url": "https://api.example.test", "api_key": "key"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["reachable"] is True
    assert body["version"] == "1.2.3"


# 8
async def test_setup_test_connection_unreachable(fresh_app, monkeypatch):
    app, *_ = fresh_app
    _patch_httpx(monkeypatch, raise_exc=Exception("boom"))
    async with _make_client(app) as client:
        r = await client.post(
            "/api/mgmt/setup/test-connection",
            json={"api_url": "https://api.example.test", "api_key": "key"},
        )
    assert r.status_code == 200
    assert r.json()["reachable"] is False


# 9
async def test_setup_finalize_success(fresh_app, tmp_data_dir):
    app, state, _ = fresh_app
    async with _make_client(app) as client:
        r = await client.post(
            "/api/mgmt/setup/finalize",
            json={
                "mode": "consumer",
                "api_url": "https://api.example.test",
                "api_key": "key",
            },
        )
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert state.get_status()["setup_complete"] is True


# 10
async def test_setup_finalize_provider_requires_upstream(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.post(
            "/api/mgmt/setup/finalize",
            json={
                "mode": "provider",
                "api_url": "https://api.example.test",
                "api_key": "key",
            },
        )
    assert r.status_code == 422


# 11
async def test_setup_finalize_invalid_url_scheme(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.post(
            "/api/mgmt/setup/finalize",
            json={
                "mode": "consumer",
                "api_url": "ftp://api.example.test",
                "api_key": "key",
            },
        )
    assert r.status_code == 422


# 12
async def test_dashboard_after_setup(setup_complete_app, monkeypatch):
    app, *_ = setup_complete_app
    _patch_httpx(monkeypatch, status_code=200)
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/status")
    assert r.status_code == 200
    body = r.json()
    assert body["node_id"] == "node-test-123"
    assert body["market_connected"] is True
    assert body["provider_running"] is False


# 13
async def test_dashboard_before_setup_returns_defaults(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/status")
    assert r.status_code == 200
    body = r.json()
    assert body["node_id"] == ""
    assert body["market_connected"] is False


# 14
async def test_config_read_masks_api_key(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/config")
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_set"] is True
    assert "api_key" not in body
    assert body["mode"] == "consumer"


# 15
async def test_config_read_before_setup(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/config")
    assert r.status_code == 200
    body = r.json()
    assert body["api_key_set"] is False
    assert body["mode"] == ""


# 16
async def test_config_update_mode_change(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.put(
            "/api/mgmt/config",
            json={
                "mode": "both",
                "upstream_url": "http://127.0.0.1:9000/invoke",
            },
        )
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["restart_required"] is True


# 17
async def test_config_update_invalid_mode_422(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.put("/api/mgmt/config", json={"mode": "nonsense"})
    assert r.status_code == 422


# 18
async def test_config_update_provider_requires_upstream(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.put("/api/mgmt/config", json={"mode": "provider"})
    assert r.status_code == 422


# 19
async def test_provider_start_success(setup_complete_provider_app):
    app, *_ = setup_complete_provider_app

    trust_channel = MagicMock()
    trust_channel.run = AsyncMock(side_effect=asyncio.CancelledError())
    adapter = MagicMock()
    handler = MagicMock()
    handler.start = AsyncMock()
    handler.stop = AsyncMock()

    with (
        patch("aim_node.management.process.TrustChannelClient", return_value=trust_channel),
        patch("aim_node.management.process.HttpJsonAdapter", return_value=adapter),
        patch("aim_node.management.process.ProviderSessionHandler", return_value=handler),
    ):
        async with _make_client(app) as client:
            r = await client.post("/api/mgmt/provider/start")
    assert r.status_code == 200
    assert r.json()["started"] is True


# 20
async def test_provider_start_when_locked_423(locked_app):
    app, *_ = locked_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/provider/start")
    assert r.status_code == 423
    body = r.json()
    assert body["code"] == "node_locked"
    assert body["request_id"].startswith("req_")


# 21
async def test_provider_start_when_setup_incomplete_412(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/provider/start")
    assert r.status_code == 412
    body = r.json()
    assert body["code"] == "setup_incomplete"
    assert body["request_id"].startswith("req_")


# 22
async def test_provider_stop_success(setup_complete_provider_app):
    app, state, _ = setup_complete_provider_app

    trust_channel = MagicMock()
    trust_channel.run = AsyncMock(side_effect=asyncio.CancelledError())
    adapter = MagicMock()
    handler = MagicMock()
    handler.start = AsyncMock()
    handler.stop = AsyncMock()

    with (
        patch("aim_node.management.process.TrustChannelClient", return_value=trust_channel),
        patch("aim_node.management.process.HttpJsonAdapter", return_value=adapter),
        patch("aim_node.management.process.ProviderSessionHandler", return_value=handler),
    ):
        async with _make_client(app) as client:
            r1 = await client.post("/api/mgmt/provider/start")
            assert r1.status_code == 200
            r2 = await client.post("/api/mgmt/provider/stop")
    assert r2.status_code == 200
    assert r2.json()["stopped"] is True


# 23
async def test_provider_stop_not_running_409(setup_complete_provider_app):
    app, *_ = setup_complete_provider_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/provider/stop")
    assert r.status_code == 409


# 24a
async def test_provider_restart_cycles_and_returns_dashboard(setup_complete_provider_app):
    app, state, _ = setup_complete_provider_app

    async with _make_client(app) as client:
        with (
            patch.object(app.state.process_mgr, "stop_provider", new=AsyncMock()) as stop_provider,
            patch.object(app.state.process_mgr, "start_provider", new=AsyncMock()) as start_provider,
        ):
            r = await client.post("/api/mgmt/provider/restart")

    assert r.status_code == 200
    assert r.json()["status"] == "restarted"
    assert r.json()["dashboard"]["provider_running"] == state.get_dashboard()["provider_running"]
    stop_provider.assert_awaited_once()
    start_provider.assert_awaited_once()


# 24b
async def test_provider_reload_reloads_config_and_restarts_running_provider(setup_complete_provider_app):
    app, state, _ = setup_complete_provider_app
    state.provider.running = True

    updated_config = {
        "core": {
            "node_serial": "node-test-123",
            "node_id": "node-backend-123",
            "keystore_path": str(state._data_dir / "keystore.json"),
            "data_dir": str(state._data_dir),
            "market_api_url": "https://api.changed.test",
            "api_key": "changed-key",
        },
        "management": {
            "setup_complete": True,
            "setup_step": 5,
            "mode": "provider",
        },
        "provider": {"adapter": {"endpoint_url": "http://127.0.0.1:9100/invoke"}},
    }
    write_config(state._data_dir, updated_config)

    facade = MagicMock()
    with patch("aim_node.management.facade.MarketplaceFacade.create", return_value=facade) as create_facade:
        async with _make_client(app) as client:
            with (
                patch.object(app.state.process_mgr, "stop_provider", new=AsyncMock()) as stop_provider,
                patch.object(app.state.process_mgr, "start_provider", new=AsyncMock()) as start_provider,
            ):
                r = await client.post("/api/mgmt/provider/reload")

    assert r.status_code == 200
    assert r.json()["status"] == "reloaded"
    assert app.state.facade is facade
    assert state.get_status()["setup_complete"] is True
    create_facade.assert_called_once()
    stop_provider.assert_awaited_once()
    start_provider.assert_awaited_once()


# 24c
async def test_provider_reload_bad_config_clears_facade(setup_complete_provider_app):
    app, state, _ = setup_complete_provider_app
    app.state.facade = object()
    state.provider.running = False
    write_config(
        state._data_dir,
        {
            "core": {
                "node_serial": "node-test-123",
                "keystore_path": str(state._data_dir / "keystore.json"),
                "data_dir": str(state._data_dir),
                "market_api_url": "https://api.changed.test",
                "api_key": "changed-key",
            },
            "management": {
                "setup_complete": True,
                "setup_step": 5,
                "mode": "provider",
            },
            "provider": {"adapter": {"endpoint_url": "http://127.0.0.1:9100/invoke"}},
        },
    )

    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/provider/reload")

    assert r.status_code == 200
    assert r.json()["status"] == "reloaded"
    assert app.state.facade is None


# 24
async def test_provider_health(setup_complete_provider_app, monkeypatch):
    app, *_ = setup_complete_provider_app
    _patch_httpx(monkeypatch, status_code=200)
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/provider/health")
    assert r.status_code == 200
    body = r.json()
    assert body["upstream_reachable"] is True
    assert "last_check" in body


# 25
async def test_consumer_start_success(setup_complete_app):
    app, *_ = setup_complete_app

    fake_market_client = object()
    fake_proxy = MagicMock()
    fake_proxy._port = 8400
    fake_proxy.start = AsyncMock()
    fake_proxy.stop = AsyncMock()
    fake_session_manager = MagicMock()

    with (
        patch("aim_node.management.process.MarketClient", return_value=fake_market_client),
        patch("aim_node.management.process.SessionManager", return_value=fake_session_manager),
        patch("aim_node.management.process.LocalProxy", return_value=fake_proxy),
    ):
        async with _make_client(app) as client:
            r = await client.post("/api/mgmt/consumer/start")
    assert r.status_code == 200
    body = r.json()
    assert body["started"] is True
    assert body["proxy_port"] == 8400


# 26
async def test_consumer_start_when_locked_423(locked_app):
    app, *_ = locked_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/consumer/start")
    assert r.status_code == 423


# 27
async def test_consumer_stop_success(setup_complete_app):
    app, *_ = setup_complete_app

    fake_market_client = object()
    fake_proxy = MagicMock()
    fake_proxy._port = 8400
    fake_proxy.start = AsyncMock()
    fake_proxy.stop = AsyncMock()
    fake_session_manager = MagicMock()

    with (
        patch("aim_node.management.process.MarketClient", return_value=fake_market_client),
        patch("aim_node.management.process.SessionManager", return_value=fake_session_manager),
        patch("aim_node.management.process.LocalProxy", return_value=fake_proxy),
    ):
        async with _make_client(app) as client:
            r1 = await client.post("/api/mgmt/consumer/start")
            assert r1.status_code == 200
            r2 = await client.post("/api/mgmt/consumer/stop")
    assert r2.status_code == 200
    assert r2.json()["stopped"] is True


# 28
async def test_consumer_stop_not_running_409(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/consumer/stop")
    assert r.status_code == 409


# 28a
async def test_lock_node_stops_provider_consumer_and_clears_passphrase(tmp_data_dir: Path):
    _write_runtime_config(tmp_data_dir, mode="both")
    _create_keystore(tmp_data_dir, passphrase="test123")
    app, state, _ = _build_app(tmp_data_dir)
    assert state.unlock("test123") is True
    state.provider.running = True
    state.consumer.running = True
    os.environ["AIM_KEYSTORE_PASSPHRASE"] = "test123"

    async with _make_client(app) as client:
        with (
            patch.object(app.state.process_mgr, "stop_provider", new=AsyncMock()) as stop_provider,
            patch.object(app.state.process_mgr, "stop_consumer", new=AsyncMock()) as stop_consumer,
        ):
            r = await client.post("/api/mgmt/lock")

    assert r.status_code == 200
    assert r.json()["status"] == "locked"
    assert os.environ.get("AIM_KEYSTORE_PASSPHRASE") is None
    assert state.get_passphrase() is None
    assert state.node_state == NodeState.LOCKED
    assert state.get_status()["locked"] is True
    stop_provider.assert_awaited_once()
    stop_consumer.assert_awaited_once()

    async with _make_client(app) as client:
        unlocked = await client.post("/api/mgmt/unlock", json={"passphrase": "test123"})
    assert unlocked.status_code == 200
    assert unlocked.json()["unlocked"] is True


# 29
async def test_sessions_empty_list(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/sessions")
    assert r.status_code == 200
    assert r.json()["sessions"] == []


# 30
async def test_session_detail_not_found_404(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/sessions/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert body["message"] == "Session not found"
    assert body["request_id"].startswith("req_")


# 30a
async def test_session_kill_closes_consumer_session_and_removes_snapshot(setup_complete_app):
    app, state, pm = setup_complete_app
    state.add_session(
        SessionSnapshot(
            session_id="consumer-1",
            role="consumer",
            state="active",
            created_at=1234567890.0,
        )
    )
    pm._consumer_session_mgr = MagicMock()
    pm._consumer_session_mgr.close_session = AsyncMock()

    async with _make_client(app) as client:
        r = await client.delete("/api/mgmt/sessions/consumer-1")

    assert r.status_code == 200
    assert r.json() == {"status": "killed", "session_id": "consumer-1"}
    pm._consumer_session_mgr.close_session.assert_awaited_once_with("consumer-1")
    assert state.get_session("consumer-1") is None


# 30b
async def test_session_kill_closes_provider_session_and_removes_snapshot(setup_complete_provider_app):
    app, state, pm = setup_complete_provider_app
    state.add_session(
        SessionSnapshot(
            session_id="provider-1",
            role="provider",
            state="active",
            created_at=1234567890.0,
        )
    )

    task = asyncio.create_task(asyncio.sleep(60))
    transport = MagicMock()
    transport.close = AsyncMock()
    pm._provider_handler = type(
        "ProviderHandlerStub",
        (),
        {
            "_session_tasks": {"provider-1": task},
            "_active_sessions": {"provider-1": transport},
        },
    )()

    try:
        async with _make_client(app) as client:
            r = await client.delete("/api/mgmt/sessions/provider-1")
    finally:
        if not task.done():
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    assert r.status_code == 200
    transport.close.assert_awaited_once_with(reason="admin_kill")
    assert state.get_session("provider-1") is None


# 30c
async def test_session_kill_missing_session_404(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.delete("/api/mgmt/sessions/missing-session")
    assert r.status_code == 404
    body = r.json()
    assert body["code"] == "not_found"
    assert body["message"] == "Session missing-session not found"


# 31
async def test_unlock_success(locked_app):
    app, *_ = locked_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/unlock", json={"passphrase": "test123"})
    assert r.status_code == 200
    assert r.json()["unlocked"] is True


# 32
async def test_unlock_wrong_passphrase_401(locked_app):
    app, *_ = locked_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/unlock", json={"passphrase": "wrong"})
    assert r.status_code == 401
    body = r.json()
    assert body["code"] == "auth_failed"
    assert body["message"] == "Invalid passphrase"
    assert body["request_id"].startswith("req_")


# 33
async def test_keypair_info_success(setup_complete_app):
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/keypair")
    assert r.status_code == 200
    body = r.json()
    assert len(body["fingerprint"]) == 64
    assert body["algorithm"] == "Ed25519"
    assert "created_at" in body


# 34
async def test_keypair_info_no_keystore_404(fresh_app):
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/keypair")
    assert r.status_code == 404


# 34a
async def test_keypair_rotate_backs_up_keystore_and_posts_public_key(setup_complete_app):
    app, state, _ = setup_complete_app
    app.state.facade = MagicMock()
    app.state.facade.post = AsyncMock()

    before = (state._data_dir / "keystore.json").read_bytes()

    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/keypair/rotate")

    after = (state._data_dir / "keystore.json").read_bytes()
    backup = (state._data_dir / "keystore.json.bak").read_bytes()

    assert r.status_code == 200
    assert r.json()["status"] == "rotated"
    assert before == backup
    assert after != before
    app.state.facade.post.assert_awaited_once()
    assert app.state.facade.post.await_args.args == ("/aim/nodes/keypair",)
    assert "public_key" in app.state.facade.post.await_args.kwargs["json_body"]


# 35
async def test_session_detail_happy_path(setup_complete_app):
    """GET /sessions/{id} returns 200 with valid session data when session exists."""
    app, state, _ = setup_complete_app
    snapshot = SessionSnapshot(
        session_id="test-123",
        role="provider",
        state="active",
        created_at=1234567890.0,
    )
    state.add_session(snapshot)
    async with _make_client(app) as client:
        r = await client.get("/api/mgmt/sessions/test-123")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "test-123"
    assert body["role"] == "provider"
    assert body["state"] == "active"


# 36
async def test_consumer_start_when_setup_incomplete_412(fresh_app):
    """POST /consumer/start returns 412 when setup is not complete."""
    app, *_ = fresh_app
    async with _make_client(app) as client:
        r = await client.post("/api/mgmt/consumer/start")
    assert r.status_code == 412


# 37
async def test_config_read_after_mode_change(setup_complete_app):
    """GET /config reflects mode change after PUT /config."""
    app, *_ = setup_complete_app
    async with _make_client(app) as client:
        await client.put("/api/mgmt/config", json={"mode": "consumer"})
        r2 = await client.get("/api/mgmt/config")
    assert r2.status_code == 200
    body = r2.json()
    assert body["mode"] == "consumer"
