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
                inst = super().__new__(cls)
                inst._initialized = False
                cls._instance = inst
            return cls._instance

    def __init__(self, data_dir: Path):
        with self._lock:
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
            self._node_state: NodeState = NodeState.SETUP_INCOMPLETE

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

            # Load persisted state and determine node state
            self._load_config()
            self._node_state = self._determine_node_state_internal()
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

    def _check_keystore_locked(self) -> bool:
        """Check if keystore requires passphrase. Returns True if locked."""
        keystore_path = self._data_dir / "keystore.json"
        if not keystore_path.exists():
            return False  # No keystore → not locked (still in setup)
        try:
            from aim_node.core.crypto import DeviceCrypto
            config = type('C', (), {
                'keystore_path': keystore_path,
                'data_dir': self._data_dir
            })()
            crypto = DeviceCrypto(config, passphrase="")
            crypto.get_or_create_keypairs()
            return False  # Loaded without passphrase → not locked
        except Exception:
            return True  # Needs passphrase → locked

    def _determine_node_state_internal(self) -> NodeState:
        """Internal state determination. Caller must hold appropriate lock or be in __init__."""
        if not self._setup_complete:
            return NodeState.SETUP_INCOMPLETE
        if self._unlocked:
            return NodeState.READY
        if self._check_keystore_locked():
            self._locked = True
            return NodeState.LOCKED
        self._unlocked = True
        self._locked = False
        return NodeState.READY

    def determine_node_state(self) -> NodeState:
        """Determine current node state. Called after state changes."""
        with self._state_lock:
            self._node_state = self._determine_node_state_internal()
            return self._node_state

    @property
    def node_state(self) -> NodeState:
        return self._node_state

    def unlock(self, passphrase: str) -> bool:
        """Attempt to unlock with passphrase. Returns True on success."""
        keystore_path = self._data_dir / "keystore.json"
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
                self._node_state = NodeState.READY
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

    def get_passphrase(self) -> Optional[str]:
        """Return in-memory passphrase for env propagation."""
        return self._passphrase

    def get_status(self) -> dict:
        """Return canonical status dict for API responses."""
        with self._state_lock:
            return {
                "setup_complete": self._setup_complete,
                "locked": self._locked,
                "unlocked": self._unlocked,
                "current_step": self._setup_step,
                "node_state": self._node_state.value,
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

    def get_session(self, session_id: str) -> Optional[dict]:
        """Return single session detail by ID, or None if not found."""
        with self._state_lock:
            for s in self._sessions:
                if s.session_id == session_id:
                    return {
                        "id": s.session_id,
                        "role": s.role,
                        "state": s.state,
                        "created_at": s.created_at,
                        "peer_fingerprint": s.peer_fingerprint,
                        "bytes_transferred": s.bytes_transferred,
                        "metering_events": [],
                        "latency_ms": None,
                        "error_count": 0,
                    }
            return None

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

