from __future__ import annotations

from pathlib import Path
from typing import Any

from aim_node.core.config import AIMCoreConfig
from aim_node.provider.adapter import AdapterConfig

DEFAULT_KEYSTORE_PATH = Path(".aim-node/keystore.json")
DEFAULT_DATA_DIR = Path(".aim-node")


def _get_section(raw: dict[str, Any], key: str) -> dict[str, Any]:
    value = raw.get(key, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"expected [{key}] to be a table")
    return value


def _optional_str(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    return value


def _required_str(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field_name} is required")
    return value


def _optional_float(value: Any, field_name: str, default: float) -> float:
    if value is None:
        return default
    if not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)


def _optional_int(value: Any, field_name: str, default: int) -> int:
    if value is None:
        return default
    if not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def load_config(raw: dict) -> AIMCoreConfig:
    """Extract AIMCoreConfig fields from parsed TOML dict."""
    core = _get_section(raw, "core")

    node_serial = _required_str(core.get("node_serial", raw.get("node_serial")), "core.node_serial")
    keystore_path = Path(
        _optional_str(core.get("keystore_path", raw.get("keystore_path")), "core.keystore_path")
        or str(DEFAULT_KEYSTORE_PATH)
    )
    data_dir = Path(
        _optional_str(core.get("data_dir", raw.get("data_dir")), "core.data_dir")
        or str(DEFAULT_DATA_DIR)
    )

    return AIMCoreConfig(
        keystore_path=keystore_path,
        node_serial=node_serial,
        market_api_url=_optional_str(core.get("market_api_url", raw.get("market_api_url")), "core.market_api_url")
        or AIMCoreConfig.market_api_url,
        market_ws_url=_optional_str(core.get("market_ws_url", raw.get("market_ws_url")), "core.market_ws_url")
        or AIMCoreConfig.market_ws_url,
        data_dir=data_dir,
        reconnect_delay_s=_optional_float(
            core.get("reconnect_delay_s", raw.get("reconnect_delay_s")),
            "core.reconnect_delay_s",
            AIMCoreConfig.reconnect_delay_s,
        ),
        reconnect_max_delay_s=_optional_float(
            core.get("reconnect_max_delay_s", raw.get("reconnect_max_delay_s")),
            "core.reconnect_max_delay_s",
            AIMCoreConfig.reconnect_max_delay_s,
        ),
        reconnect_jitter=_optional_float(
            core.get("reconnect_jitter", raw.get("reconnect_jitter")),
            "core.reconnect_jitter",
            AIMCoreConfig.reconnect_jitter,
        ),
        api_key=_optional_str(core.get("api_key", raw.get("api_key")), "core.api_key"),
        node_id=_optional_str(core.get("node_id", raw.get("node_id")), "core.node_id"),
        upstream_url=_optional_str(
            _get_section(_get_section(raw, "provider"), "adapter").get("endpoint_url"),
            "provider.adapter.endpoint_url",
        ),
    )


def load_adapter_config(raw: dict) -> AdapterConfig:
    """Extract AdapterConfig from [provider.adapter] section."""
    provider = _get_section(raw, "provider")
    adapter = _get_section(provider, "adapter")

    return AdapterConfig(
        endpoint_url=_required_str(adapter.get("endpoint_url"), "provider.adapter.endpoint_url"),
        health_check_url=_optional_str(adapter.get("health_check_url"), "provider.adapter.health_check_url"),
        timeout_seconds=_optional_int(adapter.get("timeout_seconds"), "provider.adapter.timeout_seconds", 30),
        max_concurrent=_optional_int(adapter.get("max_concurrent"), "provider.adapter.max_concurrent", 10),
        max_body_bytes=_optional_int(adapter.get("max_body_bytes"), "provider.adapter.max_body_bytes", 32768),
        input_path=_optional_str(adapter.get("input_path"), "provider.adapter.input_path"),
        wrap_key=_optional_str(adapter.get("wrap_key"), "provider.adapter.wrap_key"),
        output_path=_optional_str(adapter.get("output_path"), "provider.adapter.output_path"),
    )


def generate_default_config() -> str:
    """Return default aim-node.toml content as a string."""
    return """[core]
node_serial = "__NODE_SERIAL__"
keystore_path = ".aim-node/keystore.json"
data_dir = ".aim-node"
market_api_url = "https://api.ai.market"
market_ws_url = "wss://api.ai.market/ws"
reconnect_delay_s = 5.0
reconnect_max_delay_s = 60.0
reconnect_jitter = 0.3
api_key = ""

[provider.adapter]
endpoint_url = "http://127.0.0.1:8000/invoke"
health_check_url = "http://127.0.0.1:8000/health"
timeout_seconds = 30
max_concurrent = 10
max_body_bytes = 32768
input_path = "$"
wrap_key = "input"
output_path = "$"
"""
