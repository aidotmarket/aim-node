# BQ-AIM-NODE-EARNINGS — Gate 1 Design Review (R2)

## Summary

Replace `EarningsPlaceholder` with a revenue tracking page. All three backend routes exist as facade proxies but **response shapes are unverified** — the UI is designed around a normalization layer that maps any reasonable backend response into display-ready structures. Gate 2 must inspect live endpoints and finalize mappings.

## Backend Routes (exist — `aim_node/management/marketplace.py`)

| Endpoint | Method | Params | Facade Target | Notes |
|----------|--------|--------|---------------|-------|
| `/api/mgmt/marketplace/earnings` | GET | `range` (default `7d`) | `/aim/payouts/summary?node_id={id}&range={range}` | Summary with cache 60s |
| `/api/mgmt/marketplace/earnings/history` | GET | **none** | `/aim/payouts/history` | Full history, no range filter, cache 60s |
| `/api/mgmt/marketplace/settlements` | GET | `range` (default `30d`) | `/aim/settlements?node_id={id}&range={range}` | Settlements, cache 60s |

**Key**: Payout history has **no range param** — it returns all history. Range filtering only applies to summary and settlements.

## Design

### Layout

Single page at `/earnings`. Three zones stacked vertically.

**Range selector** (top-right): 7d / 30d / 90d (default 30d). Affects Zone 1 (summary) and Zone 3 (settlements) only. Zone 2 (payout history) is unaffected — always shows full history.

### Zone 1: Earnings Summary

Row of KPI cards from `/api/mgmt/marketplace/earnings?range={range}`.

**Normalization layer** (frontend utility):
```typescript
interface EarningsSummary {
  grossAmount: number | null;
  netAmount: number | null;
  currency: string;
  sessionCount: number | null;
  payoutCount: number | null;
  range: string;
}

function normalizeEarningsSummary(raw: Record<string, unknown>): EarningsSummary {
  // Map from any of: gross_usd/gross_cents, net_usd/net_cents, total_usd/total_cents
  // Fallback: null for missing fields → card shows "—"
}
```

This approach handles unknown response shapes gracefully. Each KPI card renders the value if present or "—" if null. Hints from `allai.py`'s `_safe_earnings_summary_context`: `range`, `currency`, `gross_usd`, `net_usd`, `total_usd`, `gross_cents`, `net_cents`, `total_cents`, `sessions`, `sessions_count`, `payouts`, `payouts_count`.

Cards:
- **Gross Revenue**: `grossAmount` formatted as currency
- **Net Revenue**: `netAmount` formatted as currency
- **Sessions**: `sessionCount`
- **Payouts**: `payoutCount`

Any card with null value shows "—" with tooltip "Data unavailable for this field."

### Zone 2: Payout History

Table from `/api/mgmt/marketplace/earnings/history`.

**Normalization layer**:
```typescript
interface PayoutEntry {
  id: string;
  date: string;
  amount: number | null;
  currency: string;
  status: string;
  [key: string]: unknown;  // preserve unknown fields for detail view
}

function normalizePayoutHistory(raw: unknown): PayoutEntry[] {
  // Accept array directly or extract from .items/.payouts/.data/.history
  // Each entry: find id/payout_id, date/created_at/timestamp, amount/amount_usd/amount_cents, status
  // Unknown fields preserved for expandable row detail
}
```

Table columns: Date (sortable, default desc), Amount, Status badge, ID (truncated). Click row expands to show all raw fields.

Client-side pagination: 10 per page.

**No range filtering** — this endpoint returns all history. If list is very long, pagination handles it.

### Zone 3: Settlements

Table from `/api/mgmt/marketplace/settlements?range={range}`.

**Normalization layer** (same pattern as payouts):
```typescript
interface SettlementEntry {
  id: string;
  date: string;
  amount: number | null;
  currency: string;
  status: string;
  [key: string]: unknown;
}
```

Table columns: Date, Amount, Status (pending/completed/failed), ID. Client-side pagination: 10 per page.

### Edge States

| Condition | Behavior |
|-----------|----------|
| Facade unavailable (412) | Full-page: "Register with the marketplace to track earnings." Link to `/tools`. |
| Empty summary response | KPI cards all show "—" with "No earnings for this period." |
| Empty history/settlements | Table shows "No payouts yet." / "No settlements yet." |
| Normalization fails (unexpected shape) | Zone-level error: "Could not parse earnings data. Please contact support." with raw JSON in expandable detail for debugging. |
| API error (non-412) | Zone-level error card with retry button. Other zones still render independently. |
| Node in setup_incomplete/locked | Router redirects before reaching page. |

### Refresh Strategy

- Summary + settlements: `staleTime: 60_000`, `refetchInterval: 120_000`, re-fetch on range change
- Payout history: `staleTime: 60_000`, `refetchInterval: 120_000` (no range dependency)

### Chart (Deferred)

Daily earnings chart deferred to v2 — depends on whether any endpoint returns daily granularity, which is unknown until Gate 2.

## Out of Scope

- Buyer-side spend tracking (BQ-AIM-NODE-BUYER-MODE)
- Per-tool revenue breakdown (requires backend support not confirmed)
- Export to CSV
- Invoice generation

## Dependencies

- Backend facade routes: all 3 exist, read-only
- Frontend: React Query (installed)
- No new dependencies required

## Estimated Effort

| Area | Hours |
|------|-------|
| Gate 2: live endpoint inspection + finalize normalizers | 1.5 |
| Frontend: Normalization layer (3 normalizers + tests) | 2 |
| Frontend: Earnings summary cards | 1.5 |
| Frontend: Payout history table with pagination/sort/expand | 2.5 |
| Frontend: Settlements table with pagination | 2 |
| Frontend: Range selector + edge states | 1.5 |
| Tests: normalizer unit tests + component tests | 2 |
| **Total** | **13** |

## Success Criteria

1. Earnings page loads and attempts all 3 backend endpoints
2. Normalization layer handles unknown response shapes gracefully (null fields show "—")
3. Range selector correctly filters summary and settlements (not history)
4. Tables are paginated and sortable
5. Parse failures surface clearly with raw data for debugging
6. All edge states handled
7. Responsive layout
8. Existing tests remain green, new tests added
