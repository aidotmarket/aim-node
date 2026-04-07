from __future__ import annotations

import asyncio
import hashlib
import signal
from contextlib import suppress
from pathlib import Path

import click
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ed25519

try:
    import tomli
except ModuleNotFoundError:  # pragma: no cover
    import tomllib as tomli

from aim_node.config_loader import generate_default_config, load_adapter_config, load_config
from aim_node.consumer.proxy import LocalProxy
from aim_node.consumer.session_manager import SessionManager
from aim_node.core.crypto import DeviceCrypto
from aim_node.core.market_client import MarketClient
from aim_node.core.trust_channel import TrustChannelClient
from aim_node.provider.adapter import HttpJsonAdapter
from aim_node.provider.session_handler import ProviderSessionHandler


def _build_core_config(ctx: click.Context):
    try:
        return load_config(ctx.obj["raw_config"])
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _build_adapter_config(ctx: click.Context):
    try:
        return load_adapter_config(ctx.obj["raw_config"])
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _fingerprint_public_key(public_key: ed25519.Ed25519PublicKey) -> str:
    key_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(key_bytes).hexdigest()


def _install_signal_handlers(stop_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()

    def _request_stop() -> None:
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(sig, _request_stop)


async def _wait_for_shutdown_signal() -> None:
    stop_event = asyncio.Event()
    _install_signal_handlers(stop_event)
    await stop_event.wait()


async def _run_provider_command(ctx: click.Context, passphrase: str) -> None:
    config = _build_core_config(ctx)
    adapter_config = _build_adapter_config(ctx)

    crypto = DeviceCrypto(config, passphrase=passphrase)
    crypto.get_or_create_keypairs()
    trust_channel = TrustChannelClient(config)
    adapter = HttpJsonAdapter(adapter_config)
    handler = ProviderSessionHandler(config, adapter, trust_channel)
    trust_task: asyncio.Task[None] | None = None

    try:
        trust_task = asyncio.create_task(trust_channel.run())
        await handler.start()
        click.echo(f"Provider running for node {config.node_serial}")
        await _wait_for_shutdown_signal()
    finally:
        await handler.stop()
        await adapter.stop()
        await trust_channel.stop()
        if trust_task is not None:
            with suppress(asyncio.CancelledError):
                await trust_task


async def _shutdown_consumer_sessions(session_manager: SessionManager) -> None:
    session_ids = list(session_manager._sessions)
    for session_id in session_ids:
        with suppress(Exception):
            await session_manager.close_session(session_id)


async def _run_consumer_command(ctx: click.Context, passphrase: str) -> None:
    config = _build_core_config(ctx)

    crypto = DeviceCrypto(config, passphrase=passphrase)
    crypto.get_or_create_keypairs()
    market_client = MarketClient(config)
    session_manager = SessionManager(config, market_client)
    proxy = LocalProxy(config, session_manager)

    try:
        await proxy.start()
        click.echo(f"Consumer proxy running on http://127.0.0.1:8400 for node {config.node_serial}")
        await _wait_for_shutdown_signal()
    finally:
        await proxy.stop()
        await _shutdown_consumer_sessions(session_manager)


@click.group()
@click.option("--config", "-c", default="aim-node.toml", help="Config file path")
@click.pass_context
def main(ctx: click.Context, config: str) -> None:
    """AIM Node — Universal AIM client for sellers and buyers."""
    ctx.ensure_object(dict)
    config_path = Path(config)
    if config_path.exists():
        with config_path.open("rb") as handle:
            ctx.obj["raw_config"] = tomli.load(handle)
    else:
        ctx.obj["raw_config"] = {}
    ctx.obj["config_path"] = config_path


@main.command()
@click.pass_context
def provider(ctx: click.Context) -> None:
    """Run AIM Node in provider (seller) mode."""
    passphrase = click.prompt("Keystore passphrase", hide_input=True, default="", show_default=False)
    try:
        asyncio.run(_run_provider_command(ctx, passphrase))
    except KeyboardInterrupt:
        pass


@main.command()
@click.pass_context
def consumer(ctx: click.Context) -> None:
    """Run AIM Node in consumer (buyer) mode."""
    passphrase = click.prompt("Keystore passphrase", hide_input=True, default="", show_default=False)
    try:
        asyncio.run(_run_consumer_command(ctx, passphrase))
    except KeyboardInterrupt:
        pass


@main.command()
@click.option("--passphrase", prompt=True, hide_input=True)
def init(passphrase: str) -> None:
    """Initialize AIM Node: generate keypair, create config template."""
    config_path = Path("aim-node.toml")
    data_dir = Path(".aim-node")
    keystore_path = data_dir / "keystore.json"

    bootstrap_config = load_config(
        {
            "core": {
                "node_serial": "pending-node-id",
                "keystore_path": str(keystore_path),
                "data_dir": str(data_dir),
            }
        }
    )
    crypto = DeviceCrypto(bootstrap_config, passphrase=passphrase)
    _, ed_pub, _, _ = crypto.get_or_create_keypairs()
    node_id = _fingerprint_public_key(ed_pub)

    if not config_path.exists():
        template = generate_default_config().replace("__NODE_SERIAL__", node_id)
        config_path.write_text(template, encoding="utf-8")

    click.echo(f"Initialized AIM Node: {node_id}")
    click.echo(f"Keystore: {keystore_path}")
    click.echo(f"Config: {config_path}")


@main.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show node status: identity, active sessions, health."""
    core_config = _build_core_config(ctx)
    click.echo(f"node_serial: {core_config.node_serial}")
    click.echo(f"keystore_path: {core_config.keystore_path}")
    click.echo(f"data_dir: {core_config.data_dir}")
    click.echo(f"market_api_url: {core_config.market_api_url}")
    click.echo(f"market_ws_url: {core_config.market_ws_url}")
    click.echo(f"api_key_configured: {'yes' if core_config.api_key else 'no'}")
