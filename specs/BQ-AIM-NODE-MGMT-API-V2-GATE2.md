# BQ-AIM-NODE-MGMT-API-V2 — Gate 2 Spec
## Implementation: Local Extensions for AIM Node UI

**BQ Code:** BQ-AIM-NODE-MGMT-API-V2
**Epic:** AIM-NODE-UI
**Phase:** 2 — Implementation
**Prerequisite:** Gate 1 approved (S432), BQ-AIM-NODE-CONTRACTS Gate 4 complete
**Author:** Vulcan (S435)

---

## Scope Reconciliation

Gate 1 defined 6 build slices. Contracts BQ (completed Gate 4 in S434) already delivered:

| Gate 1 Slice | Status | Evidence |
|---|---|---|
| Slice A: Security hardening (loopback, CSRF, origin, session token, error normalization) | **COMPLETE** | `middleware.py` (CSRFMiddleware), `errors.py` (19 codes), `cli.py:188` (127.0.0.1 default), `app.py` (exception handlers) |
| Slice E: Marketplace facade (14 proxy endpoints + caching) | **COMPLETE** | `marketplace.py` (14 handlers), `facade.py` (MarketplaceFacade with cache), `app.py` (31 routes mounted) |

**Remaining scope: 4 slices (Gate 1 Slices B, C, D, F renumbered A–D below).**

---

## Codebase Baseline

```
aim_node/
├── management/
│   ├── app.py          — Starlette factory, 31 routes, exception handlers
│   ├── routes.py       — 17 core mgmt handlers (health, setup, dashboard, config, provider, consumer, sessions, unlock, keypair)
│   ├── marketplace.py  — 14 marketplace proxy handlers
│   ├── facade.py       — MarketplaceFacade (HTTP client + auth + cache)
│   ├── middleware.py    — CSRFMiddleware (CSRF + origin + session token)
│   ├── errors.py       — ErrorCode (19 codes), NormalizedError, make_error()
│   ├── schemas.py      — Pydantic request/response models
│   ├── state.py        — ProcessStateStore (JSON persistence)
│   ├── process.py      — ProcessManager (provider/consumer lifecycle)
│   └── config_writer.py — Config R/W helpers
├── core/
│   ├── config.py       — AIMCoreConfig
│   ├── market_client.py — MarketClient (HTTP to api.ai.market)
│   ├── auth.py         — AuthService (API key → Bearer token exchange)
│   └── ...
├── cli.py              — Click CLI (serve, consumer commands)
└── ...
```

**Key patterns:**
- All handlers are async Starlette functions: `async def handler(request: Request) -> JSONResponse`
- Error responses: `make_error(ErrorCode.X, message, **kwargs)` → `NormalizedError`
- State: `request.app.state.store` (ProcessStateStore), `request.app.state.process_mgr` (ProcessManager)
- Config: `read_config(data_dir)` returns raw dict; `load_config(raw)` → AIMCoreConfig
- Tests: `httpx.AsyncClient(app=app)` pattern, fixtures in `tests/conftest.py`

---

## Slice A: Local Tool Discovery + Setup Test-Upstream (est 5h)

### A.1 New File: `aim_node/management/tools.py`

Tool discovery service + handlers. Scans the upstream MCP endpoint configured in `AIMCoreConfig.upstream_url`, discovers tool schemas via MCP protocol, and caches results in `ProcessStateStore`.

```python
# Storage key in ProcessStateStore
TOOLS_CACHE_KEY = "discovered_tools"

class DiscoveredTool:
    """Cached tool schema from upstream scan."""
    tool_id: str          # hash of tool_name + version
    name: str
    version: str
    description: str
    input_schema: dict
    output_schema: dict
    last_scanned_at: str  # ISO timestamp
    last_validated_at: str | None
    validation_status: str  # "pending" | "passed" | "failed"

async def scan_upstream(config: AIMCoreConfig, store: ProcessStateStore) -> list[dict]:
    """Connect to upstream MCP endpoint, list tools, cache schemas."""
    # 1. HTTP GET {upstream_url}/tools/list (or MCP protocol equivalent)
    # 2. Parse tool schemas from response
    # 3. Generate tool_id = hashlib.sha256(f"{name}:{version}").hexdigest()[:12]
    # 4. Store in ProcessStateStore under TOOLS_CACHE_KEY
    # 5. Return list of DiscoveredTool dicts

async def validate_tool(tool_id: str, config: AIMCoreConfig, store: ProcessStateStore) -> dict:
    """Run sample invocation against upstream, verify response matches schema."""
    # 1. Load tool from cache
    # 2. Build sample input from input_schema (generate minimal valid payload)
    # 3. POST to upstream endpoint
    # 4. Validate response against output_schema
    # 5. Update validation_status + last_validated_at in cache
    # 6. Return validation result
```

### A.2 Route Handlers

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `GET` | `/api/mgmt/tools` | `tools_list_local` | List cached tools from last scan |
| `POST` | `/api/mgmt/tools/discover` | `tools_discover` | Trigger upstream scan, return discovered tools |
| `POST` | `/api/mgmt/tools/{tool_id}/validate` | `tools_validate` | Run validation against upstream |
| `GET` | `/api/mgmt/tools/{tool_id}` | `tools_detail` | Single tool detail (schema, validation status) |
| `POST` | `/api/mgmt/setup/test-upstream` | `setup_test_upstream` | Validate upstream URL reachability + schema probe |

**Note:** `setup/test-upstream` is distinct from existing `setup/test-connection` (which tests marketplace API connectivity). This tests the upstream model/MCP endpoint.

### A.3 Request/Response Schemas

```python
# Response: GET /api/mgmt/tools, POST /api/mgmt/tools/discover
class ToolListResponse(BaseModel):
    tools: list[ToolSummary]
    scanned_at: str | None  # ISO timestamp of last scan

class ToolSummary(BaseModel):
    tool_id: str
    name: str
    version: str
    description: str
    validation_status: str
    last_scanned_at: str

# Response: GET /api/mgmt/tools/{tool_id}
class ToolDetailResponse(BaseModel):
    tool_id: str
    name: str
    version: str
    description: str
    input_schema: dict
    output_schema: dict
    validation_status: str
    last_scanned_at: str
    last_validated_at: str | None

# Response: POST /api/mgmt/tools/{tool_id}/validate
class ToolValidationResponse(BaseModel):
    tool_id: str
    status: str  # "passed" | "failed"
    latency_ms: int
    error: str | None = None

# Request: POST /api/mgmt/setup/test-upstream
class TestUpstreamRequest(BaseModel):
    url: str
    timeout_s: float = 10.0

# Response: POST /api/mgmt/setup/test-upstream
class TestUpstreamResponse(BaseModel):
    reachable: bool
    latency_ms: int | None = None
    tools_found: int = 0
    error: str | None = None
```

### A.4 Error Handling
- Upstream unreachable → `ErrorCode.UPSTREAM_UNREACHABLE` (502, per Contracts §5)
- Upstream timeout → `ErrorCode.UPSTREAM_TIMEOUT` (504)
- Tool not found in cache → `ErrorCode.NOT_FOUND` (404)
- Validation failed → `ErrorCode.TOOL_VALIDATION_FAILED` (422) with details

### A.5 Done Criteria — Slice A
- 5 endpoints functional
- Upstream scan discovers tools and caches results
- Validation runs sample invocation and reports pass/fail
- Setup test-upstream probes URL and returns reachability + tool count
- Tests: 15+ (happy path × 5, upstream down, timeout, cache miss, re-scan overwrites, validation pass/fail)

---

## Slice B: Logs + Local Metrics (est 5h)

### B.1 New File: `aim_node/management/logs.py`

Log collection from the structured logger in `aim_node/core/logging.py`.

**Architecture:** The management app needs an in-memory ring buffer that captures recent log records. On startup, install a `logging.Handler` subclass (`RingBufferHandler`) on the root `aim_node` logger that captures entries into a `collections.deque(maxlen=1000)`. The WebSocket handler taps this same buffer via an `asyncio.Queue` per subscriber.

```python
class RingBufferHandler(logging.Handler):
    """Captures log records into a bounded deque."""
    buffer: collections.deque  # maxlen=1000
    subscribers: list[asyncio.Queue]

    def emit(self, record):
        entry = self._format_entry(record)
        self.buffer.append(entry)
        for q in self.subscribers:
            q.put_nowait(entry)  # non-blocking; drop if full

class LogEntry(TypedDict):
    timestamp: str   # ISO
    level: str       # DEBUG/INFO/WARNING/ERROR
    logger: str      # logger name
    message: str
    extra: dict | None
```

### B.2 Route Handlers

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `GET` | `/api/mgmt/logs` | `logs_tail` | Query params: `level` (min level), `limit` (default 100, max 1000), `since` (ISO timestamp) |
| `WS` | `/api/mgmt/logs/stream` | `logs_stream_ws` | Real-time WebSocket stream |

**WebSocket Security (per Gate 1 §2.4):**
- Validate `Origin` header: must be `http://localhost:*` or `http://127.0.0.1:*`
- If remote_bind: require `session_token` query param on upgrade URL
- Reject with 403 before accepting upgrade

### B.3 New File: `aim_node/management/metrics.py`

Local counters maintained by the management app. Uses `ProcessStateStore` for persistence across restarts.

```python
METRICS_KEY = "local_metrics"

class MetricsCollector:
    """Tracks local counters: calls, errors, active sessions, latency."""
    # Incremented by provider/consumer event hooks
    total_calls: int = 0
    total_errors: int = 0
    active_sessions: int = 0
    uptime_s: float  # computed from app start time
    timeseries: list[MetricBucket]  # 5-min bucketed history

class MetricBucket(TypedDict):
    timestamp: str   # ISO, bucket start
    calls: int
    errors: int
    avg_latency_ms: float
```

### B.4 Metrics Route Handlers

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `GET` | `/api/mgmt/metrics/summary` | `metrics_summary` | Current counters: total_calls, total_errors, active_sessions, uptime_s |
| `GET` | `/api/mgmt/metrics/timeseries` | `metrics_timeseries` | Query: `range` (1h|24h|7d), `metric` (calls|errors|latency) |

### B.5 Done Criteria — Slice B
- Log tail returns filtered entries from ring buffer
- WebSocket stream delivers real-time log entries
- WebSocket enforces origin + session token security
- Metrics summary returns current counters
- Timeseries returns bucketed history
- Ring buffer capped at 1000 entries, no memory leak
- Tests: 18+ (log tail filtering, WebSocket connect/stream/disconnect, origin rejection, metrics summary, timeseries ranges, metric types)

---

## Slice C: Provider Lifecycle + Security Ops + Session Kill (est 4h)

### C.1 New Handlers in `aim_node/management/routes.py`

Extend existing routes file with:

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `POST` | `/api/mgmt/provider/restart` | `provider_restart` | Stop + start provider, return new health |
| `POST` | `/api/mgmt/provider/reload` | `provider_reload` | Hot-reload config (re-read config file, apply without process restart) |
| `POST` | `/api/mgmt/lock` | `lock_node` | Clear passphrase from memory, stop provider, set locked state |
| `POST` | `/api/mgmt/keypair/rotate` | `keypair_rotate` | Generate new keypair, update keystore, re-register with backend |
| `DELETE` | `/api/mgmt/sessions/{session_id}` | `session_kill` | Force-close a stuck session |

### C.2 Implementation Notes

**provider_restart:**
```python
async def provider_restart(request):
    pm = request.app.state.process_mgr
    await pm.stop_provider()
    await pm.start_provider()
    health = await pm.provider_health()
    return JSONResponse({"status": "restarted", "health": health})
```

**provider_reload:**
```python
async def provider_reload(request):
    data_dir = request.app.state.store.data_dir
    raw = read_config(data_dir)
    core_cfg = load_config(raw)
    # Update facade with new config
    request.app.state.facade = MarketplaceFacade.create(core_cfg)
    # Signal provider to reload (if running)
    pm = request.app.state.process_mgr
    if pm.is_provider_running():
        await pm.reload_provider_config(core_cfg)
    return JSONResponse({"status": "reloaded"})
```

**lock_node:**
```python
async def lock_node(request):
    pm = request.app.state.process_mgr
    store = request.app.state.store
    # Stop provider if running
    if pm.is_provider_running():
        await pm.stop_provider()
    # Clear passphrase from state
    store.clear_passphrase()
    store.set_locked(True)
    return JSONResponse({"status": "locked"})
```

**keypair_rotate:**
```python
async def keypair_rotate(request):
    store = request.app.state.store
    data_dir = store.data_dir
    # Generate new Ed25519 keypair
    crypto = DeviceCrypto.generate(data_dir)
    # Re-register with backend
    facade = request.app.state.facade
    if facade:
        await facade.post("/aim/nodes/keypair", {
            "public_key": crypto.public_key_pem,
            "fingerprint": crypto.fingerprint,
        })
    return JSONResponse({"status": "rotated", "fingerprint": crypto.fingerprint})
```

**session_kill:**
```python
async def session_kill(request):
    session_id = request.path_params["session_id"]
    pm = request.app.state.process_mgr
    killed = await pm.kill_session(session_id)
    if not killed:
        raise HTTPException(404, f"Session {session_id} not found")
    return JSONResponse({"status": "killed", "session_id": session_id})
```

### C.3 ProcessManager Extensions

Add to `process.py`:
- `reload_provider_config(config)` — send config update signal to running provider
- `kill_session(session_id)` — force-close a specific session
- `is_provider_running()` → bool

### C.4 Done Criteria — Slice C
- Restart stops + starts provider, returns new health
- Reload re-reads config, updates facade, signals provider
- Lock stops provider, clears passphrase, sets locked state
- Keypair rotate generates new key, re-registers with backend
- Session kill force-closes stuck session
- Tests: 12+ (restart cycle, reload config, lock then unlock, rotate + verify fingerprint, kill valid/invalid session)

---

## Slice D: Static Files + SPA Fallback + allAI Local Endpoints (est 4h)

### D.1 Static File Serving

Update `app.py` to serve React SPA build from `frontend/dist/`:

```python
# Replace placeholder:
frontend_dir = Path(data_dir) / "frontend" / "dist"
if frontend_dir.exists():
    # Hashed assets get long cache
    routes.append(Mount("/assets", app=StaticFiles(directory=str(frontend_dir / "assets"))))
    # index.html gets no-cache
```

**SPA Fallback:** Add a catch-all route AFTER all API routes that serves `index.html` for non-API, non-static paths:
```python
async def spa_fallback(request: Request) -> Response:
    path = request.url.path
    # Exclude API and static asset paths — only client routes get index.html
    if path.startswith("/api/") or path.startswith("/assets/"):
        raise HTTPException(404, "Not found")
    index_path = Path(data_dir) / "frontend" / "dist" / "index.html"
    if not index_path.exists():
        raise HTTPException(404, "UI not built")
    return HTMLResponse(index_path.read_text(), headers={"Cache-Control": "no-cache"})

# Add as last route (after all API and static mounts)
routes.append(Route("/{path:path}", spa_fallback, methods=["GET"])
```

**Cache headers (via custom Starlette middleware, not StaticFiles defaults):**
- `/assets/*` (fingerprinted): Add `CacheControlMiddleware` that intercepts responses for paths under `/assets/` and sets `Cache-Control: public, max-age=31536000, immutable`
- `index.html`: Served by `spa_fallback` with explicit `Cache-Control: no-cache`
- Implementation: Subclass `StaticFiles` or add a response middleware that matches path prefixes

### D.2 allAI Local Endpoints

New file: `aim_node/management/allai.py`

**Paths per Gate 1 §2.11:** These sit outside `/api/mgmt/marketplace/` because they are local management capabilities with context injection.

| Method | Path | Handler | Description |
|--------|------|---------|-------------|
| `POST` | `/allai/chat` | `allai_chat` | User message → inject local context → forward to backend |
| `POST` | `/allai/confirm` | `allai_confirm` | Confirm/deny mutating action proposed by allAI |

**allai_chat flow (Contracts §6.1–6.2):**
1. Parse `AllAIChatRequest(message, conversation_id)`
2. **Context injection:** Gather local context — `ProcessStateStore.get_status()`, `ProcessStateStore.get_sessions()`, `ProcessStateStore.get_dashboard()`, tool discovery cache (from `{data_dir}/store/discovered_tools.json`)
3. **Redaction:** Allowlist approach — only include explicitly safe fields. Strip `_passphrase`, API keys, session tokens, CSRF tokens from context
4. **Tool allowlist (Contracts §6.2):** Include `allowed_tools` from Contracts: `["inspect_local_config", "test_market_auth", "scan_provider_endpoint", "list_local_tools", "tail_recent_logs", "explain_last_failure"]`. Mutable via config.toml `[allai]` section
5. **Forward:** `POST /allie/chat/agentic` via `MarketplaceFacade.post()` with payload `{message, context, node_id, conversation_id, allowed_tools}`
6. **Response parsing:** Backend returns `{reply, conversation_id, proposed_actions, suggestions}`. Each `proposed_action` has `{action_id, description, tool_name, params, requires_confirmation}`
7. **Auto-exec vs confirm:** If `requires_confirmation == false` AND tool in allowlist → execute locally, append result. If `true` → return to UI for approval
8. **Max loop depth:** 5 rounds of auto-exec before forcing confirmation (Contracts §6.2 safety bound)
9. **Fallback:** If logs/metrics/tool inventory unavailable, include `degraded_context: true` in payload

**allai_confirm flow (Contracts §6.3 — local execution):**
1. Parse `AllAIConfirmRequest(action_id, approved)`
2. If `approved`: Execute proposed action locally (stored in in-memory action cache from chat response). If action targets backend (e.g., publish tool), proxy via `MarketplaceFacade`
3. If `!approved`: Discard action, return `{status: "denied"}`
4. No backend round-trip for confirm — actions execute locally. Backend proposed the action; confirmation is a local gate

**Note:** Full NLU, tool routing, agent orchestration are BQ-AIM-NODE-ALLAI-COPILOT scope. This BQ provides transport + context injection + confirmation gate.

### D.3 Request/Response Schemas

```python
# POST /allai/chat
class AllAIChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None

class ProposedAction(BaseModel):
    action_id: str
    description: str
    tool_name: str
    params: dict
    requires_confirmation: bool

class AllAIChatResponse(BaseModel):
    reply: str
    conversation_id: str
    proposed_actions: list[ProposedAction] | None = None
    suggestions: list[str] | None = None

# POST /allai/confirm
class AllAIConfirmRequest(BaseModel):
    action_id: str
    approved: bool

class AllAIConfirmResponse(BaseModel):
    status: str  # "executed" | "denied"
    result: dict | None = None
```

### D.4 Done Criteria — Slice D
- Static files served from `frontend/dist/`
- SPA fallback serves index.html for client routes
- Cache headers correct (immutable for hashed assets, no-cache for index.html)
- allAI chat injects local context, redacts secrets, forwards to backend
- allAI confirm executes or denies proposed actions
- Tests: 12+ (static file serving, SPA fallback, 404 when no build, cache headers, allAI chat flow, context injection, redaction, confirm approve/deny)

---

## Summary

| Slice | Endpoints | New Files | Tests |
|-------|-----------|-----------|-------|
| A: Tool Discovery + Test-Upstream | 5 | `management/tools.py` | 15 |
| B: Logs + Metrics | 4 (+ 1 WS) | `management/logs.py`, `management/metrics.py` | 18 |
| C: Provider Lifecycle + Security Ops + Session Kill | 5 | Extensions to `routes.py`, `process.py` | 12 |
| D: Static Files + SPA + allAI | 2 (+ SPA fallback) | `management/allai.py`, updates to `app.py` | 12 |
| **Total** | **16 + 1 WS + SPA** | | **57** |

## Done Criteria (Full BQ)

1. All 16 new endpoints + 1 WebSocket + SPA fallback functional
2. Local tool discovery scans upstream, caches schemas, validates tools
3. Log tail and real-time WebSocket stream functional with security
4. Provider restart/reload, node lock, keypair rotation all work
5. Session kill force-closes stuck sessions
6. Static files + SPA fallback with correct cache headers
7. allAI chat injects local context with redaction, confirm round-trip works
8. All existing 31 routes still functional (no regressions)
9. 57+ tests passing, CI green
10. All error responses use normalized format (ErrorCode + make_error)

## Out of Scope

- React SPA code (BQ-AIM-NODE-UI-SCAFFOLD)
- Backend seller APIs (BQ-AIM-BACKEND-SELLER-APIS)
- allAI tool implementations / NLU (BQ-AIM-NODE-ALLAI-COPILOT)
- Security hardening (already complete from Contracts)
- Marketplace facade (already complete from Contracts)
- Error normalization (already complete from Contracts)

---

## R3 Amendments (S435, addressing MP R2 findings 1–4)

### Amendment: ProcessStateStore Persistence (replaces R2 Amendment 2)

`ProcessStateStore` is a thread-safe singleton that reads `config.toml` for setup state and holds everything else in-memory. It has NO generic persistence to `state.json`. For tools cache and metrics, add a new file-backed KV layer:

```python
# New methods on ProcessStateStore (state.py)
# Use self._data_dir (existing private field)

def get_store_data(self, key: str) -> dict | None:
    """Read from {_data_dir}/store/{key}.json. Returns None if missing."""
    path = self._data_dir / "store" / f"{key}.json"
    if not path.exists():
        return None
    import json
    return json.loads(path.read_text())

def set_store_data(self, key: str, data: dict) -> None:
    """Atomic write to {_data_dir}/store/{key}.json via tmp+rename."""
    import json
    store_dir = self._data_dir / "store"
    store_dir.mkdir(exist_ok=True)
    tmp = store_dir / f"{key}.json.tmp"
    tmp.write_text(json.dumps(data, default=str))
    tmp.rename(store_dir / f"{key}.json")

def lock_node(self) -> None:
    """Clear passphrase from memory, set locked state."""
    with self._state_lock:
        self._passphrase = None
        self._locked = True
        self._unlocked = False
        self._node_state = NodeState.LOCKED
```

Storage layout: `{data_dir}/store/discovered_tools.json`, `local_metrics.json`, `metrics_timeseries.json`. Atomic write via tmp+rename. Single-process (uvicorn single worker), no file locking. Each file includes `_version: 1` for future schema migration.

### Amendment: ProcessManager Extensions (replaces R2 Amendment 3)

Extends `ProcessManager` (process.py) using actual internals (`_provider_task`, `_state`, `_data_dir`, `_load_raw_config()`):

```python
# ProcessManager already has: start_provider(), stop_provider()
# Uses: _provider_task (asyncio.Task), _state (ProcessStateStore), _data_dir

async def restart_provider(self) -> dict:
    """Stop then start provider. Returns dashboard status."""
    await self.stop_provider()
    await self.start_provider()
    return self._state.get_dashboard()

async def reload_config(self) -> None:
    """Re-read config.toml, update state. If provider running, stop+start."""
    self._state._load_config()  # Re-read config.toml
    self._state.determine_node_state()
    # If provider running, restart to pick up new config
    if self._state.provider.running:
        await self.restart_provider()

def is_provider_running(self) -> bool:
    return self._state.provider.running

async def kill_session(self, session_id: str) -> bool:
    """Force-remove session from state. Returns False if not found."""
    session = self._state.get_session(session_id)
    if session is None:
        return False
    self._state.remove_session(session_id)
    return True
```

### Amendment: DeviceCrypto Rotation (replaces R2 Amendment 3 crypto section)

`DeviceCrypto.__init__(config, passphrase)` + `get_or_create_keypairs()`. No `generate()` classmethod exists. Rotation:

```python
# In aim_node/management/routes.py — keypair_rotate handler
async def keypair_rotate(request: Request) -> JSONResponse:
    store = request.app.state.store
    data_dir = store._data_dir
    keystore_path = data_dir / "keystore.json"
    
    # Backup existing keystore
    if keystore_path.exists():
        keystore_path.rename(data_dir / "keystore.json.bak")
    
    # Generate new keypair using existing DeviceCrypto interface
    passphrase = store.get_passphrase() or ""
    config = type("C", (), {"keystore_path": keystore_path, "data_dir": data_dir})()
    crypto = DeviceCrypto(config, passphrase=passphrase)
    crypto.get_or_create_keypairs()
    
    # Re-register with backend via facade
    facade = request.app.state.facade
    if facade:
        pub_keys = crypto.get_public_keys_b64()
        await facade.post("/aim/nodes/keypair", {"public_key": pub_keys[0]})
    
    return JSONResponse({"status": "rotated"})
```

### Amendment: allAI Tool Allowlist (Contracts §6.2 aligned)

Default allowlist from Contracts §6.2: `["inspect_local_config", "test_market_auth", "scan_provider_endpoint", "list_local_tools", "tail_recent_logs", "explain_last_failure"]`. Plus generative tools: `["draft_tool_description", "suggest_pricing"]`. Plus mutating tools (always require confirmation): `["publish_tool", "update_config", "rotate_keypair"]`.
