# BQ-AIM-NODE-BUYER-MODE — Gate 1 Design Review

## Summary

Add buyer/consumer functionality to the AIM Node management UI — tool discovery/browsing from the marketplace, consumer proxy start/stop, test invocation of remote tools, and session monitoring for buyer-side connections. Requires both backend enhancements (discovery endpoint, test invoke) and frontend pages.

## Current State

### Backend
- Consumer proxy: `aim_node/consumer/proxy.py` + `session_manager.py` — functional proxy that connects to remote providers
- `POST /api/mgmt/consumer/start` → starts consumer proxy, returns `{ started, proxy_port }`
- `POST /api/mgmt/consumer/stop` → stops consumer proxy
- `GET /api/mgmt/marketplace/sessions` → facade proxy to `/aim/sessions?node_id={id}&range={range}` — includes both provider and consumer sessions
- No dedicated tool discovery/browse endpoint on the management API (marketplace catalog is accessed via facade)

### Frontend
- No buyer-specific pages exist
- `/sessions` placeholder exists but is generic
- `/dashboard` shows `consumer_running` status

## Design

### New Navigation

Add to AppLayout sidebar (below existing items or as a collapsible "Buyer" section):
- **Discover** — browse marketplace tool catalog
- **My Connections** — active consumer sessions and connected providers

### Page 1: Discover (`/discover`)

**Purpose**: Browse available tools on the marketplace that this node can connect to as a buyer.

**Data source**: `GET /api/mgmt/marketplace/tools/catalog` — **NEW backend endpoint** that proxies to a backend marketplace catalog route (to be confirmed — likely `/aim/tools/catalog` or `/aim/tools/search`). Returns a list of published tools from other providers.

**Note**: The exact backend catalog/search endpoint must be confirmed at Gate 2. If no public catalog endpoint exists yet, this page defers until the backend ships one. The spec assumes one will exist.

**Layout**:
- Search bar (query param to backend)
- Grid of tool cards: name, provider name, description (truncated), pricing, trust score badge
- Click → tool detail modal or page: full description, schemas, pricing details, "Connect" button
- Connect button: initiates consumer proxy start + session negotiation (flow TBD at Gate 2 — depends on session connectivity contracts)

### Page 2: My Connections (`/connections`)

**Purpose**: Monitor active consumer-side sessions and manage connections.

**Data source**: `GET /api/mgmt/sessions` (local sessions, filtered client-side to `role === "consumer"`) + `GET /api/mgmt/marketplace/sessions` (marketplace-tracked sessions)

**Layout**:
- Consumer proxy status card: running/stopped, proxy port, start/stop button
- Active connections table: session_id, remote provider, tool name, state, bytes transferred, latency
- Click row → session detail (existing `/sessions/{id}` route)

### Backend Enhancements

| Enhancement | Description | Effort |
|-------------|-------------|--------|
| `GET /api/mgmt/marketplace/tools/catalog` | Facade proxy to backend catalog/search endpoint. Paginated. Cache 120s. | 1h (if backend endpoint exists) |
| `POST /api/mgmt/consumer/test-invoke` | Test-call a remote tool via consumer proxy. Params: `{ provider_node_id, tool_name, arguments }`. Returns response + latency. | 3h |
| Extend `GET /api/mgmt/sessions` | Add `role` filter query param for client convenience (optional — can filter client-side) | 0.5h |

**Key dependency**: The marketplace catalog endpoint on the ai.market backend. If this doesn't exist, the Discover page cannot be built. Gate 2 must verify.

### Edge States

| Condition | Behavior |
|-----------|----------|
| Consumer proxy not running | Connections page shows "Start consumer proxy to connect to providers." with Start button. |
| No marketplace catalog endpoint | Discover page shows "Tool catalog coming soon." |
| Facade unavailable | Both pages show registration prompt. |
| No active consumer sessions | Connections table shows "No active connections." |
| Test invoke fails | Show error with response details (timeout, connection refused, tool error). |

### Refresh Strategy

- Catalog: `staleTime: 120_000`, manual refresh button
- Sessions: `staleTime: 15_000`, `refetchInterval: 30_000`
- Consumer status: `staleTime: 10_000`, `refetchInterval: 15_000`

## Out of Scope

- Spend tracking/budgeting (deferred — no spend-cap API exists yet)
- Subscription management (future — requires billing integration)
- Auto-connect / favorites
- Price comparison

## Dependencies

- `aim_node/consumer/proxy.py` + `session_manager.py` — consumer proxy (exists)
- `aim_node/management/routes.py` — consumer start/stop (exist)
- `aim_node/management/marketplace.py` — sessions facade (exists)
- **Backend dependency**: marketplace catalog/search endpoint — **must be confirmed at Gate 2**
- Frontend: React Query (installed), Zustand (installed)

## Estimated Effort

| Area | Hours |
|------|-------|
| Backend: catalog proxy endpoint | 1 |
| Backend: test-invoke endpoint | 3 |
| Backend: tests | 2 |
| Frontend: Discover page (catalog, search, tool cards) | 4 |
| Frontend: Connections page (proxy status, sessions table) | 3 |
| Frontend: Navigation updates | 1 |
| Frontend: Edge states | 1.5 |
| Tests: frontend component tests | 2.5 |
| **Total** | **18** |

**Note**: If backend catalog endpoint doesn't exist, Discover page portion (~5h) defers, reducing to ~13h.

## Success Criteria

1. Discover page shows marketplace tool catalog (if backend endpoint available)
2. Consumer proxy start/stop works from Connections page
3. Active consumer sessions displayed with real-time refresh
4. Test invoke returns results with latency
5. All edge states handled
6. Navigation updates work correctly
7. Existing tests remain green, new tests added
