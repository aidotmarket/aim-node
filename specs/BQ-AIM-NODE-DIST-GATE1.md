# BQ-AIM-NODE-DIST — AIM Node Distribution (Gate 1 Spec)

## Problem
aim-node core functionality is complete (crypto, relay, wire protocol, provider mode, consumer mode — 106 tests, Gate 4 passed). However:
1. **No web UI** — CLI-only, inaccessible to non-technical users
2. **No distribution** — no Docker image, no registry, no single-command install
3. **No cross-platform packaging** — must clone repo and install Python deps manually

Goal: Match the vectorAIz distribution model — `docker pull` → `docker run` → open browser → working node.

## Solution

### 1. Web UI — React/Vite SPA served by Starlette

A lightweight single-page application served by the existing Starlette/uvicorn stack on port 8400.

**Pages:**
- **Dashboard** — Node identity (public key fingerprint), mode (provider/consumer/both), uptime, version, connection status to ai.market
- **Provider Setup** — Configure upstream HTTP endpoint URL, adapter settings (transforms, max body, health check), start/stop provider mode
- **Consumer / Marketplace** — Browse available listings from ai.market, initiate sessions, view active sessions
- **Session Monitor** — Active transfers, latency, metering events, error rates
- **Settings** — Node configuration (keypair management, ai.market API URL, relay preferences)

**Technical approach:**
- React 18 + Vite + TypeScript + Tailwind CSS (matching VZ frontend stack)
- Built to `frontend/dist/` at Docker build time
- Served by Starlette `StaticFiles` mount at `/` with SPA fallback
- API endpoints under `/api/` prefix (Starlette routes)
- No separate web server needed — Starlette serves both API and static files

**API endpoints needed (new, served by aim-node):**
- `GET /api/status` — node identity, mode, health, version
- `GET /api/config` — current configuration (redacted secrets)
- `PUT /api/config` — update configuration
- `POST /api/provider/start` — start provider mode
- `POST /api/provider/stop` — stop provider mode
- `GET /api/provider/health` — upstream endpoint health
- `GET /api/sessions` — list active sessions (provider + consumer)
- `GET /api/sessions/:id` — session detail (metering, latency)
- `GET /api/marketplace/listings` — proxy to ai.market search API
- `POST /api/sessions/initiate` — start a consumer session

### 2. Dockerfile — Multi-stage Build

Following the VZ pattern (BQ-089):

**Stage 1: Frontend builder**
```
FROM node:22-slim AS frontend-builder
COPY frontend/ → npm install → npm run build → /app/frontend/dist/
```

**Stage 2: Python builder**
```
FROM python:3.11-slim-bookworm AS python-builder
COPY requirements.txt → pip install
```

**Stage 3: Runtime**
```
FROM python:3.11-slim-bookworm AS runtime
COPY --from=frontend-builder /app/frontend/dist/ /app/static/
COPY --from=python-builder /install /usr/local
COPY aim_node/ /app/aim_node/
USER aimnode (non-root, uid 1001)
EXPOSE 8400
HEALTHCHECK curl http://localhost:8400/api/status
CMD ["aim-node", "serve", "--host", "0.0.0.0", "--port", "8400"]
```

**Key decisions:**
- Single container — no nginx needed (Starlette serves static + API)
- No database dependency — aim-node is stateless (config from file/env, keypair from volume)
- Config volume at `/data` for keypair persistence and config.toml
- Python 3.11 to match VZ (3.13 in dev but 3.11 for Docker stability)

### 3. Container Registry — GHCR

Publish to `ghcr.io/aidotmarket/aim-node`.

**Tags:**
- `latest` — most recent stable build
- `v0.1.0`, `v0.1.1`, etc. — semantic version tags
- `sha-abc1234` — commit SHA tags for traceability

**Multi-arch:** `linux/amd64` + `linux/arm64`
- Covers: Linux native, macOS (Apple Silicon + Intel via Docker Desktop), Windows (via Docker Desktop/WSL2)
- Built via GitHub Actions using `docker/build-push-action` with QEMU for cross-compilation

### 4. docker-compose.yml

Simple single-service compose for one-command startup:

```yaml
services:
  aim-node:
    image: ghcr.io/aidotmarket/aim-node:latest
    ports:
      - "8400:8400"
    volumes:
      - aim-node-data:/data
    environment:
      - AIM_NODE_MODE=provider  # or consumer, or both
      - AIM_MARKET_URL=https://api.ai.market
    restart: unless-stopped

volumes:
  aim-node-data:
```

### 5. GitHub Actions CI

`.github/workflows/docker-publish.yml`:
- Trigger: push to `main`, tag `v*`
- Steps: checkout → setup QEMU → setup buildx → login GHCR → build+push multi-arch
- Cache: GitHub Actions cache for Docker layers

### 6. New CLI command: `aim-node serve`

Add a `serve` command to the CLI that:
1. Loads config from file/env
2. Starts the Starlette app (API + static files)
3. Optionally auto-starts provider/consumer based on config
4. Opens browser to `http://localhost:8400` (with `--no-browser` flag)

This replaces the current separate `provider` and `consumer` commands for Docker usage, while keeping them available for headless/CLI-only deployments.

## Build Slices

1. **API + Serve command** (~6h) — Starlette API endpoints, `serve` CLI command, static file serving scaffold
2. **Web UI: Dashboard + Settings** (~8h) — React/Vite project, dashboard page, settings page, API integration
3. **Web UI: Provider + Consumer** (~8h) — Provider setup page, marketplace browser, session monitor
4. **Docker + CI** (~4h) — Dockerfile, docker-compose.yml, GitHub Actions, GHCR publishing
5. **Integration + Polish** (~4h) — End-to-end testing, README, start.sh helper script

## Estimated Hours: 30

## Files Touched
- `aim_node/web/` (new) — Starlette API app, routes
- `aim_node/cli.py` — add `serve` command
- `frontend/` (new) — React/Vite SPA
- `Dockerfile` (new)
- `docker-compose.yml` (new)
- `.github/workflows/docker-publish.yml` (new)
- `requirements.txt` (new, for Docker — currently uses pyproject.toml)

## Acceptance Criteria
1. `docker pull ghcr.io/aidotmarket/aim-node` works on linux/amd64 and linux/arm64
2. `docker run -p 8400:8400 ghcr.io/aidotmarket/aim-node` starts node with web UI
3. Browser at `http://localhost:8400` shows dashboard with node identity
4. Provider mode configurable and startable via web UI
5. Consumer marketplace browser shows listings from ai.market
6. Session monitor shows active sessions with metering data
7. Config persists across container restarts via volume mount
8. Keypair generated on first run, persisted in `/data`
9. Non-root container user
10. Health check endpoint at `/api/status`
