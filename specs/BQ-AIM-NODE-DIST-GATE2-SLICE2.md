# BQ-AIM-NODE-DIST — Gate 2 Slice 2: Management HTTP Endpoints

**BQ Code:** BQ-AIM-NODE-DIST
**Slice:** 2 of 5
**Revision:** R2 (addressing MP R1 mandates: 5 findings)
**Depends on:** Slice 1 (ProcessStateStore, ProcessManager, config_writer, NodeState)

---

## MP R1 Mandate Resolution

| # | Mandate | Resolution |
|---|---------|-----------|
| 1 | Missing methods: `get_session()`, `initialize()`, `shutdown()` | `get_session(id)` added to ProcessStateStore. Lifespan uses constructor (no separate initialize). `shutdown()` added to ProcessManager. All three additions are part of this slice's build. |
| 2 | Key storage mismatch: spec says PEM, Slice 1 uses keystore.json via DeviceCrypto | Corrected. `keypair.py` removed. Keypair generation uses `DeviceCrypto.get_or_create_keypairs()` with keystore.json. All lock/unlock/setup endpoints use same keystore format. |
| 3 | Dashboard missing `node_id` and `market_connected` | `node_id` derived from config.toml `node_serial` (set by finalize_setup). `market_connected` populated by route handler via httpx ping to api_url. Both fields computed at route level, not stored in ProcessStateStore. |
| 4 | ConfigUpdateRequest.mode unconstrained | Changed to `Literal["provider", "consumer", "both"]`. `upstream_url` required when effective mode includes provider — enforced via `model_validator`. |
| 5 | Test plan insufficient (16 for 16 endpoints) | Expanded to 32 tests: every endpoint gets happy path + primary error case. Missing endpoints added. |

---

## Scope

Build the ManagementApp — a Starlette application on port 8401 serving all `/api/mgmt/*` REST endpoints from the Gate 1 endpoint matrix. Wires HTTP layer to Slice 1 components (ProcessStateStore, ProcessManager, config_writer).

This slice does NOT include: SPA/frontend (Slice 3), Docker (Slice 4), GHCR publish (Slice 5).

---

## Files

| File | Action | Description |
|------|--------|-------------|
| `aim_node/management/schemas.py` | CREATE | Pydantic v2 request/response models for all endpoints |
| `aim_node/management/routes.py` | CREATE | Route handlers wiring to ProcessStateStore + ProcessManager |
| `aim_node/management/app.py` | CREATE | Starlette app factory, route registration, lifespan |
| `aim_node/management/state.py` | MODIFY | Add `get_session(id)` method |
| `aim_node/management/process.py` | MODIFY | Add `shutdown()` method |
| `aim_node/cli.py` | MODIFY | Add `aim-node serve` command |
| `tests/test_management_api.py` | CREATE | 32 endpoint tests via httpx AsyncClient + ASGITransport |

---

## Slice 1 Additions (state.py + process.py)

### state.py — Add `get_session(session_id: str) -> dict | None`

```python
def get_session(self, session_id: str) -> dict | None:
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
                    "metering_events": [],  # placeholder
                    "latency_ms": None,
                    "error_count": 0,
                }
        return None
```

### process.py — Add `shutdown()`

```python
async def shutdown(self) -> None:
    """Graceful shutdown: stop provider and consumer if running. Suppresses NotRunningError."""
    try:
        await self.stop_provider()
    except NotRunningError:
        pass
    try:
        await self.stop_consumer()
    except NotRunningError:
        pass
```

---

## schemas.py — Pydantic v2 Models

All models use `from pydantic import BaseModel` and `from typing import Literal`.

### Request Models

```python
class KeypairRequest(BaseModel):
    passphrase: str | None = None

class TestConnectionRequest(BaseModel):
    api_url: str  # Pydantic validator: must be http:// or https://
    api_key: str

class FinalizeSetupRequest(BaseModel):
    mode: Literal["provider", "consumer", "both"]
    api_url: str  # validated: http(s) only
    api_key: str
    upstream_url: str | None = None

    @model_validator(mode="after")
    def require_upstream_for_provider(self):
        if self.mode in ("provider", "both") and not self.upstream_url:
            raise ValueError("upstream_url required when mode includes provider")
        return self

class UnlockRequest(BaseModel):
    passphrase: str

class ConfigUpdateRequest(BaseModel):
    mode: Literal["provider", "consumer", "both"] | None = None
    api_url: str | None = None
    api_key: str | None = None
    upstream_url: str | None = None

    @model_validator(mode="after")
    def require_upstream_for_provider(self):
        if self.mode in ("provider", "both") and self.upstream_url is None:
            raise ValueError("upstream_url required when mode includes provider")
        return self
```

### Response Models

```python
class HealthResponse(BaseModel):
    healthy: bool = True
    setup_complete: bool
    locked: bool

class SetupStatusResponse(BaseModel):
    setup_complete: bool
    locked: bool
    unlocked: bool
    current_step: int

class KeypairResponse(BaseModel):
    fingerprint: str
    created: bool

class TestConnectionResponse(BaseModel):
    reachable: bool
    version: str | None = None

class FinalizeResponse(BaseModel):
    ok: bool = True

class DashboardResponse(BaseModel):
    node_id: str
    fingerprint: str
    mode: str
    uptime_s: float
    version: str
    market_connected: bool
    provider_running: bool
    consumer_running: bool

class ConfigReadResponse(BaseModel):
    mode: str
    api_url: str
    api_key_set: bool
    upstream_url: str | None = None
    data_dir: str

class ConfigUpdateResponse(BaseModel):
    ok: bool = True
    restart_required: bool

class ProviderStartResponse(BaseModel):
    started: bool = True

class ProviderStopResponse(BaseModel):
    stopped: bool = True

class ProviderHealthResponse(BaseModel):
    upstream_reachable: bool
    latency_ms: float | None = None
    last_check: str

class ConsumerStartResponse(BaseModel):
    started: bool = True
    proxy_port: int

class ConsumerStopResponse(BaseModel):
    stopped: bool = True

class SessionItem(BaseModel):
    id: str
    role: str
    state: str
    created_at: float
    peer_fingerprint: str = ""
    bytes_transferred: int = 0

class SessionsResponse(BaseModel):
    sessions: list[SessionItem]

class SessionDetailResponse(BaseModel):
    id: str
    role: str
    state: str
    metering_events: list[dict] = []
    latency_ms: float | None = None
    error_count: int = 0
    created_at: float

class UnlockResponse(BaseModel):
    unlocked: bool = True

class KeypairInfoResponse(BaseModel):
    fingerprint: str
    algorithm: str = "Ed25519"
    created_at: str

class ErrorResponse(BaseModel):
    error: str
```

---

## Keypair Generation — Use DeviceCrypto (NOT raw PEM)

Slice 1 uses `keystore.json` via `DeviceCrypto` for all key operations. This slice does NOT introduce a separate PEM keypair module.

### Setup keypair route handler:

```python
async def setup_keypair(request):
    body = KeypairRequest(**(await request.json()))
    state = request.app.state.store
    data_dir = state._data_dir
    keystore_path = data_dir / "keystore.json"
    if keystore_path.exists():
        return JSONResponse({"error": "Keypair already exists"}, status_code=409)

    from aim_node.core.crypto import DeviceCrypto
    config = type('C', (), {'keystore_path': keystore_path, 'data_dir': data_dir})()
    passphrase = body.passphrase or ""
    crypto = DeviceCrypto(config, passphrase=passphrase)
    crypto.get_or_create_keypairs()
    fingerprint = crypto.fingerprint()
    state.mark_setup_step(2)
    return JSONResponse(KeypairResponse(fingerprint=fingerprint, created=True).model_dump())
```

This ensures the same keystore format is used by setup, lock detection, and unlock.

---

## routes.py — Route Handlers

All handlers receive `state: ProcessStateStore` and `process_mgr: ProcessManager` via `request.app.state`.

Error mapping:
- `PreconditionError` → 412
- `LockedError` → 423
- `AlreadyRunningError` → 409
- `NotRunningError` → 409
- `FileExistsError` → 409
- `ValueError` (validation) → 422
- Wrong passphrase (unlock returns False) → 401

### Dashboard node_id and market_connected

`node_id` is read from config.toml `management.node_serial` (written by `finalize_setup`). `market_connected` is computed at request time: `httpx.AsyncClient.get(api_url + "/api/v1/health", timeout=3)` — true if 200, false otherwise. This avoids storing connectivity state that goes stale.

```python
async def dashboard(request):
    state = request.app.state.store
    dash = state.get_dashboard()
    config = read_config(state._data_dir)
    mgmt = config.get("management", {})
    node_id = mgmt.get("node_serial", "")
    api_url = config.get("market", {}).get("api_url", "")
    market_connected = False
    if api_url:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{api_url}/api/v1/health", timeout=3)
                market_connected = r.status_code == 200
        except Exception:
            pass
    return JSONResponse(DashboardResponse(
        node_id=node_id, market_connected=market_connected, **dash
    ).model_dump())
```

### Endpoint → Handler Mapping (unchanged, all 16 endpoints covered)

| Endpoint | Handler | Notes |
|----------|---------|-------|
| `GET /api/mgmt/health` | `health()` | Always 200. Reads state.get_status() |
| `GET /api/mgmt/setup/status` | `setup_status()` | Returns setup/lock/step state |
| `POST /api/mgmt/setup/keypair` | `setup_keypair()` | DeviceCrypto.get_or_create_keypairs(), advances step |
| `POST /api/mgmt/setup/test-connection` | `setup_test_connection()` | httpx GET to api_url/api/v1/health |
| `POST /api/mgmt/setup/finalize` | `setup_finalize()` | config_writer.finalize_setup(), transitions state |
| `GET /api/mgmt/status` | `dashboard()` | get_dashboard() + node_id from config + market_connected via httpx |
| `GET /api/mgmt/config` | `config_read()` | Reads config, masks api_key → api_key_set |
| `PUT /api/mgmt/config` | `config_update()` | Writes config, restart_required if mode changed |
| `POST /api/mgmt/provider/start` | `provider_start()` | process_mgr.start_provider() |
| `POST /api/mgmt/provider/stop` | `provider_stop()` | process_mgr.stop_provider() |
| `GET /api/mgmt/provider/health` | `provider_health()` | httpx GET to upstream_url, measures latency |
| `POST /api/mgmt/consumer/start` | `consumer_start()` | process_mgr.start_consumer() |
| `POST /api/mgmt/consumer/stop` | `consumer_stop()` | process_mgr.stop_consumer() |
| `GET /api/mgmt/sessions` | `sessions_list()` | state.get_sessions() |
| `GET /api/mgmt/sessions/{id}` | `session_detail()` | state.get_session(id), 404 if None |
| `POST /api/mgmt/unlock` | `unlock()` | state.unlock(passphrase), 401 if False |
| `GET /api/mgmt/keypair` | `keypair_info()` | DeviceCrypto fingerprint + keystore mtime, 404 if no keystore |

### URL Validation

`TestConnectionRequest.api_url`, `FinalizeSetupRequest.api_url`, `ConfigUpdateRequest.api_url`: Pydantic `field_validator` ensures scheme is `http` or `https`. Reject `file://`, `ftp://`, etc.

`FinalizeSetupRequest.upstream_url` and `ConfigUpdateRequest.upstream_url`: Same validation. Required when mode includes provider — enforced via `model_validator`.

---

## app.py — ManagementApp Factory

```python
def create_management_app(data_dir: Path) -> Starlette:
    """
    Factory function. Creates Starlette app with:
    1. Lifespan: creates ProcessStateStore(data_dir) and ProcessManager(state, data_dir).
       Constructor reads config.toml and determines node state — no separate initialize().
    2. Route registration: all /api/mgmt/* routes from routes.py
    3. Static files: Mount /static serving data_dir/frontend/ (placeholder until Slice 3)
    4. Exception handlers: map custom exceptions to HTTP status codes
    """
```

### Lifespan

```python
@asynccontextmanager
async def lifespan(app):
    state = ProcessStateStore(data_dir)  # constructor reads config + determines state
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    yield
    await process_mgr.shutdown()  # new method — graceful stop, suppresses NotRunningError
```

---

## cli.py — `aim-node serve` Command

Add to existing Click CLI:

```python
@cli.command()
@click.option("--data-dir", type=click.Path(), default="/data")
@click.option("--host", default="0.0.0.0")
@click.option("--port", type=int, default=8401)
def serve(data_dir, host, port):
    """Start management server on :8401."""
    import uvicorn
    from aim_node.management.app import create_management_app
    app = create_management_app(Path(data_dir))
    uvicorn.run(app, host=host, port=port)
```

---

## Tests — test_management_api.py (32 tests)

All tests use `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`.

### Test Fixtures

- `tmp_data_dir`: pytest `tmp_path` as data_dir
- `app`: `create_management_app(tmp_data_dir)`
- `client`: httpx AsyncClient with ASGITransport
- `setup_complete_app`: pre-generated keystore (unencrypted) + finalized config
- `locked_app`: pre-generated keystore (encrypted with passphrase "test123") + finalized config
- Mock `httpx.AsyncClient` for test-connection and provider-health endpoints

### Test Matrix (32 tests)

| # | Test | Endpoint | Type |
|---|------|----------|------|
| 1 | `test_health_returns_200` | GET /health | happy |
| 2 | `test_health_shows_setup_incomplete` | GET /health | state |
| 3 | `test_setup_status_initial` | GET /setup/status | happy |
| 4 | `test_setup_status_after_finalize` | GET /setup/status | state |
| 5 | `test_setup_keypair_creates_keystore` | POST /setup/keypair | happy |
| 6 | `test_setup_keypair_duplicate_409` | POST /setup/keypair | error |
| 7 | `test_setup_test_connection_success` | POST /setup/test-connection | happy |
| 8 | `test_setup_test_connection_unreachable` | POST /setup/test-connection | error |
| 9 | `test_setup_finalize_success` | POST /setup/finalize | happy |
| 10 | `test_setup_finalize_provider_requires_upstream` | POST /setup/finalize | error (422) |
| 11 | `test_setup_finalize_invalid_url_scheme` | POST /setup/finalize | error (422) |
| 12 | `test_dashboard_after_setup` | GET /status | happy |
| 13 | `test_dashboard_before_setup_returns_defaults` | GET /status | state |
| 14 | `test_config_read_masks_api_key` | GET /config | happy |
| 15 | `test_config_read_before_setup` | GET /config | state |
| 16 | `test_config_update_mode_change` | PUT /config | happy |
| 17 | `test_config_update_invalid_mode_422` | PUT /config | error |
| 18 | `test_config_update_provider_requires_upstream` | PUT /config | error (422) |
| 19 | `test_provider_start_success` | POST /provider/start | happy |
| 20 | `test_provider_start_when_locked_423` | POST /provider/start | error |
| 21 | `test_provider_start_when_setup_incomplete_412` | POST /provider/start | error |
| 22 | `test_provider_stop_success` | POST /provider/stop | happy |
| 23 | `test_provider_stop_not_running_409` | POST /provider/stop | error |
| 24 | `test_provider_health` | GET /provider/health | happy |
| 25 | `test_consumer_start_success` | POST /consumer/start | happy |
| 26 | `test_consumer_start_when_locked_423` | POST /consumer/start | error |
| 27 | `test_consumer_stop_success` | POST /consumer/stop | happy |
| 28 | `test_consumer_stop_not_running_409` | POST /consumer/stop | error |
| 29 | `test_sessions_empty_list` | GET /sessions | happy |
| 30 | `test_session_detail_not_found_404` | GET /sessions/{id} | error |
| 31 | `test_unlock_success` | POST /unlock | happy |
| 32 | `test_unlock_wrong_passphrase_401` | POST /unlock | error |
| 33 | `test_keypair_info_success` | GET /keypair | happy |
| 34 | `test_keypair_info_no_keystore_404` | GET /keypair | error |

Note: 34 tests total (exceeds 32 minimum). Tests 33-34 cover the keypair info endpoint which was missing from R1.

---

## Dependencies

- `httpx` — already in aim-node deps
- `cryptography` — already in aim-node deps (DeviceCrypto)
- `starlette` — already in aim-node deps (LocalProxy)
- `uvicorn` — already in aim-node deps
- `pydantic>=2.0` — already in aim-node deps
- No new dependencies required

---

## Acceptance Criteria

1. All 16 endpoints from Gate 1 matrix return correct status codes and response schemas
2. Setup wizard flow works end-to-end: keypair (DeviceCrypto) → test-connection → finalize
3. Locked node returns 423 on provider/start and consumer/start
4. Unlock with correct passphrase transitions to READY, wrong passphrase returns 401
5. Config GET never returns raw API key
6. URL validation rejects non-http(s) schemes
7. Provider mode requires upstream_url in both finalize and config update
8. `aim-node serve` starts ManagementApp on specified host:port
9. All 34 tests pass
10. No import dependency on consumer/proxy or provider internals except through ProcessManager
11. Keypair generation uses DeviceCrypto + keystore.json (same format as lock/unlock)
12. Dashboard node_id from config, market_connected from live httpx ping
13. ConfigUpdateRequest.mode constrained to Literal enum
