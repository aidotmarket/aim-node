# BQ-AIM-NODE-DIST — Gate 2 Slice 2: Management HTTP Endpoints

**BQ Code:** BQ-AIM-NODE-DIST
**Slice:** 2 of 5
**Revision:** R1
**Depends on:** Slice 1 (ProcessStateStore, ProcessManager, config_writer, NodeState)

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
| `aim_node/management/keypair.py` | CREATE | Ed25519 keypair generation + fingerprint utilities |
| `aim_node/cli.py` | MODIFY | Add `aim-node serve` command |
| `tests/test_management_api.py` | CREATE | 16+ endpoint tests via Starlette TestClient |

---

## schemas.py — Pydantic v2 Models

All models use `from pydantic import BaseModel, SecretStr`.

### Request Models

```python
class KeypairRequest(BaseModel):
    passphrase: str | None = None

class TestConnectionRequest(BaseModel):
    api_url: str  # must be http:// or https://
    api_key: str

class FinalizeSetupRequest(BaseModel):
    mode: Literal["provider", "consumer", "both"]
    api_url: str
    api_key: str
    upstream_url: str | None = None  # required when mode includes provider

class UnlockRequest(BaseModel):
    passphrase: str

class ConfigUpdateRequest(BaseModel):
    mode: str | None = None
    api_url: str | None = None
    api_key: str | None = None
    upstream_url: str | None = None
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

## keypair.py — Ed25519 Keypair Utilities

```python
def generate_keypair(data_dir: Path, passphrase: str | None = None) -> str:
    """Generate Ed25519 keypair, save to data_dir/keys/, return SHA-256 fingerprint.
    
    - Creates data_dir/keys/ if missing
    - Private key: PEM format, optionally encrypted with passphrase (BestAvailableEncryption)
    - Public key: PEM format
    - File permissions: 0o600 private, 0o644 public
    - Returns hex SHA-256 fingerprint of public key bytes
    - Raises FileExistsError if keys already exist (409 at route layer)
    """

def get_fingerprint(data_dir: Path) -> str | None:
    """Read public key, return SHA-256 hex fingerprint. None if no keypair."""

def get_keypair_created_at(data_dir: Path) -> str | None:
    """Return ISO 8601 creation timestamp of public key file. None if missing."""

def is_key_encrypted(data_dir: Path) -> bool:
    """Check if private key is encrypted (needs passphrase to load)."""
```

Uses `cryptography` library (already a dependency via aim-node core crypto).

---

## routes.py — Route Handlers

All handlers receive `state: ProcessStateStore` and `process_mgr: ProcessManager` via Starlette app state (set during lifespan).

Error mapping:
- `PreconditionError` → 412
- `LockedError` → 423  
- `AlreadyRunningError` → 409
- `NotRunningError` → 409
- `FileExistsError` → 409
- `ValueError` (validation) → 422
- Wrong passphrase → 401

### Endpoint → Handler Mapping

| Endpoint | Handler | Notes |
|----------|---------|-------|
| `GET /api/mgmt/health` | `health()` | Always 200. Reads state.get_status() |
| `GET /api/mgmt/setup/status` | `setup_status()` | Returns setup/lock/step state |
| `POST /api/mgmt/setup/keypair` | `setup_keypair()` | Calls keypair.generate_keypair(), advances setup step |
| `POST /api/mgmt/setup/test-connection` | `setup_test_connection()` | httpx.AsyncClient GET to api_url/api/v1/health |
| `POST /api/mgmt/setup/finalize` | `setup_finalize()` | Calls config_writer.finalize_setup(), transitions state to READY or LOCKED |
| `GET /api/mgmt/status` | `dashboard()` | Calls state.get_dashboard() |
| `GET /api/mgmt/config` | `config_read()` | Reads config, masks api_key → api_key_set |
| `PUT /api/mgmt/config` | `config_update()` | Writes config, returns restart_required=true if mode changed |
| `POST /api/mgmt/provider/start` | `provider_start()` | Calls process_mgr.start_provider() |
| `POST /api/mgmt/provider/stop` | `provider_stop()` | Calls process_mgr.stop_provider() |
| `GET /api/mgmt/provider/health` | `provider_health()` | httpx GET to upstream_url, measures latency |
| `POST /api/mgmt/consumer/start` | `consumer_start()` | Calls process_mgr.start_consumer() |
| `POST /api/mgmt/consumer/stop` | `consumer_stop()` | Calls process_mgr.stop_consumer() |
| `GET /api/mgmt/sessions` | `sessions_list()` | Calls state.get_sessions() |
| `GET /api/mgmt/sessions/{id}` | `session_detail()` | Calls state.get_session(id), 404 if missing |
| `POST /api/mgmt/unlock` | `unlock()` | Calls state.unlock(passphrase), 401 on failure |
| `GET /api/mgmt/keypair` | `keypair_info()` | Calls keypair utils, 404 if no keypair |

### URL Validation

`TestConnectionRequest.api_url` and `FinalizeSetupRequest.api_url`: Pydantic validator ensures scheme is `http` or `https`. Reject `file://`, `ftp://`, etc.

`FinalizeSetupRequest.upstream_url`: Same validation. Required when `mode` is `"provider"` or `"both"` — Pydantic `model_validator` enforces this.

---

## app.py — ManagementApp Factory

```python
def create_management_app(data_dir: Path) -> Starlette:
    """
    Factory function. Creates Starlette app with:
    1. Lifespan: initializes ProcessStateStore(data_dir) + ProcessManager(state, data_dir)
       and stores on app.state
    2. Route registration: all /api/mgmt/* routes from routes.py
    3. Static files: Mount /static serving data_dir/frontend/ (placeholder until Slice 3)
    4. Exception handlers: map custom exceptions to HTTP status codes
    """
```

### Lifespan

```python
@asynccontextmanager
async def lifespan(app):
    state = ProcessStateStore(data_dir)
    state.initialize()  # reads config.toml, checks key encryption
    process_mgr = ProcessManager(state, data_dir)
    app.state.store = state
    app.state.process_mgr = process_mgr
    yield
    # Shutdown: stop provider/consumer if running
    await process_mgr.shutdown()
```

Note: `ProcessManager.shutdown()` — new method added in this slice. Calls `stop_provider()` + `stop_consumer()` if running, suppressing NotRunningError.

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

## Tests — test_management_api.py

16 tests using `httpx.AsyncClient` + Starlette `TestClient` (or `httpx.ASGITransport`).

### Test List

| # | Test | Validates |
|---|------|-----------|
| 1 | `test_health_returns_200` | GET /health always 200, returns setup_complete + locked |
| 2 | `test_setup_status_initial` | GET /setup/status returns step=0, setup_complete=false |
| 3 | `test_setup_keypair_creates_keys` | POST /setup/keypair → 200, fingerprint returned, files exist |
| 4 | `test_setup_keypair_duplicate_409` | POST /setup/keypair twice → 409 |
| 5 | `test_setup_test_connection_success` | POST /setup/test-connection with mock → reachable=true |
| 6 | `test_setup_finalize_success` | POST /setup/finalize → 200, config.toml written, setup_complete=true |
| 7 | `test_setup_finalize_provider_requires_upstream` | POST /setup/finalize mode=provider no upstream_url → 422 |
| 8 | `test_dashboard_after_setup` | GET /status returns node identity fields |
| 9 | `test_config_read_masks_api_key` | GET /config returns api_key_set=true, no raw key |
| 10 | `test_config_update` | PUT /config mode change → restart_required=true |
| 11 | `test_provider_start_when_locked_423` | POST /provider/start when locked → 423 |
| 12 | `test_provider_start_when_setup_incomplete_412` | POST /provider/start before setup → 412 |
| 13 | `test_consumer_start_stop` | POST /consumer/start → 200, POST /consumer/stop → 200 |
| 14 | `test_unlock_success` | POST /unlock correct passphrase → 200 |
| 15 | `test_unlock_wrong_passphrase_401` | POST /unlock wrong passphrase → 401 |
| 16 | `test_sessions_empty_list` | GET /sessions → empty list |

### Test Fixtures

- `tmp_data_dir`: pytest `tmp_path` as data_dir
- `app`: `create_management_app(tmp_data_dir)` 
- `client`: `httpx.AsyncClient(transport=httpx.ASGITransport(app=app))`
- Mock `httpx.AsyncClient` for test-connection endpoint (don't hit real ai.market)
- For locked-state tests: pre-generate encrypted keypair + finalize setup in fixture

---

## Dependencies

- `httpx` — already in aim-node deps (used by market_client)
- `cryptography` — already in aim-node deps (used by core crypto)
- `starlette` — already in aim-node deps (used by LocalProxy)
- `uvicorn` — already in aim-node deps
- `pydantic>=2.0` — already in aim-node deps
- No new dependencies required

---

## Acceptance Criteria

1. All 16 endpoints from Gate 1 matrix return correct status codes and response schemas
2. Setup wizard flow works end-to-end: keypair → test-connection → finalize
3. Locked node returns 423 on provider/start and consumer/start
4. Unlock with correct passphrase transitions to READY, wrong passphrase returns 401
5. Config GET never returns raw API key
6. URL validation rejects non-http(s) schemes
7. Provider mode requires upstream_url in finalize
8. `aim-node serve` starts ManagementApp on specified host:port
9. All 16 tests pass
10. No import dependency on consumer/proxy or provider internals except through ProcessManager
