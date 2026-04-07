from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class AIMCoreConfig:
    keystore_path: Path
    node_serial: str
    market_api_url: str = "https://api.ai.market"
    market_ws_url: str = "wss://api.ai.market/ws"
    data_dir: Path = field(default_factory=lambda: Path.home() / ".aim-node")
    reconnect_delay_s: float = 5.0
    reconnect_max_delay_s: float = 60.0
    reconnect_jitter: float = 0.3
    api_key: str | None = None
