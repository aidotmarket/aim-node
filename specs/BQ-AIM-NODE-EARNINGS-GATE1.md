# BQ-AIM-NODE-EARNINGS — Gate 1 Design Review

## Summary

Replace `EarningsPlaceholder` with a revenue tracking page showing earnings summary, payout history, and settlement details. This is a **frontend-only** BQ — all three backend routes exist as facade proxies. Response shapes from the backend are pass-through and must be confirmed at Gate 2 via live endpoint inspection.

## Current State

### Backend Routes (exist — `aim_node/management/marketplace.py`)

| Endpoint | Method | Params | Facade Target | Notes |
|----------|--------|--------|---------------|-------|
| `/api/mgmt/marketplace/earnings` | GET | `range` (default `7d`) | `/aim/payouts/summary?node_id={id}&range={range}` | Summary with cache 60s |
| `/api/mgmt/marketplace/earnings/history` | GET | none | `/aim/payouts/history` | Full payout history, cache 60s |
| `/api/mgmt/marketplace/settlements` | GET | `range` (default `30d`) | `/aim/settlements?node_id={id}&range={range}` | Settlement details, cache 60s |

All routes return 412 when facade is unavailable (node not registered).

### Frontend (exists — `frontend/src/pages/placeholders/EarningsPlaceholder.tsx`)
- Empty placeholder with "Coming Soon" message
- Route mounted at `/earnings` in AppLayout

## Design

### Layout

Single page at `/earnings`. Three zones stacked vertically:

1. **Earnings Summary** — top full-width card row
2. **Payout History** — full-width table
3. **Settlements** — full-width table

Range selector shared across all zones: 7d / 30d / 90d (default 30d).

### Zone 1: Earnings Summary

Row of 3–4 KPI cards based on `/api/mgmt/marketplace/earnings` response.

**Expected fields** (to be confirmed at Gate 2 via live endpoint):
- Gross revenue (total earned before fees)
- Net revenue (after platform fees)
- Session count (number of billed sessions)
- Currency (likely USD)

Each card shows the metric prominently with label below. If the response includes a `range` field, display it as a subtitle.

**Note**: The exact response shape from `/aim/payouts/summary` is not documented in the local codebase — it's a backend facade proxy. Gate 2 must inspect the live response and finalize field mappings. The allAI context builder (`_safe_earnings_summary_context` in `allai.py`) gives hints: it looks for `range`, `currency`, `gross_usd`, `net_usd`, `total_usd`, `gross_cents`, `net_cents`, `total_cents`, `sessions`, `sessions_count`, `payouts`, `payouts_count`.

### Zone 2: Payout History

Table from `/api/mgmt/marketplace/earnings/history`:
- Columns: Date, Amount, Status, Reference/ID
- Paginated client-side (10 per page) if list is long
- Sortable by date (default desc)

**Note**: Response shape must be confirmed at Gate 2.

### Zone 3: Settlements

Table from `/api/mgmt/marketplace/settlements`:
- Columns: Date, Amount, Status (pending/completed/failed), Settlement ID
- Range param matches the shared range selector
- Paginated client-side (10 per page)

**Note**: Response shape must be confirmed at Gate 2.

### Edge States

| Condition | Behavior |
|-----------|----------|
| Facade unavailable (412) | Full-page empty state: "Register with the marketplace to track earnings." Link to `/tools`. |
| No earnings data (empty response) | Each zone renders independently: "No earnings for this period." / "No payouts yet." / "No settlements yet." |
| API error (non-412) | Zone-level error card with retry button. Other zones still render. |
| Node in setup_incomplete/locked | Router redirects before reaching earnings page (existing behavior). |

### Refresh Strategy

- All queries: `staleTime: 60_000`, `refetchInterval: 120_000`
- Range change triggers immediate refetch with new params
- Use React Query `useQuery` with `api.get<T>()` pattern

### Chart (Optional/Deferred)

A daily earnings chart (bar chart over time) would be valuable but depends on whether the history endpoint returns daily granularity. If it does, add a simple bar chart above the payout table using the same chart library added in BQ-AIM-NODE-DASHBOARD. If not, defer to v2.

## Out of Scope

- Buyer-side spend tracking (BQ-AIM-NODE-BUYER-MODE)
- Per-tool revenue breakdown (requires backend support not yet confirmed — defer)
- Export to CSV
- Invoice generation
- Dashboard earnings KPI card (BQ-AIM-NODE-DASHBOARD may reference earnings later but is independent)

## Dependencies

- Backend facade routes: all 3 exist, read-only
- Frontend: React Query (installed), chart library (if Dashboard BQ adds Recharts, reuse it; otherwise defer chart)
- Zustand: may use for range selector state if shared across zones

## Estimated Effort

| Area | Hours |
|------|-------|
| Gate 2: live endpoint inspection + finalize field mappings | 1 |
| Frontend: Earnings summary cards | 2 |
| Frontend: Payout history table with pagination/sort | 3 |
| Frontend: Settlements table with pagination | 2.5 |
| Frontend: Range selector + edge states | 1.5 |
| Tests: frontend component tests | 2 |
| **Total** | **12** |

## Success Criteria

1. Earnings page loads and displays data from all 3 backend endpoints
2. Range selector (7d/30d/90d) correctly filters earnings and settlements
3. Tables are paginated and sortable
4. All edge states handled: facade unavailable, empty data, API errors
5. Auto-refresh works without flicker
6. Responsive layout (mobile ≥375px through desktop)
7. Existing tests remain green, new component tests added
