from __future__ import annotations

import os
from pathlib import Path

import httpx
import pytest

from aim_node.core.crypto import DeviceCrypto
from aim_node.management.app import create_management_app
from aim_node.management.process import ProcessManager
from aim_node.management.state import ProcessStateStore


@pytest.fixture(autouse=True)
def _reset_state():
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)
    yield
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)


def _create_keystore(data_dir: Path, passphrase: str = "") -> None:
    keystore_path = data_dir / "keystore.json"
    config = type(
        "C",
        (),
        {"keystore_path": keystore_path, "data_dir": data_dir},
    )()
    DeviceCrypto(config, passphrase=passphrase).get_or_create_keypairs()


def _build_app(data_dir: Path, *, remote_bind: bool = False):
    app = create_management_app(data_dir, remote_bind=remote_bind)
    state = ProcessStateStore(data_dir)
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    app.state.remote_bind = remote_bind
    app.state.session_token = None
    return app, process_mgr


def _make_client(app, *, client_host: str = "127.0.0.1") -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(client_host, 12345)),
        base_url="http://testserver",
    )


@pytest.fixture
async def app_with_state(tmp_path: Path):
    _create_keystore(tmp_path)
    app, process_mgr = _build_app(tmp_path)
    try:
        yield app
    finally:
        await process_mgr.shutdown()


@pytest.fixture
async def remote_bind_app(tmp_path: Path):
    _create_keystore(tmp_path)
    app, process_mgr = _build_app(tmp_path, remote_bind=True)
    try:
        yield app
    finally:
        await process_mgr.shutdown()


async def test_csrf_safe_method_passes_without_token(app_with_state):
    async with _make_client(app_with_state) as client:
        response = await client.get("/api/mgmt/health")

    assert response.status_code == 200


async def test_csrf_mutating_loopback_origin_passes(app_with_state):
    async with _make_client(app_with_state) as client:
        response = await client.post(
            "/api/mgmt/setup/keypair",
            json={"passphrase": ""},
            headers={"Origin": "http://localhost:3000"},
        )

    assert response.status_code != 403


async def test_csrf_mutating_valid_token_passes(app_with_state):
    async with _make_client(app_with_state) as client:
        health = await client.get("/api/mgmt/health")
        csrf_token = health.headers["X-CSRF-Token"]
        response = await client.post(
            "/api/mgmt/setup/keypair",
            json={"passphrase": ""},
            headers={"X-CSRF-Token": csrf_token},
        )

    assert response.status_code != 403


async def test_csrf_mutating_missing_both_rejected(app_with_state):
    async with _make_client(app_with_state) as client:
        response = await client.post(
            "/api/mgmt/setup/keypair",
            json={"passphrase": ""},
        )

    assert response.status_code == 403
    assert response.json()["code"] == "csrf_rejected"


async def test_csrf_mutating_wrong_token_rejected(app_with_state):
    async with _make_client(app_with_state) as client:
        response = await client.post(
            "/api/mgmt/setup/keypair",
            json={"passphrase": ""},
            headers={"X-CSRF-Token": "wrong-token"},
        )

    assert response.status_code == 403


async def test_csrf_token_in_response_header(app_with_state):
    async with _make_client(app_with_state) as client:
        response = await client.get("/api/mgmt/health")

    assert response.status_code == 200
    assert response.headers["X-CSRF-Token"]


async def test_remote_bind_valid_session_token_passes(remote_bind_app):
    async with _make_client(remote_bind_app) as loopback_client:
        issued = await loopback_client.get("/api/mgmt/health")
        session_token = issued.json()["session_token"]
    async with _make_client(remote_bind_app, client_host="10.0.0.2") as remote_client:
        response = await remote_client.get(
            "/api/mgmt/health",
            headers={"X-Session-Token": session_token},
        )

    assert response.status_code == 200


async def test_remote_bind_missing_session_token_rejected(remote_bind_app):
    async with _make_client(remote_bind_app) as loopback_client:
        await loopback_client.get("/api/mgmt/health")
    async with _make_client(remote_bind_app, client_host="10.0.0.2") as remote_client:
        response = await remote_client.get("/api/mgmt/health")

    assert response.status_code == 401
    assert response.json()["code"] == "auth_failed"


async def test_remote_bind_first_loopback_issues_token(remote_bind_app):
    async with _make_client(remote_bind_app) as client:
        response = await client.get("/api/mgmt/health")

    body = response.json()
    assert response.status_code == 200
    assert body["session_token"] == remote_bind_app.state.session_token
    assert "aim_session=" in response.headers["set-cookie"]


async def test_remote_bind_non_loopback_before_issue_rejected(remote_bind_app):
    async with _make_client(remote_bind_app, client_host="10.0.0.2") as client:
        response = await client.get("/api/mgmt/health")

    assert response.status_code == 401
    assert "not yet issued" in response.json()["message"]


async def test_remote_bind_cookie_auth_accepted(remote_bind_app):
    async with _make_client(remote_bind_app) as loopback_client:
        issued = await loopback_client.get("/api/mgmt/health")
        cookie = issued.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]
    async with _make_client(remote_bind_app, client_host="10.0.0.2") as remote_client:
        remote_client.cookies.set("aim_session", cookie)
        response = await remote_client.get("/api/mgmt/health")

    assert response.status_code == 200


async def test_health_includes_csrf_token_in_body(app_with_state):
    async with _make_client(app_with_state) as client:
        response = await client.get("/api/mgmt/health")

    body = response.json()
    assert body["csrf_token"] == response.headers["X-CSRF-Token"]
