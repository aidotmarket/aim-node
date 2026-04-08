"""Process lifecycle manager for provider and consumer."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from pathlib import Path
from typing import Optional

from aim_node.config_loader import load_adapter_config, load_config
from aim_node.core.config import AIMCoreConfig
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.trust_channel import TrustChannelClient
from aim_node.provider.adapter import HttpJsonAdapter
from aim_node.provider.session_handler import ProviderSessionHandler
from aim_node.consumer.proxy import LocalProxy
from aim_node.consumer.session_manager import SessionManager
from aim_node.core.market_client import MarketClient

from .state import ProcessStateStore, NodeState

logger = logging.getLogger(__name__)

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli


class ProcessManager:
    """
    Start/stop provider and consumer as async tasks.

    Checks ProcessStateStore before starting:
    - SETUP_INCOMPLETE → raises PreconditionError (412)
    - LOCKED → raises LockedError (423)
    - READY → proceeds

    Passphrase propagation:
    Before starting any process, sets os.environ["AIM_KEYSTORE_PASSPHRASE"]
    from ProcessStateStore's in-memory passphrase. This is required because
    runtime handshake code reads the passphrase from this env var, not from
    any in-memory store.
    """

    def __init__(self, state: ProcessStateStore, data_dir: Path):
        self._state = state
        self._data_dir = data_dir
        self._provider_task: Optional[asyncio.Task] = None
        self._consumer_proxy: Optional[LocalProxy] = None
        self._consumer_session_mgr: Optional[SessionManager] = None
        self._trust_channel: Optional[TrustChannelClient] = None
        self._trust_task: Optional[asyncio.Task] = None

    def _load_raw_config(self) -> dict:
        config_path = self._data_dir / "config.toml"
        with open(config_path, "rb") as f:
            return tomli.load(f)

    def _check_ready(self) -> None:
        """Raise if node not ready to start processes."""
        status = self._state.get_status()
        if not status["setup_complete"]:
            raise PreconditionError("Setup not complete")
        if status["locked"]:
            raise LockedError("Node is locked — unlock first")

    def _propagate_passphrase(self) -> None:
        """Set AIM_KEYSTORE_PASSPHRASE env var from in-memory passphrase.
        Unconditionally overwrites to prevent stale secrets from prior runs."""
        os.environ["AIM_KEYSTORE_PASSPHRASE"] = self._state.get_passphrase() or ""

    async def start_provider(self) -> None:
        self._check_ready()
        with self._state._state_lock:
            if self._state.provider.running:
                raise AlreadyRunningError("Provider already running")

        self._propagate_passphrase()

        raw = self._load_raw_config()
        config = load_config(raw)
        adapter_config = load_adapter_config(raw)

        passphrase = self._state.get_passphrase() or ""
        crypto = DeviceCrypto(config, passphrase=passphrase)
        crypto.get_or_create_keypairs()

        self._trust_channel = TrustChannelClient(config)
        adapter = HttpJsonAdapter(adapter_config)
        handler = ProviderSessionHandler(config, adapter, self._trust_channel)

        async def _run():
            try:
                self._trust_task = asyncio.create_task(self._trust_channel.run())
                await handler.start()
                with self._state._state_lock:
                    self._state.provider.running = True
                    self._state.provider.started_at = time.time()
                # Block until cancelled
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await handler.stop()
                if self._trust_task:
                    self._trust_task.cancel()
                with self._state._state_lock:
                    self._state.provider.running = False
                    self._state.provider.started_at = None

        self._provider_task = asyncio.create_task(_run())
        # Wait briefly for startup
        await asyncio.sleep(0.1)

    async def stop_provider(self) -> None:
        with self._state._state_lock:
            if not self._state.provider.running:
                raise NotRunningError("Provider not running")
        if self._provider_task:
            self._provider_task.cancel()
            await self._provider_task
            self._provider_task = None

    async def start_consumer(self, bind_host: str = "127.0.0.1") -> int:
        """Start consumer proxy. Returns proxy port.

        Args:
            bind_host: Host to bind the local proxy to. Default "127.0.0.1"
                for CLI usage. Use "0.0.0.0" for Docker/serve mode.
                Passed as constructor parameter to LocalProxy (no monkeypatching).
        """
        self._check_ready()
        with self._state._state_lock:
            if self._state.consumer.running:
                raise AlreadyRunningError("Consumer already running")

        self._propagate_passphrase()

        raw = self._load_raw_config()
        config = load_config(raw)

        # SessionManager takes (config, market_client) — NOT (config, crypto)
        market_client = MarketClient(config)
        self._consumer_session_mgr = SessionManager(config, market_client)

        # LocalProxy accepts optional host param (see Modified Files section)
        self._consumer_proxy = LocalProxy(config, self._consumer_session_mgr, host=bind_host)

        await self._consumer_proxy.start()
        port = self._consumer_proxy._port

        with self._state._state_lock:
            self._state.consumer.running = True
            self._state.consumer.started_at = time.time()
        return port

    async def stop_consumer(self) -> None:
        with self._state._state_lock:
            if not self._state.consumer.running:
                raise NotRunningError("Consumer not running")
        if self._consumer_proxy:
            await self._consumer_proxy.stop()
            self._consumer_proxy = None
        with self._state._state_lock:
            self._state.consumer.running = False
            self._state.consumer.started_at = None

    async def shutdown(self) -> None:
        """Graceful shutdown: stop provider and consumer if running.
        Suppresses NotRunningError."""
        try:
            await self.stop_provider()
        except NotRunningError:
            pass
        try:
            await self.stop_consumer()
        except NotRunningError:
            pass

    async def autostart(self, bind_host: str = "127.0.0.1") -> None:
        """Auto-start based on config mode. Called after setup/unlock.

        Best-effort: errors are logged and suppressed so they don't fail
        the calling endpoint (finalize/unlock)."""
        mode = self._state._mode
        if not mode:
            return
        if mode in ("provider", "both"):
            try:
                await self.start_provider()
            except Exception:
                logger.exception("autostart: provider start failed")
        if mode in ("consumer", "both"):
            try:
                await self.start_consumer(bind_host=bind_host)
            except Exception:
                logger.exception("autostart: consumer start failed")


class PreconditionError(Exception):
    """412 — setup not complete."""


class LockedError(Exception):
    """423 — node locked."""


class AlreadyRunningError(Exception):
    """409 — process already running."""


class NotRunningError(Exception):
    """409 — process not running."""


class ConfigError(Exception):
    """500 — config file parse/IO error."""

