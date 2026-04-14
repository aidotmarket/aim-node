"""Write management config to /data/config.toml."""

from __future__ import annotations

import uuid
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

from aim_node.management.process import ConfigError


def read_config(data_dir: Path) -> dict:
    config_path = data_dir / "config.toml"
    if not config_path.exists():
        return {}
    try:
        with open(config_path, "rb") as f:
            return tomli.load(f)
    except OSError as exc:
        raise ConfigError(f"failed to read config: {exc}") from exc
    except Exception as exc:
        raise ConfigError(f"failed to parse config: {exc}") from exc


def write_config(data_dir: Path, config: dict) -> None:
    config_path = data_dir / "config.toml"
    try:
        config_path.parent.mkdir(parents=True, exist_ok=True)
        if tomli_w:
            with open(config_path, "wb") as f:
                tomli_w.dump(config, f)
        else:
            # Manual TOML serialization
            with open(config_path, "w") as f:
                _write_toml(f, config, prefix="")
    except OSError as exc:
        raise ConfigError(f"failed to write config: {exc}") from exc


def _write_toml(f, d: dict, prefix: str) -> None:
    """Simple TOML writer for nested dicts with string/bool/int/float values.

    Tracks full dotted prefix through recursion to correctly emit
    nested sections like [provider.adapter].
    """
    # First pass: write non-dict values at this level
    for k, v in d.items():
        if not isinstance(v, dict):
            if isinstance(v, bool):
                f.write(f'{"" if not prefix else ""}{k} = {"true" if v else "false"}\n')
            elif isinstance(v, str):
                f.write(f'{k} = "{v}"\n')
            elif isinstance(v, (int, float)):
                f.write(f"{k} = {v}\n")

    # Second pass: write dict values as sections
    for k, v in d.items():
        if isinstance(v, dict):
            section = f"{prefix}.{k}" if prefix else k
            f.write(f"\n[{section}]\n")
            _write_toml(f, v, prefix=section)


def finalize_setup(
    data_dir: Path,
    mode: str,
    api_url: str,
    api_key: str,
    node_serial: Optional[str] = None,
    upstream_url: Optional[str] = None,
) -> None:
    """Write final config after setup wizard completes.

    Args:
        data_dir: Path to data directory containing config.toml
        mode: "provider", "consumer", or "both"
        api_url: ai.market API URL
        api_key: ai.market API key
        node_serial: Unique node identifier. If None, generates a UUID.
            Required by load_config() at runtime — must be present in
            core.node_serial or load_config() will raise.
        upstream_url: Provider adapter endpoint (required if mode includes provider)
    """
    config = read_config(data_dir)

    # Core section — must include node_serial for load_config() compatibility
    if "core" not in config:
        config["core"] = {}
    config["core"]["market_api_url"] = api_url
    config["core"]["api_key"] = api_key
    config["core"]["node_serial"] = node_serial or str(uuid.uuid4())

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


def persist_setup_step(data_dir: Path, step: int) -> None:
    """Persist an intermediate setup step to config.toml."""
    config = read_config(data_dir)
    if "management" not in config:
        config["management"] = {}
    config["management"]["setup_step"] = step
    write_config(data_dir, config)
