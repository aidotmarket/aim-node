from __future__ import annotations

import asyncio
import os
import unittest
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aim_node.config_loader import load_config
from aim_node.core.crypto import DeviceCrypto
from aim_node.management.config_writer import finalize_setup, read_config, write_config
from aim_node.management.process import (
    AlreadyRunningError,
    LockedError,
    NotRunningError,
    PreconditionError,
    ProcessManager,
)
from aim_node.management.state import NodeState, ProcessStateStore


@pytest.fixture(autouse=True)
def _reset_state_store():
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)
    yield
    ProcessStateStore.reset()
    os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)


def _write_text(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _write_management_config(data_dir: Path, *, setup_complete: bool, setup_step: int = 5, mode: str = "consumer") -> None:
    _write_text(
        data_dir / "config.toml",
        "\n".join(
            [
                "[management]",
                f"setup_complete = {'true' if setup_complete else 'false'}",
                f"setup_step = {setup_step}",
                f'mode = "{mode}"',
                "",
            ]
        ),
    )


def _write_runtime_config(data_dir: Path, *, mode: str = "consumer", upstream_url: str = "http://127.0.0.1:8000/invoke") -> None:
    config = {
        "core": {
            "node_serial": "node-123",
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
    }
    if mode in ("provider", "both"):
        config["provider"] = {"adapter": {"endpoint_url": upstream_url}}
    write_config(data_dir, config)


def _create_keystore(data_dir: Path, passphrase: str) -> None:
    config = type(
        "Config",
        (),
        {
            "keystore_path": data_dir / "keystore.json",
            "data_dir": data_dir,
        },
    )()
    DeviceCrypto(config, passphrase=passphrase).get_or_create_keypairs()


def test_state_store_singleton(tmp_path: Path):
    first = ProcessStateStore(tmp_path)
    second = ProcessStateStore(tmp_path)
    assert first is second


def test_state_store_reset(tmp_path: Path):
    first = ProcessStateStore(tmp_path)
    ProcessStateStore.reset()
    second = ProcessStateStore(tmp_path)
    assert first is not second


def test_initial_state_no_config(tmp_path: Path):
    state = ProcessStateStore(tmp_path)
    assert state.get_status()["setup_complete"] is False
    assert state.node_state == NodeState.SETUP_INCOMPLETE


def test_initial_state_setup_complete_unlocked(tmp_path: Path):
    _write_management_config(tmp_path, setup_complete=True)
    _create_keystore(tmp_path, passphrase="")
    state = ProcessStateStore(tmp_path)
    assert state.node_state == NodeState.READY


def test_initial_state_setup_complete_locked(tmp_path: Path):
    _write_management_config(tmp_path, setup_complete=True)
    _create_keystore(tmp_path, passphrase="secret")
    state = ProcessStateStore(tmp_path)
    assert state.node_state == NodeState.LOCKED


def test_unlock_success(tmp_path: Path):
    _write_management_config(tmp_path, setup_complete=True)
    _create_keystore(tmp_path, passphrase="secret")
    state = ProcessStateStore(tmp_path)
    assert state.unlock("secret") is True
    assert state.node_state == NodeState.READY


def test_unlock_failure(tmp_path: Path):
    _write_management_config(tmp_path, setup_complete=True)
    _create_keystore(tmp_path, passphrase="secret")
    state = ProcessStateStore(tmp_path)
    assert state.unlock("wrong") is False
    assert state.node_state == NodeState.LOCKED


class TestProcessManagerAsync(unittest.IsolatedAsyncioTestCase):
    tmpdir: Path

    @pytest.fixture(autouse=True)
    def _inject_tmpdir(self, tmp_path: Path):
        self.tmpdir = tmp_path

    def tearDown(self) -> None:
        ProcessStateStore.reset()
        os.environ.pop("AIM_KEYSTORE_PASSPHRASE", None)

    async def test_start_provider_setup_incomplete(self):
        state = ProcessStateStore(self.tmpdir)
        manager = ProcessManager(state, self.tmpdir)
        with self.assertRaises(PreconditionError):
            await manager.start_provider()

    async def test_start_provider_locked(self):
        _write_runtime_config(self.tmpdir, mode="provider")
        _create_keystore(self.tmpdir, passphrase="secret")
        state = ProcessStateStore(self.tmpdir)
        manager = ProcessManager(state, self.tmpdir)
        with self.assertRaises(LockedError):
            await manager.start_provider()

    async def test_start_stop_idempotency(self):
        _write_runtime_config(self.tmpdir, mode="provider")
        _create_keystore(self.tmpdir, passphrase="")
        state = ProcessStateStore(self.tmpdir)
        manager = ProcessManager(state, self.tmpdir)

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
            await manager.start_provider()
            with self.assertRaises(AlreadyRunningError):
                await manager.start_provider()
            await manager.stop_provider()
            with self.assertRaises(NotRunningError):
                await manager.stop_provider()

    async def test_provider_handler_reference_lifecycle(self):
        _write_runtime_config(self.tmpdir, mode="provider")
        _create_keystore(self.tmpdir, passphrase="")
        state = ProcessStateStore(self.tmpdir)
        manager = ProcessManager(state, self.tmpdir)

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
            await manager.start_provider()
            self.assertIs(manager._provider_handler, handler)
            await manager.stop_provider()

        self.assertIsNone(manager._provider_handler)
        handler.stop.assert_awaited_once()

    async def test_consumer_construction_uses_market_client(self):
        _write_runtime_config(self.tmpdir, mode="consumer")
        _create_keystore(self.tmpdir, passphrase="")
        state = ProcessStateStore(self.tmpdir)
        manager = ProcessManager(state, self.tmpdir)

        fake_market_client = object()
        fake_proxy = MagicMock()
        fake_proxy._port = 8400
        fake_proxy.start = AsyncMock()
        fake_proxy.stop = AsyncMock()
        session_manager_instance = MagicMock()

        with (
            patch("aim_node.management.process.MarketClient", return_value=fake_market_client) as market_client_cls,
            patch("aim_node.management.process.SessionManager", return_value=session_manager_instance) as session_manager_cls,
            patch("aim_node.management.process.LocalProxy", return_value=fake_proxy),
        ):
            port = await manager.start_consumer()

        self.assertEqual(port, 8400)
        market_client_cls.assert_called_once()
        session_manager_cls.assert_called_once()
        args = session_manager_cls.call_args.args
        self.assertEqual(len(args), 2)
        self.assertIs(args[1], fake_market_client)


def test_config_roundtrip_nested_sections(tmp_path: Path):
    config = {
        "core": {"node_serial": "node-123", "api_key": "api-key"},
        "provider": {"adapter": {"endpoint_url": "http://127.0.0.1:8000/invoke"}},
        "management": {"setup_complete": True, "setup_step": 5, "mode": "provider"},
    }
    write_config(tmp_path, config)
    assert read_config(tmp_path) == config


def test_finalize_setup_writes_node_serial(tmp_path: Path):
    finalize_setup(
        tmp_path,
        mode="provider",
        api_url="https://api.example.test",
        api_key="api-key",
        node_serial="node-123",
        upstream_url="http://127.0.0.1:8000/invoke",
    )
    raw = read_config(tmp_path)
    assert raw["core"]["node_serial"] == "node-123"
    load_config(raw)


def test_finalize_setup_generates_uuid_when_none(tmp_path: Path):
    finalize_setup(
        tmp_path,
        mode="consumer",
        api_url="https://api.example.test",
        api_key="api-key",
        node_serial=None,
    )
    raw = read_config(tmp_path)
    uuid.UUID(raw["core"]["node_serial"])


def test_passphrase_propagation_to_env(tmp_path: Path):
    _write_management_config(tmp_path, setup_complete=True)
    _create_keystore(tmp_path, passphrase="secret")
    state = ProcessStateStore(tmp_path)
    assert state.unlock("secret") is True
    manager = ProcessManager(state, tmp_path)
    manager._propagate_passphrase()
    assert os.environ["AIM_KEYSTORE_PASSPHRASE"] == "secret"


def test_node_state_determined_on_init(tmp_path: Path):
    _write_management_config(tmp_path, setup_complete=True)
    _create_keystore(tmp_path, passphrase="")
    state = ProcessStateStore(tmp_path)
    assert state.node_state == NodeState.READY


def test_passphrase_env_overwrites_stale(tmp_path: Path):
    os.environ["AIM_KEYSTORE_PASSPHRASE"] = "old_stale_value"
    _write_management_config(tmp_path, setup_complete=True)
    _create_keystore(tmp_path, passphrase="")
    state = ProcessStateStore(tmp_path)
    manager = ProcessManager(state, tmp_path)
    manager._propagate_passphrase()
    assert os.environ["AIM_KEYSTORE_PASSPHRASE"] == ""
