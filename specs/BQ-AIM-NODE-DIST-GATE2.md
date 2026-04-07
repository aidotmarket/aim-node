# BQ-AIM-NODE-DIST — Gate 2 Spec (Slice 1: Management State + Process Model)

**Gate:** 2
**Slice:** 1 of 5
**Depends on:** Gate 1 R6 (APPROVED, commit 5709b0f)

---

## Scope

This slice creates the management foundation: `ProcessStateStore` (state tracking) and `ProcessManager` (lifecycle control). No HTTP endpoints, no UI — those come in Slice 2.

---

## Design Note: Keystore vs PEM

Gate 1 spec references PEM files at `/data/keys/`. The existing codebase uses `DeviceCrypto` with an encrypted JSON keystore (`keystore.json`) via Fernet + PBKDF2. **This slice keeps the existing keystore approach** for backward compatibility. The "PEM" references in Gate 1 are conceptual — the actual storage mechanism is the existing encrypted keystore. Setup wizard will call `DeviceCrypto.get_or_create_keypairs()` which already handles keypair generation and persistence.

---

## New Files

### `aim_node/management/__init__.py`
Empty init.

### `aim_node/management/state.py`

```python
"""Thread-safe singleton for management state tracking."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli


class NodeState(str, Enum):
    SETUP_INCOMPLETE = "setup_incomplete"  # setup_complete == false
    LOCKED = "locked"                       # setup_complete == true, key encrypted, not unlocked
    READY = "ready"                         # setup_complete == true, key available


@dataclass
class ProcessStatus:
    running: bool = False
    started_at: Optional[float] = None  # time.time()
    error: Optional[str] = None


@dataclass
class SessionSnapshot:
    session_id: str
    role: str  # "provider" or "consumer"
    state: str
    created_at: float
    peer_fingerprint: str = ""
    bytes_transferred: int = 0


class ProcessStateStore:
    """
    Thread-safe singleton tracking node management state.
    
    State determination on init:
    1. Read /data/config.toml → check setup_complete flag
    2. If setup_complete == false or missing → NodeState.SETUP_INCOMPLETE
    3. If setup_complete == true → check keystore encryption
    4. If keystore needs passphrase → NodeState.LOCKED
    5. If keystore readable without passphrase → NodeState.READY
    """

    _instance: Optional[ProcessStateStore] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self, data_dir: Path):
        if self._initialized:
            return
        self._data_dir = data_dir
        self._state_lock = threading.Lock()
        
        # Setup state
        self._setup_complete: bool = False
        self._setup_step: int = 0  # 0-5, 5 = done
        
        # Lock state (only meaningful when setup_complete)
        self._locked: bool = False
        self._unlocked: bool = False
        self._passphrase: Optional[str] = None  # in-memory only
        
        # Process state
        self.provider = ProcessStatus()
        self.consumer = ProcessStatus()
        
        # Sessions (updated by ProcessManager callbacks)
        self._sessions: list[SessionSnapshot] = []
        
        # Identity
        self._fingerprint: Optional[str] = None
        self._mode: Optional[str] = None  # "provider", "consumer", "both"
        self._version: str = ""
        self._boot_time: float = time.time()
        
        # Load persisted state
        self._load_config()
        self._initialized = True

    def _load_config(self) -> None:
        """Read config.toml to determine setup_complete and mode."""
        config_path = self._data_dir / "config.toml"
        if not config_path.exists():
            self._setup_complete = False
            self._setup_step = 0
            return
        
        with open(config_path, "rb") as f:
            raw = tomli.load(f)
        
        mgmt = raw.get("management", {})
        self._setup_complete = bool(mgmt.get("setup_complete", False))
        self._setup_step = int(mgmt.get("setup_step", 0))
        self._mode = mgmt.get("mode")
    
    def _check_keystore_locked(self, keystore_path: Path) -> bool:
        """Check if keystore requires passphrase. Returns True if locked."""
        if not keystore_path.exists():
            return False  # No keystore → not locked (still in setup)
        try:
            from aim_node.core.crypto import DeviceCrypto
            # Try loading with empty passphrase
            config = type('C', (), {
                'keystore_path': keystore_path,
                'data_dir': self._data_dir
            })()
            crypto = DeviceCrypto(config, passphrase="")
            crypto.get_or_create_keypairs()
            return False  # Loaded without passphrase → not locked
        except Exception:
            return True  # Needs passphrase → locked

    def determine_node_state(self, keystore_path: Path) -> NodeState:
        """Determine current node state. Called on startup and after state changes."""
        with self._state_lock:
            if not self._setup_complete:
                return NodeState.SETUP_INCOMPLETE
            
            if self._unlocked:
                return NodeState.READY
            
            if self._check_keystore_locked(keystore_path):
                self._locked = True
                return NodeState.LOCKED
            
            self._unlocked = True
            self._locked = False
            return NodeState.READY

    def unlock(self, passphrase: str, keystore_path: Path) -> bool:
        """Attempt to unlock with passphrase. Returns True on success."""
        with self._state_lock:
            try:
                from aim_node.core.crypto import DeviceCrypto
                config = type('C', (), {
                    'keystore_path': keystore_path,
                    'data_dir': self._data_dir
                })()
                crypto = DeviceCrypto(config, passphrase=passphrase)
                crypto.get_or_create_keypairs()
                self._passphrase = passphrase  # hold in memory
                self._locked = False
                self._unlocked = True
                return True
            except Exception:
                return False

    def mark_setup_step(self, step: int) -> None:
        with self._state_lock:
            self._setup_step = step

    def mark_setup_complete(self, mode: str) -> None:
        with self._state_lock:
            self._setup_complete = True
            self._setup_step = 5
            self._mode = mode

    def get_status(self) -> dict:
        """Return canonical status dict for API responses."""
        with self._state_lock:
            return {
                "setup_complete": self._setup_complete,
                "locked": self._locked,
                "unlocked": self._unlocked,
                "current_step": self._setup_step,
            }

    def get_dashboard(self) -> dict:
        with self._state_lock:
            return {
                "fingerprint": self._fingerprint,
                "mode": self._mode,
                "uptime_s": time.time() - self._boot_time,
                "version": self._version,
                "provider_running": self.provider.running,
                "consumer_running": self.consumer.running,
            }

    def add_session(self, snapshot: SessionSnapshot) -> None:
        with self._state_lock:
            self._sessions.append(snapshot)

    def remove_session(self, session_id: str) -> None:
        with self._state_lock:
            self._sessions = [s for s in self._sessions if s.session_id != session_id]

    def get_sessions(self) -> list[dict]:
        with self._state_lock:
            return [
                {
                    "id": s.session_id,
                    "role": s.role,
                    "state": s.state,
                    "created_at": s.created_at,
                    "peer_fingerprint": s.peer_fingerprint,
                    "bytes_transferred": s.bytes_transferred,
                }
                for s in self._sessions
            ]

    @classmethod
    def reset(cls) -> None:
        """Reset singleton for testing."""
        with cls._lock:
            cls._instance = None
```

### `aim_node/management/process.py`

```python
"""Process lifecycle manager for provider and consumer."""

from __future__ import annotations

import asyncio
import logging
import os
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

    async def start_provider(self) -> None:
        self._check_ready()
        if self._state.provider.running:
            raise AlreadyRunningError("Provider already running")

        raw = self._load_raw_config()
        config = load_config(raw)
        adapter_config = load_adapter_config(raw)
        
        passphrase = self._state._passphrase or ""
        crypto = DeviceCrypto(config, passphrase=passphrase)
        crypto.get_or_create_keypairs()
        
        self._trust_channel = TrustChannelClient(config)
        adapter = HttpJsonAdapter(adapter_config)
        handler = ProviderSessionHandler(config, adapter, self._trust_channel)

        async def _run():
            try:
                self._trust_task = asyncio.create_task(self._trust_channel.run())
                await handler.start()
                self._state.provider.running = True
                self._state.provider.started_at = __import__('time').time()
                # Block until cancelled
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            finally:
                await handler.stop()
                if self._trust_task:
                    self._trust_task.cancel()
                self._state.provider.running = False
                self._state.provider.started_at = None

        self._provider_task = asyncio.create_task(_run())
        # Wait briefly for startup
        await asyncio.sleep(0.1)

    async def stop_provider(self) -> None:
        if not self._state.provider.running:
            raise NotRunningError("Provider not running")
        if self._provider_task:
            self._provider_task.cancel()
            await self._provider_task
            self._provider_task = None

    async def start_consumer(self, bind_host: str = "127.0.0.1") -> int:
        """Start consumer proxy. Returns proxy port."""
        self._check_ready()
        if self._state.consumer.running:
            raise AlreadyRunningError("Consumer already running")

        raw = self._load_raw_config()
        config = load_config(raw)
        passphrase = self._state._passphrase or ""
        crypto = DeviceCrypto(config, passphrase=passphrase)
        crypto.get_or_create_keypairs()
        
        self._consumer_session_mgr = SessionManager(config, crypto)
        self._consumer_proxy = LocalProxy(config, self._consumer_session_mgr)
        
        # Override bind host for Docker mode
        if bind_host != "127.0.0.1":
            # Patch the proxy's internal host before start
            import aim_node.consumer.proxy as proxy_mod
            original_host = proxy_mod.DEFAULT_HOST
            proxy_mod.DEFAULT_HOST = bind_host
        
        await self._consumer_proxy.start()
        port = self._consumer_proxy._port
        
        self._state.consumer.running = True
        self._state.consumer.started_at = __import__('time').time()
        return port

    async def stop_consumer(self) -> None:
        if not self._state.consumer.running:
            raise NotRunningError("Consumer not running")
        if self._consumer_proxy:
            await self._consumer_proxy.stop()
            self._consumer_proxy = None
        self._state.consumer.running = False
        self._state.consumer.started_at = None

    async def autostart(self, bind_host: str = "127.0.0.1") -> None:
        """Auto-start based on config mode. Called after setup/unlock."""
        mode = self._state._mode
        if not mode:
            return
        if mode in ("provider", "both"):
            await self.start_provider()
        if mode in ("consumer", "both"):
            await self.start_consumer(bind_host=bind_host)


class PreconditionError(Exception):
    """412 — setup not complete."""

class LockedError(Exception):
    """423 — node locked."""

class AlreadyRunningError(Exception):
    """409 — process already running."""

class NotRunningError(Exception):
    """409 — process not running."""
```

### `aim_node/management/config_writer.py`

```python
"""Write management config to /data/config.toml."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli

try:
    import tomli_w
except ModuleNotFoundError:
    tomli_w = None  # fallback to manual TOML writing


def read_config(data_dir: Path) -> dict:
    config_path = data_dir / "config.toml"
    if not config_path.exists():
        return {}
    with open(config_path, "rb") as f:
        return tomli.load(f)


def write_config(data_dir: Path, config: dict) -> None:
    config_path = data_dir / "config.toml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    if tomli_w:
        with open(config_path, "wb") as f:
            tomli_w.dump(config, f)
    else:
        # Manual TOML serialization for simple flat structure
        with open(config_path, "w") as f:
            _write_toml(f, config)


def _write_toml(f, d: dict, prefix: str = "") -> None:
    """Simple TOML writer for nested dicts with string/bool/int/float values."""
    for k, v in d.items():
        if isinstance(v, dict):
            section = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            f.write(f"\n[{section}]\n")
            _write_toml(f, v, "")
        elif isinstance(v, bool):
            f.write(f'{k} = {"true" if v else "false"}\n')
        elif isinstance(v, str):
            f.write(f'{k} = "{v}"\n')
        elif isinstance(v, (int, float)):
            f.write(f"{k} = {v}\n")


def finalize_setup(
    data_dir: Path,
    mode: str,
    api_url: str,
    api_key: str,
    upstream_url: Optional[str] = None,
) -> None:
    """Write final config after setup wizard completes."""
    config = read_config(data_dir)
    
    # Core section
    if "core" not in config:
        config["core"] = {}
    config["core"]["market_api_url"] = api_url
    config["core"]["api_key"] = api_key
    
    # Provider section (if applicable)
    if mode in ("provider", "both") and upstream_url:
        if "provider" not in config:
            config["provider"] = {}
        if "adapter" not in config["provider"]:
            config["provider"]["adapter"] = {}
        config["provider"]["adapter"]["endpoint_url"] = upstream_url
    
    # Management section
    if "management" not in config:
        config["management"] = {}
    config["management"]["setup_complete"] = True
    config["management"]["setup_step"] = 5
    config["management"]["mode"] = mode
    
    write_config(data_dir, config)
```

---

## Modified Files

### `pyproject.toml`
Add `tomli_w` to optional dependencies (for TOML writing):
```
[project.optional-dependencies]
management = ["tomli_w>=1.0"]
```

---

## Tests: `tests/test_management_state.py`

10 tests:

1. **test_state_store_singleton** — Two `ProcessStateStore(data_dir)` calls return same instance
2. **test_state_store_reset** — After `reset()`, new instance is created
3. **test_initial_state_no_config** — No config.toml → `setup_complete=False`, `NodeState.SETUP_INCOMPLETE`
4. **test_initial_state_setup_complete_unlocked** — config.toml with `setup_complete=true`, unencrypted keystore → `NodeState.READY`
5. **test_initial_state_setup_complete_locked** — config.toml with `setup_complete=true`, encrypted keystore → `NodeState.LOCKED`
6. **test_unlock_success** — `unlock(correct_passphrase)` returns True, state transitions to READY
7. **test_unlock_failure** — `unlock(wrong_passphrase)` returns False, state stays LOCKED
8. **test_start_provider_setup_incomplete** — `ProcessManager.start_provider()` raises `PreconditionError` when setup incomplete
9. **test_start_provider_locked** — `ProcessManager.start_provider()` raises `LockedError` when locked
10. **test_start_stop_idempotency** — Double start raises `AlreadyRunningError`, double stop raises `NotRunningError`

All tests use `ProcessStateStore.reset()` in tearDown and tmpdir fixtures for data_dir.

---

## Acceptance Criteria (Slice 1)

1. `from aim_node.management.state import ProcessStateStore, NodeState` imports cleanly
2. `from aim_node.management.process import ProcessManager` imports cleanly
3. ProcessStateStore correctly determines SETUP_INCOMPLETE / LOCKED / READY from filesystem state
4. ProcessManager refuses to start processes with 412/423 when not ready
5. Config writer persists setup_complete flag to config.toml
6. All 10 tests pass
7. No changes to existing aim_node modules (state/process are additive)

---

## Implementation Notes for Builder

- Use `ProcessStateStore.reset()` between all tests — singleton state leaks across tests otherwise
- `DeviceCrypto` requires a valid `AIMCoreConfig` with `keystore_path` and `data_dir` — create minimal fixtures
- The `_check_keystore_locked` method should be tested with both encrypted and unencrypted keystores — use `DeviceCrypto.get_or_create_keypairs()` with empty vs non-empty passphrase to create both variants
- `tomli_w` may not be installed — the fallback `_write_toml` handles simple cases. Tests should verify roundtrip (write then read back)
- `ProcessManager.start_provider/consumer` are async — tests need `asyncio` fixtures or `unittest.IsolatedAsyncioTestCase`
