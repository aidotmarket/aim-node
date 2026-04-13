from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from click.testing import CliRunner

try:
    import tomli
except ModuleNotFoundError:
    import tomllib as tomli

from aim_node.cli import main
from aim_node.config_loader import load_adapter_config, load_config


def test_main_help() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["--help"])

    assert result.exit_code == 0
    assert "AIM Node" in result.output
    assert "provider" in result.output
    assert "consumer" in result.output
    assert "init" in result.output
    assert "status" in result.output


def test_provider_help() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["provider", "--help"])

    assert result.exit_code == 0
    assert "Run AIM Node in provider" in result.output


def test_consumer_help() -> None:
    runner = CliRunner()

    result = runner.invoke(main, ["consumer", "--help"])

    assert result.exit_code == 0
    assert "Run AIM Node in consumer" in result.output


def test_init_creates_config_and_keypair(tmp_path: Path, monkeypatch) -> None:
    runner = CliRunner()
    monkeypatch.chdir(tmp_path)

    result = runner.invoke(main, ["init"], input="secret-passphrase\n")

    assert result.exit_code == 0
    assert (tmp_path / "aim-node.toml").exists()
    assert (tmp_path / ".aim-node" / "keystore.json").exists()
    assert "Initialized AIM Node:" in result.output


def test_load_config_from_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "aim-node.toml"
    config_path.write_text(
        """
[core]
node_serial = "node-abc"
keystore_path = ".aim-node/custom-keystore.json"
data_dir = ".aim-node/state"
market_api_url = "https://market.example/api"
market_ws_url = "wss://market.example/ws"
reconnect_delay_s = 2.5
reconnect_max_delay_s = 25.0
reconnect_jitter = 0.1
api_key = "api-key-123"
""".strip(),
        encoding="utf-8",
    )

    with config_path.open("rb") as handle:
        raw = tomli.load(handle)

    config = load_config(raw)

    assert config.node_serial == "node-abc"
    assert config.keystore_path == Path(".aim-node/custom-keystore.json")
    assert config.data_dir == Path(".aim-node/state")
    assert config.market_api_url == "https://market.example/api"
    assert config.market_ws_url == "wss://market.example/ws"
    assert config.reconnect_delay_s == 2.5
    assert config.reconnect_max_delay_s == 25.0
    assert config.reconnect_jitter == 0.1
    assert config.api_key == "api-key-123"


def test_load_adapter_config_from_toml(tmp_path: Path) -> None:
    config_path = tmp_path / "aim-node.toml"
    config_path.write_text(
        """
[core]
node_serial = "node-abc"

[provider.adapter]
endpoint_url = "http://127.0.0.1:9000/invoke"
health_check_url = "http://127.0.0.1:9000/health"
timeout_seconds = 45
max_concurrent = 12
max_body_bytes = 65536
input_path = "$.payload"
wrap_key = "input"
output_path = "$.result"
""".strip(),
        encoding="utf-8",
    )

    with config_path.open("rb") as handle:
        raw = tomli.load(handle)

    adapter_config = load_adapter_config(raw)

    assert adapter_config.endpoint_url == "http://127.0.0.1:9000/invoke"
    assert adapter_config.health_check_url == "http://127.0.0.1:9000/health"
    assert adapter_config.timeout_seconds == 45
    assert adapter_config.max_concurrent == 12
    assert adapter_config.max_body_bytes == 65536
    assert adapter_config.input_path == "$.payload"
    assert adapter_config.wrap_key == "input"
    assert adapter_config.output_path == "$.result"


def test_serve_default_host_is_loopback(monkeypatch, tmp_path: Path) -> None:
    runner = CliRunner()
    seen: dict[str, object] = {}

    def fake_create_management_app(data_dir: Path, *, remote_bind: bool = False):
        seen["data_dir"] = data_dir
        seen["remote_bind"] = remote_bind
        return SimpleNamespace()

    def fake_run(app, *, host: str, port: int):
        seen["app"] = app
        seen["host"] = host
        seen["port"] = port

    monkeypatch.setattr("aim_node.management.app.create_management_app", fake_create_management_app)
    monkeypatch.setattr("uvicorn.run", fake_run)

    result = runner.invoke(main, ["serve", "--data-dir", str(tmp_path)])

    assert result.exit_code == 0
    assert seen["data_dir"] == tmp_path
    assert seen["remote_bind"] is False
    assert seen["host"] == "127.0.0.1"
    assert seen["port"] == 8401
