# BQ-AIM-NODE-DASHBOARD — Gate 1 Design Review (R2)

## Summary

Replace `DashboardPlaceholder` with a real-time provider dashboard aggregating health, metrics, sessions, and tool status. Requires a minor backend enhancement (extend `DashboardResponse` with 4 fields) and a frontend build (new page with 4 zones, chart dependency addition, hooks, responsive layout).

## Problem

After setup and tool publishing, providers land on an empty placeholder. They have no visibility into node health, call volume, sessions, error rates, or tool status without navigating multiple pages.

## Data Sources — Actual API Contracts

All endpoints are on the management API (port 8401 default).

| Endpoint | Method | Returns | Query Params |
|----------|--------|---------|-------------|
| `/api/mgmt/status` | GET | `DashboardResponse` — `node_id`, `fingerprint`, `mode`, `uptime_s`, `version`, `market_connected`, `provider_running`, `consumer_running` | None |
| `/api/mgmt/provider/health` | GET | `ProviderHealthResponse` — `upstream_reachable`, `latency_ms`, `last_check` | None |
| `/api/mgmt/metrics/summary` | GET | `{ total_calls, total_errors, active_sessions, avg_latency_ms, uptime_s }` | None |
| `/api/mgmt/metrics/timeseries` | GET | `{ range, metric, points: [{timestamp, value}] }` | `range` (1h\|24h\|7d), `metric` (calls\|errors\|latency) — **one metric per request** |
| `/api/mgmt/sessions` | GET | `{ sessions: [{session_id, role, state, created_at, peer_fingerprint, bytes_transferred}] }` | **None** — returns all in-memory sessions |
| `/api/mgmt/marketplace/tools` | GET | Facade proxy — returns tools from backend with `draft\|active\|archived` status | None (requires facade / node_id) |
| `/api/mgmt/tools` | GET | Local tool definitions discovered on this node | None |

## Backend Enhancement

Extend `DashboardResponse` in `schemas.py` with 4 new fields:

```python
class DashboardResponse(BaseModel):
    # existing
    node_id: str
    fingerprint: str = ""
    mode: str = ""
    uptime_s: float
    version: str = ""
    market_connected: bool
    provider_running: bool
    consumer_running: bool
    # new
    adapter_healthy: bool = False       # from provider_health: upstream_reachable
    marketplace_registered: bool = False # from facade is not None (node_id exists)
    published_tool_count: int = 0       # from facade.get("/aim/nodes/{id}/tools") count, or 0 if facade unavailable
    active_session_count: int = 0       # from len(state.get_sessions()) filtered by state != "closed"
```

In the `dashboard()` route handler:
- `adapter_healthy`: call `provider_health` logic (or reuse the adapter's `_healthy` flag via state store) — maps to `upstream_reachable` from `ProviderHealthResponse`
- `marketplace_registered`: `request.app.state.facade is not None`
- `published_tool_count`: wrap `facade.get(...)` in try/except, count results, default 0 if facade unavailable
- `active_session_count`: `len([s for s in state.get_sessions() if s.get("state") != "closed"])`

This keeps the status endpoint as a single aggregated call for the frontend banner.

## Design

### Layout

Single-page dashboard at `/dashboard`. Four zones, stacked vertically on mobile, 2-column grid on ≥768px:

1. **Status Banner** — top full-width
2. **KPI Cards** — row of 4
3. **Timeseries Chart** — full-width
4. **Activity Panel** — two-column (sessions left, tools right)

### Zone 1: Status Banner

Compact horizontal bar:
- **Node ID** (truncated, copy-on-click)
- **Mode** badge (`provider` / `consumer` / `both`)
- **Uptime** (humanized: "3d 14h 22m")
- **Health indicator** — green/yellow/red dot:
  - **Green**: `provider_running && market_connected && adapter_healthy`
  - **Yellow**: `provider_running && (!adapter_healthy || !market_connected)`
  - **Red**: `!provider_running`

Data source: `GET /api/mgmt/status` (extended `DashboardResponse`)

### Zone 2: KPI Cards

| Card | Value | Source |
|------|-------|--------|
| Total Calls | `total_calls` | `GET /api/mgmt/metrics/summary` → `total_calls` |
| Error Rate | `(total_errors / total_calls) * 100`% or "0%" if no calls | `GET /api/mgmt/metrics/summary` → `total_calls`, `total_errors` |
| Active Sessions | `active_sessions` | `GET /api/mgmt/metrics/summary` → `active_sessions` |
| Avg Latency | `avg_latency_ms` rounded to 1 decimal | `GET /api/mgmt/metrics/summary` → `avg_latency_ms` |

No trend indicators in v1 — would require historical snapshots not currently stored.

### Zone 3: Timeseries Chart

Line chart showing calls and errors over time.

- **Range selector**: 1h / 24h / 7d tabs
- **Two separate API calls** per render: `GET /api/mgmt/metrics/timeseries?range={range}&metric=calls` and `?metric=errors`
- **Dual series**: Calls (filled area, primary), Errors (line, red)
- Latency overlay deferred to v2 (would require third call + dual Y-axis complexity)
- Auto-refresh every 60s via React Query `refetchInterval`
- **Empty state**: When `points` array is empty, show centered message "No metrics data yet. Metrics populate once the provider starts handling requests."

**Chart library**: Recharts is **not currently installed**. Gate 2 must include `npm install recharts` in the frontend. Alternatively, a lighter option like a hand-rolled SVG chart could avoid the dependency — builder's discretion at Gate 2.

### Zone 4: Activity Panel

**Left — Active Sessions** (compact list):
- Render all sessions from `GET /api/mgmt/sessions`, client-side filter to exclude `state === "closed"`, client-side slice to show max 5
- Each row: session_id (truncated), role badge, state badge, peer fingerprint (truncated), bytes transferred (humanized)
- "View All →" link to `/sessions`
- **Empty state**: "No active sessions."

**Right — Published Tools** (compact list):
- Source: `GET /api/mgmt/marketplace/tools` (facade proxy)
- Status badges use actual values: `draft` / `active` / `archived`
- No call-count column (not available in current API)
- "Manage Tools →" link to `/tools`
- **Facade unavailable state**: When facade returns 412 (node not registered/setup incomplete), show "Register with marketplace to see published tools." with link to `/tools`

### Edge States

| Node State | Dashboard Behavior |
|-----------|-------------------|
| `setup_incomplete` | Router already redirects `/` → `/setup`. If user navigates directly to `/dashboard`, show a blocking card: "Complete setup to access your dashboard." with "Go to Setup →" button. |
| `locked` | Router redirects to `/setup/unlock`. If direct navigation, show "Unlock your node to access the dashboard." with "Unlock →" button. |
| `ready`, provider not running | Dashboard renders normally. Status banner shows red health. KPI cards show whatever metrics exist. Session list likely empty. |
| `ready`, fresh install (no metrics) | All zones render with zero/empty states. Chart shows empty state message. Session list shows "No active sessions." |
| `ready`, facade unavailable | Status banner, KPIs, chart, sessions all render. Tools panel shows facade-unavailable message. |

### Refresh Strategy

- `GET /api/mgmt/status`: `staleTime: 10_000`, `refetchInterval: 15_000`
- `GET /api/mgmt/metrics/summary`: `staleTime: 30_000`, `refetchInterval: 60_000`
- `GET /api/mgmt/metrics/timeseries`: `staleTime: 30_000`, `refetchInterval: 60_000`
- `GET /api/mgmt/sessions`: `staleTime: 15_000`, `refetchInterval: 30_000`
- Marketplace tools: `staleTime: 60_000`, `refetchInterval: 120_000`

## Out of Scope

- Revenue/earnings data (BQ-AIM-NODE-EARNINGS)
- Log viewer (BQ-AIM-NODE-LOGS-DIAGNOSTICS)
- allAI copilot integration (BQ-AIM-NODE-ALLAI-COPILOT)
- Latency timeseries overlay (v2)
- Trend indicators on KPI cards (v2)
- WebSocket real-time streaming (future)

## Dependencies

- `aim_node/management/schemas.py` — `DashboardResponse` (extend with 4 fields)
- `aim_node/management/routes.py` — `dashboard()` handler (add 4 field population)
- `aim_node/management/metrics.py` — `MetricsCollector` (exists, read-only)
- `aim_node/management/state.py` — `ProcessStateStore` (exists, read-only)
- `aim_node/management/marketplace.py` — `tools_list` (exists, read-only via facade)
- Frontend: React Query (installed), Zustand (installed), **Recharts (NOT installed — must add)**
- Frontend router: `/dashboard` route exists, currently renders `DashboardPlaceholder`

## Estimated Effort

| Area | Hours |
|------|-------|
| Backend: extend DashboardResponse + route | 1.5 |
| Frontend: Status Banner + KPI Cards | 3 |
| Frontend: Timeseries Chart (+ Recharts setup) | 3.5 |
| Frontend: Activity Panel (sessions + tools) | 3 |
| Frontend: Edge states (setup_incomplete, locked, empty, facade unavail) | 2 |
| Tests: backend unit tests for extended response | 1.5 |
| Tests: frontend component tests | 2.5 |
| **Total** | **17** |

## Success Criteria

1. Dashboard loads within 2s on fresh page load
2. All 4 zones render with real data from management API
3. Timeseries chart renders correctly for 1h/24h/7d with calls + errors series
4. Health indicator accurately reflects provider + adapter + market status
5. Auto-refresh works without visible flicker
6. All edge states handled: setup_incomplete, locked, provider stopped, empty metrics, facade unavailable
7. Responsive layout works on mobile (≥375px) through desktop
8. Existing tests (379 pytest + 119 vitest) remain green, new tests added
