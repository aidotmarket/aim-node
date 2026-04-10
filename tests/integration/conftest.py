"""Shared fixtures for integration tests."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.management.app import create_management_app
from aim_node.management.config_writer import write_config
from aim_node.management.process import ProcessManager
from aim_node.management.state import NodeState, ProcessStateStore, SessionSnapshot


# ---------------------------------------------------------------------------
# Reset singleton between tests
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_state():
    ProcessStateStore.reset()
    old_passphrase = os.environ.get("AIM_KEYSTORE_PASSPHRASE")
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)
    try:
        yield
    finally:
        ProcessStateStore.reset()
        if old_passphrase is not None:
            os.environ["AIM_KEYSTORE_PASSPHRASE"] = old_passphrase
        else:
            os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def create_keystore(data_dir: Path, passphrase: str = "") -> None:
    keystore_path = data_dir / "keystore.json"
    config = type("C", (), {"keystore_path": keystore_path, "data_dir": data_dir})()
    DeviceCrypto(config, passphrase=passphrase).get_or_create_keypairs()


def write_runtime_config(
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


def build_app(data_dir: Path):
    """Create management app with manually bootstrapped state (ASGI transport
    does not invoke lifespan)."""
    app = create_management_app(data_dir)
    state = ProcessStateStore(data_dir)
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    return app, state, process_mgr


def make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
    )


# ---------------------------------------------------------------------------
# Fake httpx client for route-level HTTP calls (market API probes)
# ---------------------------------------------------------------------------


class FakeAsyncClient:
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


def patch_httpx(monkeypatch, *, status_code=200, json_data=None, raise_exc=None):
    def _factory(*args, **kwargs):
        return FakeAsyncClient(
            status_code=status_code, json_data=json_data, raise_exc=raise_exc,
        )

    monkeypatch.setattr("aim_node.management.routes._AsyncClient", _factory)


# ---------------------------------------------------------------------------
# Core config fixture (no management app)
# ---------------------------------------------------------------------------


@pytest.fixture
def core_config(tmp_path: Path) -> AIMCoreConfig:
    return AIMCoreConfig(
        keystore_path=tmp_path / "keystore.json",
        node_serial="node-integ-123",
        data_dir=tmp_path / "data",
        api_key="test-api-key",
    )


# ---------------------------------------------------------------------------
# Management app fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_data_dir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def fresh_app(tmp_data_dir: Path):
    """App with no setup done."""
    app, state, pm = build_app(tmp_data_dir)
    try:
        yield app, state, pm
    finally:
        pass  # no async cleanup needed for ASGI transport


@pytest.fixture
def setup_consumer_app(tmp_data_dir: Path):
    """Setup-complete app in consumer mode."""
    write_runtime_config(tmp_data_dir, mode="consumer")
    create_keystore(tmp_data_dir, passphrase="")
    app, state, pm = build_app(tmp_data_dir)
    assert state.node_state == NodeState.READY
    try:
        yield app, state, pm
    finally:
        pass


@pytest.fixture
def setup_provider_app(tmp_data_dir: Path):
    """Setup-complete app in provider mode."""
    write_runtime_config(tmp_data_dir, mode="provider")
    create_keystore(tmp_data_dir, passphrase="")
    app, state, pm = build_app(tmp_data_dir)
    assert state.node_state == NodeState.READY
    try:
        yield app, state, pm
    finally:
        pass


@pytest.fixture
def setup_both_app(tmp_data_dir: Path):
    """Setup-complete app in both mode."""
    write_runtime_config(tmp_data_dir, mode="both")
    create_keystore(tmp_data_dir, passphrase="")
    app, state, pm = build_app(tmp_data_dir)
    assert state.node_state == NodeState.READY
    try:
        yield app, state, pm
    finally:
        pass


@pytest.fixture
def locked_app(tmp_data_dir: Path):
    """Setup-complete app with encrypted keystore (locked)."""
    write_runtime_config(tmp_data_dir, mode="provider")
    create_keystore(tmp_data_dir, passphrase="test-pass-123")
    app, state, pm = build_app(tmp_data_dir)
    assert state.node_state == NodeState.LOCKED
    try:
        yield app, state, pm
    finally:
        pass
