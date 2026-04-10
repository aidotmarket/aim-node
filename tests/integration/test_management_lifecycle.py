"""Scenario 1: Management API lifecycle integration tests.

Exercises setup flow, finalize, unlock, autostart, dashboard, config CRUD,
provider/consumer start/stop, and session inspection through the management
HTTP API as a single coherent lifecycle.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aim_node.management.state import SessionSnapshot

from .conftest import make_client, patch_httpx


# ---------------------------------------------------------------------------
# Full lifecycle: setup -> finalize -> dashboard -> config -> start/stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_full_setup_finalize_lifecycle(fresh_app, tmp_data_dir, monkeypatch):
    """Walk through the complete setup flow: status -> keypair -> finalize -> dashboard."""
    app, state, pm = fresh_app
    patch_httpx(monkeypatch, status_code=200, json_data={"version": "1.0.0"})

    async with make_client(app) as client:
        # Step 1: Check initial status
        r = await client.get("/api/mgmt/setup/status")
        assert r.status_code == 200
        body = r.json()
        assert body["setup_complete"] is False
        assert body["current_step"] == 0

        # Step 2: Generate keypair
        r = await client.post("/api/mgmt/setup/keypair", json={"passphrase": ""})
        assert r.status_code == 200
        assert r.json()["created"] is True
        fingerprint = r.json()["fingerprint"]
        assert len(fingerprint) == 64

        # Step 3: Test connection
        r = await client.post(
            "/api/mgmt/setup/test-connection",
            json={"api_url": "https://api.example.test", "api_key": "key-1"},
        )
        assert r.status_code == 200
        assert r.json()["reachable"] is True

        # Step 4: Finalize
        r = await client.post(
            "/api/mgmt/setup/finalize",
            json={
                "mode": "consumer",
                "api_url": "https://api.example.test",
                "api_key": "key-1",
            },
        )
        assert r.status_code == 200
        assert r.json()["ok"] is True

        # Step 5: Verify setup complete
        r = await client.get("/api/mgmt/setup/status")
        assert r.json()["setup_complete"] is True

        # Step 6: Dashboard
        r = await client.get("/api/mgmt/status")
        assert r.status_code == 200
        dash = r.json()
        assert dash["market_connected"] is True
        assert dash["provider_running"] is False
        # consumer_running may be True due to autostart after finalize


@pytest.mark.asyncio
async def test_finalize_autostart_triggers(fresh_app, tmp_data_dir, monkeypatch):
    """Finalize calls autostart on the process manager."""
    app, state, pm = fresh_app
    autostart_called = False
    original_autostart = pm.autostart

    async def fake_autostart():
        nonlocal autostart_called
        autostart_called = True

    pm.autostart = fake_autostart
    try:
        async with make_client(app) as client:
            r = await client.post(
                "/api/mgmt/setup/finalize",
                json={
                    "mode": "consumer",
                    "api_url": "https://api.example.test",
                    "api_key": "key-1",
                },
            )
        assert r.status_code == 200
        assert autostart_called is True
    finally:
        pm.autostart = original_autostart


@pytest.mark.asyncio
async def test_unlock_then_autostart(locked_app, monkeypatch):
    """Unlock triggers autostart."""
    app, state, pm = locked_app
    autostart_called = False

    async def fake_autostart():
        nonlocal autostart_called
        autostart_called = True

    pm.autostart = fake_autostart
    try:
        async with make_client(app) as client:
            r = await client.post("/api/mgmt/unlock", json={"passphrase": "test-pass-123"})
        assert r.status_code == 200
        assert r.json()["unlocked"] is True
        assert autostart_called is True
    finally:
        pm.autostart = fake_autostart  # no real cleanup needed


@pytest.mark.asyncio
async def test_config_read_update_roundtrip(setup_consumer_app, monkeypatch):
    """Read config, update it, read again to verify persistence."""
    app, state, pm = setup_consumer_app

    async with make_client(app) as client:
        # Read initial
        r = await client.get("/api/mgmt/config")
        assert r.status_code == 200
        assert r.json()["mode"] == "consumer"
        assert r.json()["api_key_set"] is True

        # Update mode (requires upstream_url for provider)
        r = await client.put(
            "/api/mgmt/config",
            json={"mode": "both", "upstream_url": "http://127.0.0.1:9000/invoke"},
        )
        assert r.status_code == 200
        assert r.json()["restart_required"] is True

        # Verify update persisted
        r = await client.get("/api/mgmt/config")
        assert r.json()["mode"] == "both"


@pytest.mark.asyncio
async def test_provider_start_stop_cycle(setup_provider_app):
    """Start provider, verify state, stop, verify state."""
    app, state, pm = setup_provider_app

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
        async with make_client(app) as client:
            # Start
            r = await client.post("/api/mgmt/provider/start")
            assert r.status_code == 200
            assert r.json()["started"] is True

            # Double-start should 409
            r = await client.post("/api/mgmt/provider/start")
            assert r.status_code == 409

            # Stop
            r = await client.post("/api/mgmt/provider/stop")
            assert r.status_code == 200
            assert r.json()["stopped"] is True

            # Double-stop should 409
            r = await client.post("/api/mgmt/provider/stop")
            assert r.status_code == 409


@pytest.mark.asyncio
async def test_consumer_start_stop_cycle(setup_consumer_app):
    """Start consumer, verify state, stop, verify state."""
    app, state, pm = setup_consumer_app

    fake_proxy = MagicMock()
    fake_proxy._port = 8400
    fake_proxy.start = AsyncMock()
    fake_proxy.stop = AsyncMock()

    with (
        patch("aim_node.management.process.MarketClient", return_value=object()),
        patch("aim_node.management.process.SessionManager", return_value=MagicMock()),
        patch("aim_node.management.process.LocalProxy", return_value=fake_proxy),
    ):
        async with make_client(app) as client:
            # Start
            r = await client.post("/api/mgmt/consumer/start")
            assert r.status_code == 200
            body = r.json()
            assert body["started"] is True
            assert body["proxy_port"] == 8400

            # Double-start should 409
            r = await client.post("/api/mgmt/consumer/start")
            assert r.status_code == 409

            # Stop
            r = await client.post("/api/mgmt/consumer/stop")
            assert r.status_code == 200
            assert r.json()["stopped"] is True

            # Double-stop should 409
            r = await client.post("/api/mgmt/consumer/stop")
            assert r.status_code == 409


@pytest.mark.asyncio
async def test_session_inspection_lifecycle(setup_consumer_app):
    """Add sessions to state, list them, inspect detail, verify 404 on missing."""
    app, state, pm = setup_consumer_app

    state.add_session(SessionSnapshot(
        session_id="sess-alpha",
        role="consumer",
        state="active",
        created_at=1000.0,
    ))
    state.add_session(SessionSnapshot(
        session_id="sess-beta",
        role="provider",
        state="closed",
        created_at=2000.0,
    ))

    async with make_client(app) as client:
        # List all
        r = await client.get("/api/mgmt/sessions")
        assert r.status_code == 200
        sessions = r.json()["sessions"]
        assert len(sessions) == 2
        ids = {s["id"] for s in sessions}
        assert ids == {"sess-alpha", "sess-beta"}

        # Detail
        r = await client.get("/api/mgmt/sessions/sess-alpha")
        assert r.status_code == 200
        detail = r.json()
        assert detail["id"] == "sess-alpha"
        assert detail["role"] == "consumer"
        assert detail["state"] == "active"

        # Not found
        r = await client.get("/api/mgmt/sessions/nonexistent")
        assert r.status_code == 404


@pytest.mark.asyncio
async def test_dashboard_reflects_mode_and_market_status(
    setup_consumer_app, monkeypatch
):
    """Dashboard shows correct node_id, mode, and market connectivity."""
    app, state, pm = setup_consumer_app

    # Market reachable
    patch_httpx(monkeypatch, status_code=200)
    async with make_client(app) as client:
        r = await client.get("/api/mgmt/status")
    assert r.status_code == 200
    body = r.json()
    assert body["node_id"] == "node-test-123"
    assert body["market_connected"] is True

    # Market unreachable
    patch_httpx(monkeypatch, raise_exc=Exception("offline"))
    async with make_client(app) as client:
        r = await client.get("/api/mgmt/status")
    body = r.json()
    assert body["market_connected"] is False
