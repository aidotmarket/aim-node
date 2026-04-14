# BQ-AIM-NODE-EARNINGS — Gate 1 Design Review (R3)

## Summary

Replace `EarningsPlaceholder` with a revenue tracking page. All three backend routes exist as facade proxies. Backend Pydantic schemas are now confirmed from `ai-market-backend/app/schemas/aim_seller.py`.

## Backend Routes & Confirmed Schemas

| Endpoint | Facade Target | Response Schema |
|----------|---------------|-----------------|
| `GET /api/mgmt/marketplace/earnings?range={range}` | `/aim/payouts/summary` | `EarningsSummary` |
| `GET /api/mgmt/marketplace/earnings/history` | `/aim/payouts/history` | Bare list or `{ payouts: [...] }` (normalize both) |
| `GET /api/mgmt/marketplace/settlements?range={range}` | `/aim/settlements` | `SettlementListResponse` |

**Confirmed backend schemas** (from `app/schemas/aim_seller.py`):

```python
class EarningsPeriodEntry(BaseModel):
    date: str
    amount_cents: int
    calls: int

class EarningsByListing(BaseModel):
    listing_id: UUID
    amount_cents: int
    calls: int

class EarningsSummary(BaseModel):
    total_earned_cents: int
    total_paid_cents: int
    pending_cents: int
    period_earnings: list[EarningsPeriodEntry]
    totals_by_listing: list[EarningsByListing]

class SettlementListItem(BaseModel):
    session_id: UUID
    amount: int
    buyer_amount: int
    seller_amount: int
    commission: int
    status: str
    settled_at: Optional[datetime] = None

class SettlementListResponse(BaseModel):
    settlements: list[SettlementListItem]
    total: int; limit: int; offset: int
```

**Note**: Payout history has **no range param** — returns full history. Range selector only affects summary and settlements.

## Design

### Layout

Single page at `/earnings`. Three zones. Range selector (7d/30d/90d, default 30d) at top-right — affects Zone 1 and Zone 3 only.

### Zone 1: Earnings Summary

Four KPI cards from `EarningsSummary`:

| Card | Field | Format |
|------|-------|--------|
| Total Earned | `total_earned_cents` | `$X.XX` (cents → dollars) |
| Total Paid | `total_paid_cents` | `$X.XX` |
| Pending | `pending_cents` | `$X.XX` |
| Listings | `totals_by_listing.length` | Count |

Below cards: **Period Earnings mini-chart** (optional) — if `period_earnings` has >1 entry, render a simple bar chart (reuse Recharts from Dashboard BQ if available). Shows daily `amount_cents` over the range. If empty or single entry, omit.

**Per-listing breakdown**: collapsible table below KPIs showing `totals_by_listing` — listing_id (truncated), amount (cents→dollars), calls.

### Zone 2: Payout History

Table from `/api/mgmt/marketplace/earnings/history`.

Normalization: accept bare list `[...]` or `{ payouts: [...] }`. Each entry mapped to:
```typescript
interface PayoutEntry {
  id: string;        // payout_id or first available id-like field
  date: string;      // created_at / timestamp / date
  amountCents: number;
  status: string;
  [key: string]: unknown;  // preserve extra fields for expand view
}
```

Table: Date (sortable, desc default), Amount ($X.XX), Status badge, ID. Click row → expand raw fields. Client-side pagination: 10/page. No range filtering.

### Zone 3: Settlements

Table from `SettlementListResponse`:

| Column | Field | Format |
|--------|-------|--------|
| Session ID | `session_id` | Truncated UUID |
| Amount | `amount` | Cents → $X.XX |
| Seller Share | `seller_amount` | Cents → $X.XX |
| Commission | `commission` | Cents → $X.XX |
| Status | `status` | Badge (pending/completed/failed) |
| Settled At | `settled_at` | Formatted datetime or "—" if null |

Client-side pagination: 10/page. Respects range selector.

### Edge States

| Condition | Behavior |
|-----------|----------|
| Facade unavailable (412) | Full-page: "Register with the marketplace to track earnings." |
| Empty summary (all zeros) | Cards show $0.00, empty listings table, empty period chart |
| Empty history/settlements | "No payouts yet." / "No settlements yet." |
| Normalization fails | Zone-level error with raw JSON in expandable detail |
| API error (non-412) | Zone-level error with retry. Other zones render independently. |

### Refresh Strategy

- Summary + settlements: `staleTime: 60_000`, `refetchInterval: 120_000`, re-fetch on range change
- Payout history: `staleTime: 60_000`, `refetchInterval: 120_000`

## Out of Scope

- Buyer-side spend tracking (BQ-AIM-NODE-BUYER-MODE)
- Export to CSV, invoice generation

## Dependencies

- Backend facade routes (all 3 exist, read-only)
- Frontend: React Query (installed), Recharts (if added by Dashboard BQ — optional for period chart)

## Estimated Effort

| Area | Hours |
|------|-------|
| Frontend: KPI cards + per-listing breakdown | 2.5 |
| Frontend: Payout history table + normalizer | 2.5 |
| Frontend: Settlements table | 2 |
| Frontend: Range selector + edge states + period chart | 2 |
| Tests: normalizer + component tests | 2 |
| **Total** | **11** |

## Success Criteria

1. KPI cards show `total_earned_cents`, `total_paid_cents`, `pending_cents` formatted as dollars
2. Per-listing breakdown renders `totals_by_listing`
3. Range selector filters summary + settlements, not history
4. Tables paginated and sortable
5. Payout history normalizer handles both bare list and wrapped formats
6. All edge states handled
7. Existing tests green, new tests added
