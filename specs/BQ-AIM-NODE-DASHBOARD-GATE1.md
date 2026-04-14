# BQ-AIM-NODE-DASHBOARD — Gate 1 Design Review

## Summary

Replace the `DashboardPlaceholder` with a real-time provider dashboard aggregating health, metrics, sessions, and marketplace status into a single glanceable view. All data sources already exist via management API — this is a **frontend-only** BQ with one minor backend enhancement (extend `DashboardResponse`).

## Problem

After setup and tool publishing, providers land on an empty placeholder page. They have no visibility into whether their node is healthy, how many calls they're serving, current sessions, error rates, or revenue. They must manually navigate to separate pages to piece together operational status.

## Design

### Layout

Single-page dashboard at `/dashboard` (already routed). Four zones stacked vertically on mobile, 2-column grid on ≥768px:

1. **Status Banner** — top full-width
2. **KPI Cards** — row of 4 metric cards
3. **Timeseries Chart** — full-width area chart
4. **Activity Panel** — two-column: Active Sessions (left), Published Tools (right)

### Zone 1: Status Banner

Compact horizontal bar showing:
- **Node ID** (truncated, copy-on-click)
- **Mode** badge (provider / consumer / both)
- **Uptime** (humanized: "3d 14h 22m")
- **Health indicator** — green/yellow/red dot with label
  - Green: provider running + market connected + adapter healthy
  - Yellow: provider running but adapter unhealthy OR market disconnected
  - Red: provider not running

Data source: `GET /api/mgmt/status` (existing `DashboardResponse`) + `GET /api/mgmt/provider/health`

### Zone 2: KPI Cards

Four cards in a responsive row:

| Card | Value | Source |
|------|-------|--------|
| Total Calls | `total_calls` | `GET /api/mgmt/metrics/summary` |
| Error Rate | `total_errors / total_calls * 100`% | `GET /api/mgmt/metrics/summary` |
| Active Sessions | `active_sessions` | `GET /api/mgmt/metrics/summary` |
| Avg Latency | `avg_latency_ms` (last bucket) | `GET /api/mgmt/metrics/timeseries?range=1h` |

Each card shows the metric value prominently, a label below, and a subtle trend indicator (↑↓→) comparing current window to previous.

### Zone 3: Timeseries Chart

Area/line chart (Recharts, already in frontend deps) showing calls and errors over time.

- **Range selector**: 1h / 24h / 7d tabs
- **Dual Y-axis**: Calls (left, area fill), Errors (right, line), Latency (toggle overlay)
- Data source: `GET /api/mgmt/metrics/timeseries?range={range}`
- Auto-refresh every 60s via React Query `refetchInterval`

### Zone 4: Activity Panel

**Left — Active Sessions** (compact list, max 5 shown):
- Session ID (truncated), role badge, state badge, peer fingerprint (truncated), bytes transferred
- "View All →" link to `/sessions`
- Data source: `GET /api/mgmt/sessions?limit=5&active=true`

**Right — Published Tools** (compact list):
- Tool name, status badge (live/draft/unpublished), call count (if available)
- "Manage Tools →" link to `/tools`
- Data source: existing tools list from management API or local state

### Refresh Strategy

- React Query with `staleTime: 30_000` (30s), `refetchInterval: 60_000` (60s)
- Status banner: `refetchInterval: 15_000` (15s) for near-real-time health
- All queries use existing hooks pattern (`useQuery` with `api.get<T>()`)

## Backend Enhancement (Minor)

Extend `DashboardResponse` to include a few fields already available in `ProcessStateStore`:

```python
class DashboardResponse(BaseModel):
    # existing fields
    node_id: str
    fingerprint: str = ""
    mode: str = ""
    uptime_s: float
    version: str = ""
    market_connected: bool
    provider_running: bool
    consumer_running: bool
    # new fields
    adapter_healthy: bool = False
    marketplace_registered: bool = False
    published_tool_count: int = 0
    active_session_count: int = 0
```

The `dashboard()` route handler already has access to `state` and `metrics` on `request.app.state` — just read and include them.

## Out of Scope

- Revenue/earnings data (covered by BQ-AIM-NODE-EARNINGS)
- Log viewer (covered by BQ-AIM-NODE-LOGS-DIAGNOSTICS)
- Session detail/kill actions (already exist at `/sessions/{id}`)
- allAI copilot integration (covered by BQ-AIM-NODE-ALLAI-COPILOT)
- WebSocket real-time streaming (future enhancement)

## Dependencies

- `aim_node/management/metrics.py` — MetricsCollector (exists)
- `aim_node/management/state.py` — ProcessStateStore (exists)
- `aim_node/management/routes.py` — dashboard route (exists, needs extension)
- `aim_node/management/schemas.py` — DashboardResponse (exists, needs 4 new fields)
- Frontend: React Query, Recharts, Zustand store (all installed)

## Estimated Effort

- Backend: ~1 hour (extend DashboardResponse + route handler)
- Frontend: ~6 hours (4 zones, responsive layout, chart, hooks, tests)
- Tests: ~3 hours (unit tests for extended response, component tests)
- **Total: ~10 hours**

## Success Criteria

1. Dashboard loads within 2s on fresh page load
2. All 4 zones render with real data from management API
3. Timeseries chart renders with correct 1h/24h/7d ranges
4. Health indicator accurately reflects provider + adapter + market connectivity
5. Auto-refresh works without visible flicker
6. Responsive layout works on mobile (≥375px) through desktop
7. Existing tests (379 pytest + 119 vitest) remain green
