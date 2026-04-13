# BQ-AIM-NODE-MGMT-API-V2 — Gate 1 Spec
## AIM Node Local Management API Extensions for UI

**BQ Code:** BQ-AIM-NODE-MGMT-API-V2
**Epic:** AIM-NODE-UI
**Phase:** 1 — Foundation
**Priority:** P0
**Estimated Hours:** 15
**Depends On:** BQ-AIM-NODE-CONTRACTS (Gate 1 APPROVED)
**Author:** Vulcan (S431)

---

## 1. Problem Statement

The AIM Node has 17 management endpoints covering setup, dashboard, config, provider/consumer controls, sessions, and security. The UI needs additional local capabilities:

1. **Security hardening** — loopback bind, CSRF/origin protection (Contracts M1)
2. **Error normalization** — migrate current ad-hoc `{"error": ...}` to standardized format (Contracts M5)
3. **Local tool inventory** — scan upstream endpoint, discover schemas, validate tools
4. **Logs** — tail recent logs, stream real-time via WebSocket
5. **Metrics** — local counters for dashboard
6. **Provider lifecycle** — restart, reload config
7. **Security ops** — lock, rotate keypair
8. **Marketplace facade** — proxy endpoints to backend (Contracts Section 4.1)
9. **allAI local proxy** — forward chat with context injection (Contracts Section 6)

## 2. New Endpoints

### 2.1 Security Hardening (Contracts M1)

**Implementation, not new endpoints:**
- CLI `serve` command: change default `--host` from `0.0.0.0` to `127.0.0.1`
- Add `OriginValidationMiddleware` to Starlette app: validate `Origin` header on POST/PUT/DELETE
- Issue CSRF token via `GET /api/mgmt/health` response (new `csrf_token` field)
- Validate `X-CSRF-Token` header on all mutating requests
- **Remote-bind session token:** If `--host 0.0.0.0` is enabled, all management API requests MUST also present `X-Session-Token` header. The session token is issued on first localhost access, stored in browser `sessionStorage`, and validated on every subsequent request. Requests without a valid session token are rejected 403. (Contracts M1 §3.1 requirement 3)

### 2.2 Error Normalization (Contracts M5)

**Refactor, not new endpoints:**
- Replace all `JSONResponse({"error": ...})` patterns with `ErrorResponse(code=..., message=..., ...)` 
- Update all exception handlers in `app.py` to return normalized format
- Add `request_id` generation middleware

### 2.3 Local Tool Discovery

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/mgmt/tools` | List locally discovered tools (from upstream scan cache) |
| `POST` | `/api/mgmt/tools/discover` | Scan upstream MCP endpoint, discover tool schemas |
| `POST` | `/api/mgmt/tools/{tool_id}/validate` | Run sample invocation against upstream, verify schema |
| `GET` | `/api/mgmt/tools/{tool_id}` | Local tool detail (schema, last validation, upstream status) |

### 2.4 Logs

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/mgmt/logs` | Tail recent log entries (query: `level`, `limit`, `since`) |
| `WS` | `/api/mgmt/logs/stream` | Real-time log stream via WebSocket |

**WebSocket Security (`/api/mgmt/logs/stream`):**
- On upgrade request: validate `Origin` header matches `http://localhost:*` or `http://127.0.0.1:*` (same policy as management CORS)
- If remote-bind (`--host 0.0.0.0`) is enabled: require `session_token` query parameter on the upgrade request URL (WebSocket upgrade cannot attach custom headers in all browsers)
- Connections from non-loopback origins without a valid session token are rejected 403 before the upgrade is accepted

### 2.5 Local Metrics

| Method | Path | Purpose |
|--------|------|---------|
| `GET` | `/api/mgmt/metrics/summary` | Local counters: total calls, errors, active sessions, uptime |
| `GET` | `/api/mgmt/metrics/timeseries` | Local timeseries (query: `range=1h|24h|7d`, `metric=calls|errors|latency`) |

### 2.6 Provider Lifecycle

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/mgmt/provider/restart` | Stop then start provider (returns new health) |
| `POST` | `/api/mgmt/provider/reload` | Hot-reload config without full restart |

### 2.7 Security Operations

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/mgmt/lock` | Lock node (clear passphrase from memory, stop provider) |
| `POST` | `/api/mgmt/keypair/rotate` | Generate new keypair, re-register with backend |

### 2.8 Setup Enhancement

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/api/mgmt/setup/test-upstream` | Validate upstream model URL during setup (reachability + schema probe) |

### 2.9 Session Management

| Method | Path | Purpose |
|--------|------|---------|
| `DELETE` | `/api/mgmt/sessions/{session_id}` | Kill stuck local session |

### 2.10 Marketplace Facade (Contracts Section 4.1)

All under `/api/mgmt/marketplace/*` — proxy to backend with Bearer token auth (API-key exchange → `access_token`, per Contracts Section 3.2):

| Method | Path | Proxies To |
|--------|------|-----------|
| `GET` | `/marketplace/node` | `GET /aim/nodes/mine` |
| `GET` | `/marketplace/tools` | `GET /aim/nodes/{id}/tools` |
| `POST` | `/marketplace/tools/publish` | `POST /aim/nodes/{id}/tools/publish` |
| `PUT` | `/marketplace/tools/{tool_id}` | `PUT /aim/nodes/{id}/tools/{tool_id}` |
| `DELETE` | `/marketplace/tools/{tool_id}` | `DELETE /aim/nodes/{id}/tools/{tool_id}` |
| `GET` | `/marketplace/earnings` | `GET /aim/payouts/summary?node_id={id}` |
| `GET` | `/marketplace/earnings/history` | `GET /aim/payouts/history` |
| `GET` | `/marketplace/sessions` | `GET /aim/sessions?node_id={id}` |
| `GET` | `/marketplace/settlements` | `GET /aim/settlements?node_id={id}` |
| `GET` | `/marketplace/trust` | `GET /aim/nodes/{id}/trust` |
| `GET` | `/marketplace/trust/events` | `GET /aim/nodes/{id}/trust/events` |
| `GET` | `/marketplace/traces` | `GET /aim/observability/traces?node_id={id}` |
| `GET` | `/marketplace/listings` | `GET /listings?node_id={id}` |
| `GET` | `/marketplace/discover` | `POST /aim/discover/search` |

**Discover endpoint query-to-body mapping:** `GET /marketplace/discover` translates query parameters to the `POST /aim/discover/search` request body:

| Query Param | POST Body Field | Notes |
|-------------|----------------|-------|
| `q` | `query` | Free-text search string |
| `category` | `category` | Tool category filter |
| `tags` | `tags` | Comma-separated string → array |
| `limit` | `limit` | Max results (default 20, max 100) |
| `offset` | `offset` | Pagination offset |
| `sort_by` | `sort_by` | `relevance` \| `popularity` \| `created_at` |

All query params are optional. Omitting all params produces an unfiltered browse (empty POST body).

### 2.11 allAI Local Endpoints

Local capabilities, not marketplace proxies. These handle the allAI chat round-trip with context injection before forwarding to the backend, and the confirmation round-trip for mutating actions.

| Method | Path | Purpose |
|--------|------|---------|
| `POST` | `/allai/chat` | Submit a user message; node injects local context per redaction rules (Contracts §6.1), forwards to backend `POST /allie/chat/agentic` |
| `POST` | `/allai/confirm` | Confirm a mutating action proposed by allAI (Contracts §6.3 confirmation contract) |

These endpoints are outside `/api/mgmt/marketplace/*` because they are local management capabilities, not marketplace data proxies.

### 2.12 Static File Serving

This BQ owns Starlette static file serving. The React SPA build artifacts are produced by BQ-AIM-NODE-UI-SCAFFOLD (which owns the Docker multi-stage build, Node 20 LTS) and placed at `frontend/dist/` in the Python runtime image.

This BQ implements:
- Update the existing `Mount("/static", ...)` placeholder in `app.py` to serve from `frontend/dist/`
- SPA fallback: any non-API, non-static path returns `index.html` (enables client-side routing)
- Cache headers: `Cache-Control: public, max-age=31536000` for fingerprinted/hashed assets; `no-cache` for `index.html`

## 3. Build Slices

**Slice A:** Security hardening (loopback bind, CSRF middleware, error normalization, request_id)
**Slice B:** Local tools (discover, validate, list, detail) + setup test-upstream
**Slice C:** Logs (tail + WebSocket stream) + local metrics (summary + timeseries)
**Slice D:** Provider lifecycle (restart, reload) + security ops (lock, rotate) + session kill
**Slice E:** Marketplace facade (14 proxy endpoints with caching per Contracts Section 4.2)
**Slice F:** Static file serving + SPA fallback (§2.12) + allAI local endpoints (`POST /allai/chat`, `POST /allai/confirm`) with context injection per Contracts Section 6

## 4. Done Criteria

- Loopback-only bind enforced by default, CSRF validated on mutating requests
- All error responses follow normalized format (19 codes from Contracts)
- Local tool discovery scans upstream MCP endpoint and caches schemas
- Log tail and WebSocket stream functional
- All 14 marketplace facade endpoints proxy correctly with Bearer token auth
- allAI chat (`POST /allai/chat`) injects local context per redaction rules (Contracts §6.1); confirmation round-trip (`POST /allai/confirm`) executes approved mutating actions
- SPA fallback serves index.html for client routes
- All existing 17 endpoints still functional (no regressions)

## 5. Out of Scope

- React SPA code (covered by BQ-AIM-NODE-UI-SCAFFOLD)
- Backend API additions (covered by BQ-AIM-BACKEND-SELLER-APIS)
- allAI local tool implementations (covered by BQ-AIM-NODE-ALLAI-COPILOT)
