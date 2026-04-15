# BQ-AIM-NODE-DASHBOARD — Gate 2 Implementation Spec

## Overview

Implementation plan for the provider dashboard. Replaces `DashboardPlaceholder` with a 4-zone real-time page. Backend extends `DashboardResponse` with 4 aggregated fields; frontend builds the page in 5 chunks respecting MP's ~300s timeout.

## Pre-Build Dependencies

```bash
cd frontend && npm install recharts
```

This MUST run before any frontend chunk. Recharts is the only new dependency.

## Build Chunks

### Chunk 1: Backend — Extend DashboardResponse (est. 120s)

**Files:**
- `aim_node/management/schemas.py` — Add 4 fields to `DashboardResponse`
- `aim_node/management/routes.py` — Populate new fields in `dashboard()` handler
- `tests/management/test_routes.py` — Add/update tests for extended response

**Changes to `schemas.py`:**

Add to `DashboardResponse`:
```python
adapter_healthy: bool = False
marketplace_registered: bool = False
published_tool_count: int = 0
active_session_count: int = 0
```

**Changes to `routes.py` `dashboard()` handler:**

After existing field population, add:
```python
# adapter_healthy: reuse provider health check
try:
    health = await provider_health_check(state)  # or however the existing health endpoint works
    adapter_healthy = health.get("upstream_reachable", False)
except Exception:
    adapter_healthy = False

# marketplace_registered: check backend registration
marketplace_registered = False
published_tool_count = 0
facade = state.get_facade()
if facade:
    try:
        resp = await facade.get("/aim/nodes/mine")
        marketplace_registered = resp.status_code == 200
        if marketplace_registered:
            tools_resp = await facade.get(f"/aim/nodes/{node_id}/tools")
            if tools_resp.status_code == 200:
                published_tool_count = len(tools_resp.json().get("tools", []))
    except Exception:
        pass

# active_session_count
sessions = state.get_sessions()
active_session_count = len([s for s in sessions if s.get("state") != "closed"])
```

Exact implementation must follow existing patterns in `routes.py` — the above is directional. Builder should inspect `provider_health()` and `marketplace.tools_list()` for the actual call patterns and reuse them.

**Tests:** Verify that `GET /api/mgmt/status` returns all 4 new fields. Mock facade for registered/unregistered cases.

---

### Chunk 2: Frontend — Hooks + Dashboard Skeleton (est. 150s)

**Files to create:**
- `frontend/src/hooks/useDashboard.ts` — Hook for `/api/mgmt/status` (extended)
- `frontend/src/hooks/useMetricsSummary.ts` — Hook for `/api/mgmt/metrics/summary`
- `frontend/src/hooks/useTimeseries.ts` — Hook for `/api/mgmt/metrics/timeseries`
- `frontend/src/hooks/useSessions.ts` — Hook for `/api/mgmt/sessions`
- `frontend/src/pages/Dashboard.tsx` — Page skeleton importing zones

**Files to modify:**
- `frontend/src/router.tsx` — Replace `DashboardPlaceholder` import with `Dashboard`

**Hook patterns** (follow existing `useHealth.ts` convention):

```typescript
// useDashboard.ts
export function useDashboard() {
  return useQuery({
    queryKey: ['dashboard'],
    queryFn: () => api.get('/api/mgmt/status'),
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}

// useMetricsSummary.ts
export function useMetricsSummary() {
  return useQuery({
    queryKey: ['metrics-summary'],
    queryFn: () => api.get('/api/mgmt/metrics/summary'),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

// useTimeseries.ts
export function useTimeseries(range: '1h' | '24h' | '7d', metric: 'calls' | 'errors') {
  return useQuery({
    queryKey: ['timeseries', range, metric],
    queryFn: () => api.get(`/api/mgmt/metrics/timeseries?range=${range}&metric=${metric}`),
    staleTime: 30_000,
    refetchInterval: 60_000,
  });
}

// useSessions.ts
export function useSessions() {
  return useQuery({
    queryKey: ['sessions'],
    queryFn: () => api.get('/api/mgmt/sessions'),
    staleTime: 15_000,
    refetchInterval: 30_000,
  });
}
```

**Dashboard.tsx skeleton:**
```tsx
export default function Dashboard() {
  // Edge state checks (setup_incomplete, locked) — use useNodeState()
  // If blocked, render blocking card with redirect button
  // Otherwise render: StatusBanner → KPICards → TimeseriesChart → ActivityPanel
}
```

Router update: Change `DashboardPlaceholder` import to `Dashboard` from `@/pages/Dashboard`.

---

### Chunk 3: Frontend — StatusBanner + KPICards (est. 150s)

**Files to create:**
- `frontend/src/components/dashboard/StatusBanner.tsx`
- `frontend/src/components/dashboard/KPICards.tsx`
- `frontend/src/components/dashboard/index.ts` (barrel export)

**StatusBanner props:** Receives `DashboardResponse` data.
- Node ID: truncated to 8 chars, click-to-copy (use `navigator.clipboard`)
- Mode badge: `provider` / `consumer` / `both` with color variants
- Uptime: humanize `uptime_s` → "3d 14h 22m" (simple math, no library)
- Health dot: green/yellow/red per Gate 1 logic:
  - Green: `provider_running && market_connected && adapter_healthy`
  - Yellow: `provider_running && (!adapter_healthy || !market_connected)`
  - Red: `!provider_running`

**KPICards props:** Receives metrics summary data.
- 4 cards in a responsive grid: `grid-cols-2 md:grid-cols-4`
- Each card: label, value (large), subtle icon
- Cards: Total Calls, Error Rate (computed), Active Sessions, Avg Latency
- Use existing `@/components/ui` card patterns if available, otherwise plain div with border

---

### Chunk 4: Frontend — TimeseriesChart (est. 150s)

**Files to create:**
- `frontend/src/components/dashboard/TimeseriesChart.tsx`

**Implementation:**
- Range selector: 3 buttons (1h / 24h / 7d), controlled state, default `24h`
- Two `useTimeseries` calls: one for `calls`, one for `errors` with current range
- Recharts `AreaChart` with `Area` for calls (filled, primary color) and `Line` for errors (red)
- X-axis: timestamps formatted per range (HH:mm for 1h/24h, MM/DD for 7d)
- Y-axis: auto-scaled
- Tooltip: show both series values
- **Empty state**: When both calls and errors have empty `points`, show centered "No metrics data yet. Metrics populate once the provider starts handling requests."
- Responsive: `ResponsiveContainer` from Recharts

---

### Chunk 5: Frontend — ActivityPanel + Edge States (est. 150s)

**Files to create:**
- `frontend/src/components/dashboard/SessionsList.tsx`
- `frontend/src/components/dashboard/ToolsList.tsx`
- `frontend/src/components/dashboard/ActivityPanel.tsx`

**SessionsList:**
- Uses `useSessions()` hook
- Client-side filter: exclude `state === "closed"`
- Client-side slice: max 5 shown
- Each row: session_id (truncated 8 chars), role badge, state badge, peer fingerprint (truncated 8 chars), bytes (humanized: KB/MB/GB)
- "View All →" links to `/sessions` (placeholder OK if page doesn't exist yet)
- Empty: "No active sessions."

**ToolsList:**
- Uses `useMarketplaceTools()` (existing hook at `frontend/src/hooks/useMarketplaceTools.ts`)
- Status badges: `draft` (gray), `active` (green), `archived` (amber)
- "Manage Tools →" links to `/tools`
- Facade unavailable (412): "Register with marketplace to see published tools." with link to `/tools`

**ActivityPanel:** Two-column layout `grid-cols-1 md:grid-cols-2`, sessions left, tools right.

**Edge states in Dashboard.tsx:**
- `setup_incomplete` → blocking card: "Complete setup to access your dashboard." + "Go to Setup →" button → `/setup`
- `locked` → blocking card: "Unlock your node to access the dashboard." + "Unlock →" button → `/setup/unlock`
- Detection: Use `useNodeState()` or `useSetupStatus()` hooks (already exist)

---

### Chunk 6: Frontend Tests (est. 150s)

**Files to create:**
- `frontend/src/hooks/__tests__/useDashboard.test.ts`
- `frontend/src/components/dashboard/__tests__/StatusBanner.test.tsx`
- `frontend/src/components/dashboard/__tests__/KPICards.test.tsx`
- `frontend/src/components/dashboard/__tests__/TimeseriesChart.test.tsx`
- `frontend/src/components/dashboard/__tests__/ActivityPanel.test.tsx`
- `frontend/src/pages/__tests__/Dashboard.test.tsx`

**Test coverage:**
1. Hook tests: verify query keys, stale times, refetch intervals match spec
2. StatusBanner: health dot logic (green/yellow/red), uptime formatting, copy-on-click
3. KPICards: error rate calculation (including division by zero), number formatting
4. TimeseriesChart: range selector state, empty state rendering, dual series
5. ActivityPanel: session filtering (exclude closed), slice to 5, facade unavailable state
6. Dashboard page: edge state blocking cards (setup_incomplete, locked), normal render

Follow existing test patterns in `frontend/src/hooks/__tests__/` and `frontend/src/components/__tests__/`.

## Build Order

```
Chunk 1 (backend) → Chunk 2 (hooks + skeleton) → Chunk 3 (banner + KPIs)
                                                → Chunk 4 (chart)
                                                → Chunk 5 (activity + edge states)
                                                → Chunk 6 (tests)
```

Chunks 3-5 can run in parallel after Chunk 2, but sequential dispatch is safer for MP. Chunk 6 runs last.

## Dispatch Notes

- ALL chunks: `cwd=/Users/max/Projects/ai-market/aim-node` — always include `cd /Users/max/Projects/ai-market/aim-node && git pull origin main` as first instruction
- Chunk 1 (backend): MP via `dispatch_mp_build`
- Chunks 2-6 (frontend): MP via `dispatch_mp_build`
- Each chunk commits and pushes independently
- After Chunk 1, verify pytest passes before starting frontend chunks
- After all chunks, run full test suite: `cd backend && python -m pytest` + `cd frontend && npx vitest run`

## Success Criteria (from Gate 1)

1. Dashboard loads within 2s on fresh page load
2. All 4 zones render with real data from management API
3. Timeseries chart renders correctly for 1h/24h/7d with calls + errors series
4. Health indicator accurately reflects provider + adapter + market status
5. Auto-refresh works without visible flicker
6. All edge states handled: setup_incomplete, locked, provider stopped, empty metrics, facade unavailable
7. Responsive layout works on mobile (≥375px) through desktop
8. Existing tests (379 pytest + 119 vitest) remain green, new tests added
