"""Route handlers for the management HTTP API."""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Type, TypeVar

import httpx
from cryptography.hazmat.primitives import serialization
from pydantic import BaseModel, ValidationError
from starlette.requests import Request
from starlette.responses import JSONResponse

from aim_node.core.crypto import DeviceCrypto
from aim_node.management.config_writer import finalize_setup, read_config, write_config
from aim_node.management.schemas import (
    ConfigReadResponse,
    ConfigUpdateRequest,
    ConfigUpdateResponse,
    ConsumerStartResponse,
    ConsumerStopResponse,
    DashboardResponse,
    FinalizeResponse,
    FinalizeSetupRequest,
    HealthResponse,
    KeypairInfoResponse,
    KeypairRequest,
    KeypairResponse,
    ProviderHealthResponse,
    ProviderStartResponse,
    ProviderStopResponse,
    SessionDetailResponse,
    SessionItem,
    SessionsResponse,
    SetupStatusResponse,
    TestConnectionRequest,
    TestConnectionResponse,
    UnlockRequest,
    UnlockResponse,
)

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# Indirection so tests can monkeypatch without replacing httpx globally.
_AsyncClient = httpx.AsyncClient


def _crypto_for(data_dir: Path, passphrase: str = "") -> DeviceCrypto:
    keystore_path = data_dir / "keystore.json"
    config = type("C", (), {"keystore_path": keystore_path, "data_dir": data_dir})()
    return DeviceCrypto(config, passphrase=passphrase)


def _fingerprint_from_ed_pub(ed_pub) -> str:
    raw = ed_pub.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return hashlib.sha256(raw).hexdigest()


async def _parse_body(request: Request, model: Type[T]) -> T:
    try:
        data = await request.json()
    except Exception:
        data = {}
    if not isinstance(data, dict):
        data = {}
    return model(**data)


# ---------- Health ----------


async def health(request: Request) -> JSONResponse:
    state = request.app.state.store
    status = state.get_status()
    return JSONResponse(
        HealthResponse(
            healthy=True,
            setup_complete=status["setup_complete"],
            locked=status["locked"],
        ).model_dump()
    )


# ---------- Setup ----------


async def setup_status(request: Request) -> JSONResponse:
    state = request.app.state.store
    status = state.get_status()
    return JSONResponse(
        SetupStatusResponse(
            setup_complete=status["setup_complete"],
            locked=status["locked"],
            unlocked=status["unlocked"],
            current_step=status["current_step"],
        ).model_dump()
    )


async def setup_keypair(request: Request) -> JSONResponse:
    body = await _parse_body(request, KeypairRequest)
    state = request.app.state.store
    data_dir: Path = state._data_dir
    keystore_path = data_dir / "keystore.json"
    if keystore_path.exists():
        return JSONResponse({"error": "Keypair already exists"}, status_code=409)

    passphrase = body.passphrase or ""
    crypto = _crypto_for(data_dir, passphrase=passphrase)
    _, ed_pub, _, _ = crypto.get_or_create_keypairs()
    fingerprint = _fingerprint_from_ed_pub(ed_pub)
    state.mark_setup_step(2)
    return JSONResponse(
        KeypairResponse(fingerprint=fingerprint, created=True).model_dump()
    )


async def setup_test_connection(request: Request) -> JSONResponse:
    body = await _parse_body(request, TestConnectionRequest)
    reachable = False
    version: str | None = None
    try:
        async with _AsyncClient() as client:
            r = await client.get(
                f"{body.api_url}/api/v1/health",
                headers={"Authorization": f"Bearer {body.api_key}"},
                timeout=5,
            )
            reachable = r.status_code == 200
            if reachable:
                try:
                    data = r.json()
                    version = data.get("version") if isinstance(data, dict) else None
                except Exception:
                    version = None
    except Exception:
        reachable = False
    return JSONResponse(
        TestConnectionResponse(reachable=reachable, version=version).model_dump()
    )


async def setup_finalize(request: Request) -> JSONResponse:
    body = await _parse_body(request, FinalizeSetupRequest)
    state = request.app.state.store
    data_dir: Path = state._data_dir
    finalize_setup(
        data_dir=data_dir,
        mode=body.mode,
        api_url=body.api_url,
        api_key=body.api_key,
        upstream_url=body.upstream_url,
    )
    state.mark_setup_complete(body.mode)
    state.determine_node_state()
    return JSONResponse(FinalizeResponse(ok=True).model_dump())


# ---------- Dashboard ----------


async def dashboard(request: Request) -> JSONResponse:
    state = request.app.state.store
    dash = state.get_dashboard()
    data_dir: Path = state._data_dir
    config = read_config(data_dir)
    core = config.get("core", {}) if isinstance(config, dict) else {}
    node_id = core.get("node_serial", "") or ""
    api_url = core.get("market_api_url", "") or ""
    market_connected = False
    if api_url:
        try:
            async with _AsyncClient() as client:
                r = await client.get(f"{api_url}/api/v1/health", timeout=3)
                market_connected = r.status_code == 200
        except Exception:
            market_connected = False
    return JSONResponse(
        DashboardResponse(
            node_id=node_id,
            fingerprint=dash.get("fingerprint") or "",
            mode=dash.get("mode") or "",
            uptime_s=dash.get("uptime_s") or 0.0,
            version=dash.get("version") or "",
            market_connected=market_connected,
            provider_running=bool(dash.get("provider_running")),
            consumer_running=bool(dash.get("consumer_running")),
        ).model_dump()
    )


# ---------- Config ----------


async def config_read(request: Request) -> JSONResponse:
    state = request.app.state.store
    data_dir: Path = state._data_dir
    config = read_config(data_dir)
    core = config.get("core", {}) if isinstance(config, dict) else {}
    mgmt = config.get("management", {}) if isinstance(config, dict) else {}
    provider = config.get("provider", {}) if isinstance(config, dict) else {}
    adapter = provider.get("adapter", {}) if isinstance(provider, dict) else {}
    upstream_url = adapter.get("endpoint_url")
    return JSONResponse(
        ConfigReadResponse(
            mode=mgmt.get("mode") or "",
            api_url=core.get("market_api_url") or "",
            api_key_set=bool(core.get("api_key")),
            upstream_url=upstream_url,
            data_dir=str(data_dir),
        ).model_dump()
    )


async def config_update(request: Request) -> JSONResponse:
    body = await _parse_body(request, ConfigUpdateRequest)
    state = request.app.state.store
    data_dir: Path = state._data_dir
    config = read_config(data_dir)
    if "core" not in config:
        config["core"] = {}
    if "management" not in config:
        config["management"] = {}

    prev_mode = config["management"].get("mode")
    restart_required = False

    if body.mode is not None:
        config["management"]["mode"] = body.mode
        if body.mode != prev_mode:
            restart_required = True
    if body.api_url is not None:
        config["core"]["market_api_url"] = body.api_url
    if body.api_key is not None:
        config["core"]["api_key"] = body.api_key
    if body.upstream_url is not None:
        if "provider" not in config:
            config["provider"] = {}
        if "adapter" not in config["provider"]:
            config["provider"]["adapter"] = {}
        config["provider"]["adapter"]["endpoint_url"] = body.upstream_url

    write_config(data_dir, config)
    # Reflect mode change in state store for dashboard purposes
    if body.mode is not None:
        state._mode = body.mode

    return JSONResponse(
        ConfigUpdateResponse(ok=True, restart_required=restart_required).model_dump()
    )


# ---------- Provider ----------


async def provider_start(request: Request) -> JSONResponse:
    process_mgr = request.app.state.process_mgr
    await process_mgr.start_provider()
    return JSONResponse(ProviderStartResponse(started=True).model_dump())


async def provider_stop(request: Request) -> JSONResponse:
    process_mgr = request.app.state.process_mgr
    await process_mgr.stop_provider()
    return JSONResponse(ProviderStopResponse(stopped=True).model_dump())


async def provider_health(request: Request) -> JSONResponse:
    state = request.app.state.store
    data_dir: Path = state._data_dir
    config = read_config(data_dir)
    provider = config.get("provider", {}) if isinstance(config, dict) else {}
    adapter = provider.get("adapter", {}) if isinstance(provider, dict) else {}
    upstream_url = adapter.get("endpoint_url")

    upstream_reachable = False
    latency_ms: float | None = None
    if upstream_url:
        try:
            async with _AsyncClient() as client:
                start = time.monotonic()
                r = await client.get(upstream_url, timeout=3)
                latency_ms = (time.monotonic() - start) * 1000.0
                upstream_reachable = 200 <= r.status_code < 500
        except Exception:
            upstream_reachable = False
            latency_ms = None

    return JSONResponse(
        ProviderHealthResponse(
            upstream_reachable=upstream_reachable,
            latency_ms=latency_ms,
            last_check=datetime.now(timezone.utc).isoformat(),
        ).model_dump()
    )


# ---------- Consumer ----------


async def consumer_start(request: Request) -> JSONResponse:
    process_mgr = request.app.state.process_mgr
    port = await process_mgr.start_consumer()
    return JSONResponse(
        ConsumerStartResponse(started=True, proxy_port=port).model_dump()
    )


async def consumer_stop(request: Request) -> JSONResponse:
    process_mgr = request.app.state.process_mgr
    await process_mgr.stop_consumer()
    return JSONResponse(ConsumerStopResponse(stopped=True).model_dump())


# ---------- Sessions ----------


async def sessions_list(request: Request) -> JSONResponse:
    state = request.app.state.store
    raw = state.get_sessions()
    items = [SessionItem(**s) for s in raw]
    return JSONResponse(SessionsResponse(sessions=items).model_dump())


async def session_detail(request: Request) -> JSONResponse:
    state = request.app.state.store
    session_id = request.path_params.get("session_id", "")
    session = state.get_session(session_id)
    if session is None:
        return JSONResponse({"error": "Session not found"}, status_code=404)
    return JSONResponse(
        SessionDetailResponse(
            id=session["id"],
            role=session["role"],
            state=session["state"],
            metering_events=session.get("metering_events") or [],
            latency_ms=session.get("latency_ms"),
            error_count=session.get("error_count") or 0,
            created_at=session["created_at"],
        ).model_dump()
    )


# ---------- Unlock ----------


async def unlock(request: Request) -> JSONResponse:
    body = await _parse_body(request, UnlockRequest)
    state = request.app.state.store
    ok = state.unlock(body.passphrase)
    if not ok:
        return JSONResponse({"error": "Invalid passphrase"}, status_code=401)
    return JSONResponse(UnlockResponse(unlocked=True).model_dump())


# ---------- Keypair Info ----------


async def keypair_info(request: Request) -> JSONResponse:
    state = request.app.state.store
    data_dir: Path = state._data_dir
    keystore_path = data_dir / "keystore.json"
    if not keystore_path.exists():
        return JSONResponse({"error": "Keystore not found"}, status_code=404)

    passphrase = state.get_passphrase() or ""
    try:
        crypto = _crypto_for(data_dir, passphrase=passphrase)
        _, ed_pub, _, _ = crypto.get_or_create_keypairs()
        fingerprint = _fingerprint_from_ed_pub(ed_pub)
    except Exception:
        # Locked — read public key directly from keystore without decrypting private
        import json

        with keystore_path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        hex_pub = data.get("ed25519_public_key", "")
        if hex_pub:
            fingerprint = hashlib.sha256(bytes.fromhex(hex_pub)).hexdigest()
        else:
            return JSONResponse({"error": "Keystore corrupted"}, status_code=500)

    mtime = keystore_path.stat().st_mtime
    created_at = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat()
    return JSONResponse(
        KeypairInfoResponse(
            fingerprint=fingerprint,
            algorithm="Ed25519",
            created_at=created_at,
        ).model_dump()
    )
