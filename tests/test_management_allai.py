from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from aim_node.core.crypto import DeviceCrypto
from aim_node.management.allai import ProposedAction
from aim_node.management.app import create_management_app
from aim_node.management.config_writer import write_config
from aim_node.management.process import ProcessManager
from aim_node.management.state import ProcessStateStore, write_store


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


def _write_runtime_config(data_dir: Path) -> None:
    write_config(
        data_dir,
        {
            "core": {
                "node_serial": "node-test-123",
                "node_id": "node-backend-123",
                "keystore_path": str(data_dir / "keystore.json"),
                "data_dir": str(data_dir),
                "market_api_url": "https://api.example.test",
                "api_key": "secret-api-key",
            },
            "management": {
                "setup_complete": True,
                "setup_step": 5,
                "mode": "consumer",
            },
        },
    )


def _build_app(data_dir: Path):
    app = create_management_app(data_dir)
    state = ProcessStateStore(data_dir)
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    app.state.allai_action_cache = {}
    return app, state, process_mgr


def _make_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://testserver",
        headers={"Origin": "http://localhost"},
    )


@pytest.fixture
def setup_complete_app(tmp_path: Path):
    _write_runtime_config(tmp_path)
    _create_keystore(tmp_path, passphrase="")
    return _build_app(tmp_path)


async def test_allai_chat_injects_context_redacts_and_forwards_to_facade(setup_complete_app):
    app, state, _ = setup_complete_app
    write_store(
        state._data_dir,
        "discovered_tools",
        {
            "tools": [
                {
                    "name": "inspect",
                    "api_key": "should-not-leak",
                    "session_token": "secret-token",
                }
            ],
            "csrf_token": "csrf-secret",
        },
    )

    facade = MagicMock()
    facade.node_id = "node-backend-123"
    facade.post = AsyncMock(
        return_value={
            "reply": "hello",
            "conversation_id": "conv-1",
            "proposed_actions": None,
            "suggestions": ["inspect config"],
        }
    )
    app.state.facade = facade

    async with _make_client(app) as client:
        r = await client.post("/allai/chat", json={"message": "status?"})

    assert r.status_code == 200
    payload = facade.post.await_args.kwargs["json_body"]
    assert facade.post.await_args.args == ("/allie/chat/agentic",)
    assert payload["message"] == "status?"
    assert payload["node_id"] == "node-backend-123"
    assert payload["allowed_tools"]
    assert payload["context"]["status"]["node_state"] == state.get_status()["node_state"]
    assert payload["context"]["discovered_tools"]["csrf_token"] == "[redacted]"
    assert payload["context"]["discovered_tools"]["tools"][0]["api_key"] == "[redacted]"
    assert payload["context"]["discovered_tools"]["tools"][0]["session_token"] == "[redacted]"
    assert "degraded_context" not in payload
    assert r.json()["conversation_id"] == "conv-1"


async def test_allai_chat_sets_degraded_context_when_store_lookup_fails(setup_complete_app, monkeypatch):
    app, state, _ = setup_complete_app
    facade = MagicMock()
    facade.node_id = "node-backend-123"
    facade.post = AsyncMock(
        return_value={
            "reply": "degraded",
            "conversation_id": "conv-2",
            "proposed_actions": None,
            "suggestions": None,
        }
    )
    app.state.facade = facade

    def _boom():
        raise RuntimeError("status unavailable")

    monkeypatch.setattr(state, "get_status", _boom)

    async with _make_client(app) as client:
        r = await client.post("/allai/chat", json={"message": "status?"})

    assert r.status_code == 200
    payload = facade.post.await_args.kwargs["json_body"]
    assert payload["degraded_context"] is True
    assert "status" not in payload["context"]


async def test_allai_chat_caches_confirmation_actions(setup_complete_app):
    app, _, _ = setup_complete_app
    facade = MagicMock()
    facade.node_id = "node-backend-123"
    facade.post = AsyncMock(
        return_value={
            "reply": "need approval",
            "conversation_id": "conv-3",
            "proposed_actions": [
                {
                    "action_id": "act-1",
                    "description": "Inspect config",
                    "tool_name": "inspect_local_config",
                    "params": {},
                    "requires_confirmation": True,
                }
            ],
            "suggestions": None,
        }
    )
    app.state.facade = facade

    async with _make_client(app) as client:
        r = await client.post("/allai/chat", json={"message": "inspect"})

    assert r.status_code == 200
    assert r.json()["proposed_actions"][0]["action_id"] == "act-1"
    assert "act-1" in app.state.allai_action_cache


async def test_allai_chat_auto_executes_allowed_actions(setup_complete_app):
    app, state, _ = setup_complete_app
    facade = MagicMock()
    facade.node_id = "node-backend-123"
    facade.post = AsyncMock(
        side_effect=[
            {
                "reply": "running local check",
                "conversation_id": "conv-4",
                "proposed_actions": [
                    {
                        "action_id": "act-auto",
                        "description": "Inspect config",
                        "tool_name": "inspect_local_config",
                        "params": {},
                        "requires_confirmation": False,
                    }
                ],
                "suggestions": None,
            },
            {
                "reply": "done",
                "conversation_id": "conv-4",
                "proposed_actions": None,
                "suggestions": None,
            },
        ]
    )
    app.state.facade = facade

    async with _make_client(app) as client:
        r = await client.post("/allai/chat", json={"message": "inspect"})

    assert r.status_code == 200
    body = r.json()
    assert body["conversation_id"] == "conv-4"
    assert "Local action results:" in body["reply"]
    second_payload = facade.post.await_args_list[1].kwargs["json_body"]
    assert second_payload["tool_results"][0]["action_id"] == "act-auto"
    assert second_payload["tool_results"][0]["result"]["config"]["core"]["api_key"] == "[redacted]"
    assert state._data_dir.exists()


async def test_allai_confirm_approve_executes_cached_action(setup_complete_app):
    app, _, _ = setup_complete_app
    app.state.allai_action_cache["act-approve"] = ProposedAction(
        action_id="act-approve",
        description="Inspect config",
        tool_name="inspect_local_config",
        params={},
        requires_confirmation=True,
    )

    async with _make_client(app) as client:
        r = await client.post(
            "/allai/confirm",
            json={"action_id": "act-approve", "approved": True},
        )

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "executed"
    assert body["result"]["config"]["core"]["api_key"] == "[redacted]"
    assert "act-approve" not in app.state.allai_action_cache


async def test_allai_confirm_deny_discards_cached_action(setup_complete_app):
    app, _, _ = setup_complete_app
    app.state.allai_action_cache["act-deny"] = ProposedAction(
        action_id="act-deny",
        description="Inspect config",
        tool_name="inspect_local_config",
        params={},
        requires_confirmation=True,
    )

    async with _make_client(app) as client:
        r = await client.post(
            "/allai/confirm",
            json={"action_id": "act-deny", "approved": False},
        )

    assert r.status_code == 200
    assert r.json() == {"status": "denied"}
    assert "act-deny" not in app.state.allai_action_cache


async def test_allai_confirm_unknown_action_returns_404(setup_complete_app):
    app, _, _ = setup_complete_app

    async with _make_client(app) as client:
        r = await client.post(
            "/allai/confirm",
            json={"action_id": "missing", "approved": True},
        )

    assert r.status_code == 404
    assert r.json()["code"] == "not_found"
