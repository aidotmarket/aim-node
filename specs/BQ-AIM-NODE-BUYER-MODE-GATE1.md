# BQ-AIM-NODE-BUYER-MODE — Gate 1 Design Review (R2)

## Summary

Add buyer/consumer functionality to the AIM Node management UI: tool discovery via the existing marketplace discover endpoint, consumer proxy management, and local consumer session monitoring. Scoped to what's buildable with current backend contracts.

## Current State

### Backend (exists)
- `POST /api/mgmt/marketplace/discover` → facade proxy to `POST /aim/discover/search` — **marketplace discovery already works**
- `POST /api/mgmt/consumer/start` → starts consumer proxy, returns `{ started, proxy_port }`
- `POST /api/mgmt/consumer/stop` → stops consumer proxy
- `GET /api/mgmt/sessions` → local in-memory sessions with `{ id, role, state, created_at, peer_fingerprint, bytes_transferred }`
- `GET /api/mgmt/marketplace/sessions?range={range}` → facade proxy to `/aim/sessions` — **seller-scoped**, not usable for buyer-side data

### Frontend
- No buyer-specific pages exist
- Consumer start/stop routes exist but no UI

## Design

### Navigation

Add to AppLayout sidebar:
- **Discover** (`/discover`) — browse marketplace tools
- **Connections** (`/connections`) — consumer proxy + local sessions

### Page 1: Discover (`/discover`)

Uses existing `POST /api/mgmt/marketplace/discover` (already routes to `/aim/discover/search`).

**Layout**:
- Search input + search button
- Results grid: tool name, provider (if available), description (truncated), pricing info
- Click card → expand or modal with full details, schemas, pricing
- **No "Connect" action in v1** — connection flow (session negotiation) is complex and depends on trust channel contracts. Deferred. Users can copy tool details for manual connection.

**Request shape**: `POST /api/mgmt/marketplace/discover` with JSON body `{ query?: string }` (other params TBD — Gate 2 inspects actual `/aim/discover/search` contract).

**Empty state**: "Search the marketplace to find tools from other providers."

### Page 2: Connections (`/connections`)

**Consumer Proxy Status Card** (top):
- Status: Running (green) / Stopped (gray) — from `DashboardResponse.consumer_running`
- Proxy port (from consumer start response, stored in Zustand)
- Start / Stop button

**Local Consumer Sessions** (below):
- Source: `GET /api/mgmt/sessions` — client-side filter to `role === "consumer"`
- Table: ID (truncated), State badge, Peer Fingerprint (truncated), Bytes Transferred, Created At
- **Note**: Local sessions do NOT include provider name, tool name, or latency — these fields are not in the `SessionItem` schema. Show only what's available.
- Click row → `/sessions/{id}` for detail view (existing route)

**Not included**: Marketplace sessions (`/api/mgmt/marketplace/sessions`) are seller-scoped and not usable for buyer-side data. Buyer-side marketplace session tracking requires a new backend endpoint (deferred).

### Edge States

| Condition | Behavior |
|-----------|----------|
| Facade unavailable | Both pages show registration prompt |
| Consumer not running | Connections shows "Start consumer proxy" card. Sessions table empty. |
| No discover results | "No tools found. Try a different search." |
| No consumer sessions | "No active consumer sessions." |
| Discover endpoint error | Error card with retry |

### Deferred (Not In This BQ)

- Connect/invoke flow (session negotiation via trust channel)
- Buyer-side marketplace session tracking (needs backend endpoint)
- Spend tracking / budgeting (no spend-cap API exists)
- Subscription management
- Test invoke of remote tools through consumer proxy

## Dependencies

- `POST /api/mgmt/marketplace/discover` (exists)
- `POST /api/mgmt/consumer/start`, `POST /api/mgmt/consumer/stop` (exist)
- `GET /api/mgmt/sessions` (exists)
- `GET /api/mgmt/status` — `consumer_running` field (exists)
- Frontend: React Query (installed), Zustand (installed)
- No new backend endpoints required

## Estimated Effort

| Area | Hours |
|------|-------|
| Frontend: Discover page (search + results grid + expand) | 4 |
| Frontend: Connections page (proxy card + sessions table) | 3 |
| Frontend: Navigation updates + routing | 1 |
| Frontend: Edge states | 1 |
| Tests: component tests | 2 |
| **Total** | **11** |

## Success Criteria

1. Discover page sends search to existing discover endpoint and renders results
2. Consumer proxy start/stop works from Connections page
3. Local consumer sessions displayed (filtered by role)
4. All edge states handled
5. No new backend endpoints needed
6. Existing tests green, new tests added
