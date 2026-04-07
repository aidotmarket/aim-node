# BQ-AIM-NODE-DIST — AIM Node Distribution (Gate 1 Spec R2)

**Revision:** R3 (addressing MP review mandates from R1)
**BQ Code:** BQ-AIM-NODE-DIST
**Status:** Gate 1 IN_REVIEW

---

## Problem

aim-node core is complete (crypto, relay, wire protocol, provider, consumer — 106 tests, Gate 4). Distribution gaps:
1. CLI-only — inaccessible to non-technical users
2. No Docker image or registry — must clone repo and install Python deps
3. No management UI for node configuration, monitoring, or first-run setup

Goal: `docker pull` → `docker run` → open browser → working node.

---

## Architecture Decision: Separate Management App

The existing `LocalProxy` (consumer/proxy.py) is a consumer-only Starlette app on `127.0.0.1:8400` that proxies buyer requests to active AIM sessions. It is **not** a management server.

This spec introduces a **new, separate** Starlette application: `ManagementApp` (`aim_node/management/app.py`). It:
- Runs on port **8401** (management) — distinct from :8400 (consumer proxy)
- Serves the React SPA (static files) and management REST API
- Binds to `0.0.0.0` by default (Docker) or `127.0.0.1` (local dev)
- Has no import dependency on LocalProxy or consumer internals
- Communicates with provider/consumer processes via shared in-memory state (ProcessStateStore)

**Port strategy:** Port 8401 rootless (no nginx, no privilege escalation). Docker exposes 8401 for the management UI and 8400 for the consumer proxy. No reverse proxy needed at this scale.

---

## First-Run / Setup / Unlock Flow

On first start (no keypair in `/data`), the management UI presents a **setup wizard** before any other page is accessible:

### Step 1: Welcome
- Explains what aim-node is, what it will configure
- "Get Started" button

### Step 2: Keypair Generation
- Auto-generates Ed25519 keypair
- Displays public key fingerprint (SHA-256 hex)
- Optional: set passphrase for private key encryption
- Writes keypair to `/data/keys/`

### Step 3: ai.market Connection
- Input: ai.market API URL (default `https://api.ai.market`)
- Input: API key (obtained from ai.market dashboard)
- "Test Connection" button → calls `GET /api/v1/health` on ai.market
- Success → stores in `/data/config.toml`

### Step 4: Mode Selection
- Choose: Provider, Consumer, or Both
- Provider: input upstream HTTP endpoint URL
- Consumer: no additional config needed
- Stores mode in config.toml

### Step 5: Review & Launch
- Summary of all configuration
- "Launch Node" button → starts selected mode(s)
- Redirects to Dashboard

**State tracking:** `GET /api/mgmt/setup/status` returns `{setup_complete: bool, current_step: int}`. The SPA checks this on every page load and redirects to `/setup` if `setup_complete == false`.

---


---

## Unlock Flow (Encrypted Keypair Restart)

When setup is complete but the private key is encrypted with a passphrase, subsequent starts enter a **locked state**:

### Detection
- On startup, `ProcessStateStore` checks: keypair exists at `/data/keys/private.pem`? → `setup_complete = true`. Can it be loaded without passphrase? → `unlocked = true`. If encrypted → `unlocked = false`, `locked = true`.

### Locked State Behavior
- Management API starts and serves the SPA (port 8401) — always available
- Provider and consumer **do not autostart** — blocked until unlock succeeds
- `GET /api/mgmt/setup/status` returns `{setup_complete: true, locked: true, unlocked: false}`
- SPA detects `locked: true` and redirects to `/unlock` page

### Unlock Page
- Single input: passphrase field
- "Unlock Node" button → `POST /api/mgmt/unlock`
- On success: passphrase held **in memory only** (never persisted to disk), private key decrypted, provider/consumer autostart based on config
- On failure: 401 with error message, user retries

### Unlock Endpoint

| Page/Action | Method | Path | Request Body | Response (200) | Error |
|---|---|---|---|---|---|
| **Unlock** | POST | `/api/mgmt/unlock` | `{passphrase: string}` | `{unlocked: true}` | 401 wrong passphrase |
| **Lock status** | GET | `/api/mgmt/setup/status` | — | `{setup_complete: bool, locked: bool, unlocked: bool, current_step: int}` | — |

### Process-Start Semantics
- `POST /api/mgmt/provider/start` and `/consumer/start` return **423 Locked** if `unlocked == false`
- After successful unlock, if config `mode` includes provider/consumer, they autostart immediately
- Passphrase is held in a `SecretStr` (Pydantic) in memory — zeroed on process exit, never logged

## Endpoint Matrix

### Management API (`/api/mgmt/` prefix, port 8401)

| Page/Action | Method | Path | Request Body | Response (200) | Error |
|---|---|---|---|---|---|
| **Setup: status** | GET | `/api/mgmt/setup/status` | — | `{setup_complete: bool, current_step: int}` | — |
| **Setup: generate keypair** | POST | `/api/mgmt/setup/keypair` | `{passphrase?: string}` | `{fingerprint: string, created: bool}` | 409 exists |
| **Setup: test connection** | POST | `/api/mgmt/setup/test-connection` | `{api_url: string, api_key: string}` | `{reachable: bool, version?: string}` | — |
| **Setup: save config** | POST | `/api/mgmt/setup/finalize` | `{mode: "provider"\|"consumer"\|"both", api_url: string, api_key: string, upstream_url?: string}` | `{ok: true}` | 422 validation |
| **Dashboard** | GET | `/api/mgmt/status` | — | `{node_id: string, fingerprint: string, mode: string, uptime_s: float, version: string, market_connected: bool, provider_running: bool, consumer_running: bool}` | — |
| **Config: read** | GET | `/api/mgmt/config` | — | `{mode: string, api_url: string, api_key_set: bool, upstream_url?: string, data_dir: string}` | — |
| **Config: update** | PUT | `/api/mgmt/config` | `{mode?: string, api_url?: string, api_key?: string, upstream_url?: string}` | `{ok: true, restart_required: bool}` | 422 validation |
| **Provider: start** | POST | `/api/mgmt/provider/start` | — | `{started: true}` | 409 already running, 423 locked |
| **Provider: stop** | POST | `/api/mgmt/provider/stop` | — | `{stopped: true}` | 409 not running |
| **Provider: health** | GET | `/api/mgmt/provider/health` | — | `{upstream_reachable: bool, latency_ms?: float, last_check: string}` | — |
| **Consumer: start** | POST | `/api/mgmt/consumer/start` | — | `{started: true, proxy_port: int}` | 409 already running, 423 locked |
| **Consumer: stop** | POST | `/api/mgmt/consumer/stop` | — | `{stopped: true}` | 409 not running |
| **Sessions: list** | GET | `/api/mgmt/sessions` | — | `{sessions: [{id, role, state, created_at, peer_fingerprint, bytes_transferred}]}` | — |
| **Sessions: detail** | GET | `/api/mgmt/sessions/:id` | — | `{id, role, state, metering_events: [], latency_ms, error_count, created_at}` | 404 |
| **Unlock node** | POST | `/api/mgmt/unlock` | `{passphrase: string}` | `{unlocked: true}` | 401 wrong passphrase |
| **Keypair: info** | GET | `/api/mgmt/keypair` | — | `{fingerprint: string, algorithm: "Ed25519", created_at: string}` | 404 no keypair |

### Notes on Config Read
- `api_key` is NEVER returned in any response — only `api_key_set: bool`
- `passphrase` is NEVER stored or echoed — used only during keypair generation, then discarded
- No raw credentials in any GET response

---


### Consumer Proxy Bind Strategy

The existing `LocalProxy` binds to `127.0.0.1:8400` (loopback only). In Docker, this must change:

- **Local dev / CLI mode:** `LocalProxy` binds `127.0.0.1:8400` (default, unchanged) — consumer proxy is local-only
- **Docker / serve mode:** `LocalProxy` binds `0.0.0.0:8400` — required for Docker port publishing to work
- **Implementation:** `ProcessManager.start_consumer()` passes `host` parameter based on `AIM_NODE_BIND_HOST` env var (default `127.0.0.1`, set to `0.0.0.0` in Dockerfile/docker-compose)
- **docker-compose.yml** exposes both ports: `8401:8401` (management) and `8400:8400` (consumer proxy)
- The `aim-node serve` command accepts `--bind-host` flag (default `0.0.0.0` for serve, `127.0.0.1` for consumer/provider commands)

---

## Security Requirements

### Container
- **Non-root user:** `aimnode` (UID 1001, GID 1001), created in Dockerfile
- **No secrets in image layers:** API keys, passphrases, and keypairs are runtime-only (env vars or volume)
- **Volume ownership:** `/data` owned by `aimnode:aimnode` (1001:1001). Dockerfile creates and `chown`s the dir
- **Read-only filesystem:** Container runs with `--read-only` compatibility (tmpfs for /tmp)

### API Security
- Management API binds `0.0.0.0:8401` — intended for local/Docker network access only
- **No authentication on management API** (v1) — assumes trusted network (same machine or Docker bridge). Future: optional bearer token
- Browser API **never** echoes raw credentials: API keys return `api_key_set: bool`, passphrases are never stored
- All user input validated with Pydantic models before processing
- Upstream URL validated: must be `http://` or `https://` scheme, no file:// or other schemes

### Keypair
- Private key stored at `/data/keys/private.pem` (PEM, optionally encrypted with passphrase)
- Public key at `/data/keys/public.pem`
- File permissions: 600 for private key, 644 for public key
- Volume mount is the ONLY persistence mechanism — no database

---

## Build Slices (Reordered)

### Slice 1: Management State Model + Process Model (~4h)
**Files:** `aim_node/management/__init__.py`, `aim_node/management/state.py`, `aim_node/management/process.py`

- `ProcessStateStore` — thread-safe singleton tracking:
  - Setup completion state (step, complete flag)
  - Provider process status (running, pid, started_at)
  - Consumer process status (running, pid, proxy_port)
  - Active sessions list with metering snapshots
  - Node identity (fingerprint, mode, version, uptime)
- `ProcessManager` — start/stop provider and consumer as async tasks:
  - `start_provider(config)` → creates ProviderSessionHandler + TrustChannelClient
  - `stop_provider()` → graceful shutdown
  - `start_consumer(config)` → creates SessionManager + LocalProxy
  - `stop_consumer()` → graceful shutdown
- Config persistence: read/write `/data/config.toml` via existing `config_loader.py`

**Tests:** 8 unit tests (state transitions, start/stop idempotency, config roundtrip)

### Slice 2: Management API Contract (~6h)
**Files:** `aim_node/management/app.py`, `aim_node/management/routes.py`, `aim_node/management/schemas.py`

- Starlette app with all `/api/mgmt/*` routes from endpoint matrix
- Pydantic v2 request/response schemas for every endpoint
- Setup wizard endpoints (keypair generation, connection test, finalize)
- Provider/consumer start/stop via ProcessManager
- Static file serving scaffold (serves placeholder until SPA built)
- `aim-node serve` CLI command: starts ManagementApp on :8401, optionally starts provider/consumer based on config

**Tests:** 14 tests (every endpoint: happy path + primary error case)

### Slice 3: Web UI — SPA (~8h)
**Files:** `frontend/` (new React/Vite/TypeScript/Tailwind project)

- Setup wizard (5-step flow)
- Dashboard page (status, identity, connection indicator)
- Provider page (start/stop, upstream health, config)
- Consumer page (start/stop, proxy port)
- Sessions page (list + detail)
- Settings page (config editor)
- SPA router: redirects to `/setup` when `setup_complete == false`

**Tests:** Manual QA (e2e tests deferred to integration slice)

### Slice 4: Dockerfile + docker-compose (~4h)
**Files:** `Dockerfile`, `docker-compose.yml`

- Multi-stage build (node:22-slim → python:3.11-slim-bookworm → runtime)
- Frontend built in stage 1, Python deps in stage 2, combined in stage 3
- User `aimnode` (1001:1001), `/data` volume, ports 8400+8401
- `docker-compose.yml`: single service, volume mount, env vars, restart policy
- HEALTHCHECK: `curl -f http://localhost:8401/api/mgmt/status || exit 1`

**Tests:** Local `docker build` + `docker run` + manual verification

### Slice 5: GHCR Publish + Integration (~4h)
**Files:** `.github/workflows/docker-publish.yml`, README updates

- GitHub Actions: checkout → QEMU → buildx → GHCR login → build+push
- Platforms: `linux/amd64,linux/arm64`
- Tags: `latest`, `v{semver}`, `sha-{short}`
- Acceptance test: `docker buildx build --platform linux/amd64,linux/arm64 .` must complete without error
- Integration test: `docker run` → wait for health → curl setup status → run setup flow → verify dashboard
- README: quickstart, docker-compose example, configuration reference

**Tests:** CI green on both architectures, README quickstart works end-to-end

---

## Estimated Hours: 26

## Files Touched
- `aim_node/management/` (new) — state, process manager, app, routes, schemas
- `aim_node/cli.py` — add `serve` command
- `frontend/` (new) — React/Vite SPA
- `Dockerfile` (new)
- `docker-compose.yml` (new)
- `.github/workflows/docker-publish.yml` (new)

## Acceptance Criteria
1. `docker pull ghcr.io/aidotmarket/aim-node:latest` works on linux/amd64 and linux/arm64
2. `docker buildx build --platform linux/amd64,linux/arm64 .` completes without error
3. `docker run -p 8401:8401 -p 8400:8400 -v aim-data:/data ghcr.io/aidotmarket/aim-node` starts node
4. First visit to `http://localhost:8401` shows setup wizard (not dashboard)
5. Setup wizard generates keypair, tests ai.market connection, selects mode
6. After setup, dashboard shows node identity, mode, connection status
7. Provider start/stop works via UI; upstream health check displayed
8. Consumer start/stop works via UI; proxy port shown
9. Sessions page shows active sessions with metering data
10. Config GET never returns raw API key (only `api_key_set: bool`)
11. Container runs as non-root user (UID 1001)
12. `/data` volume persists keypair and config across container restarts
13. GitHub Actions publishes multi-arch image to GHCR on tag push

## MP R1 Mandate Resolution

| # | Mandate | Resolution |
|---|---------|-----------|
| 1 | Full endpoint matrix | Complete matrix with Method/Path/Request/Response/Error for all 16 endpoints |
| 2 | Separate management app from LocalProxy | New `ManagementApp` on :8401, no import dependency on LocalProxy |
| 3 | Explicit security requirements | Non-root UID 1001, runtime-only secrets, volume ownership, no credential echo |
| 4 | Reorder slices | State model → API contract → SPA → Docker → GHCR |
| 5 | Multi-arch acceptance criteria | Explicit `docker buildx build --platform linux/amd64,linux/arm64` in AC #2 |
| 6 | First-run/setup/unlock flow | 5-step wizard + locked-state model with unlock endpoint, passphrase in-memory only, 423 on locked start |
| 7 | Port strategy | 8401 rootless management, 8400 consumer proxy with explicit bind strategy (loopback local / 0.0.0.0 Docker) |
