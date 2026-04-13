# BQ-AIM-NODE-CONTRACTS — Gate 1 Spec
## AIM Node UI Contracts: API Boundaries, Auth Model, Ownership Split

**BQ Code:** BQ-AIM-NODE-CONTRACTS
**Epic:** AIM-NODE-UI
**Phase:** 1 — Foundation
**Priority:** P0
**Estimated Hours:** 8
**Council Hall:** hall-64f542200af77
**Author:** Vulcan (S431)

---

## 1. Problem Statement

AIM Node needs a web UI. The API surface is split between two codebases:
- **ai-market-backend** — the marketplace server (source of truth for cross-party state)
- **aim-node** — the local management server (source of truth for local machine state)

Before building any UI, we need a clear contract defining what lives where, how the node proxies backend calls, the auth chain, and error handling. Without this, the UI team will make ad-hoc decisions that create coupling, auth gaps, and maintenance debt.

## 2. Ownership Matrix

### 2.1 ai-market-backend Owns (Marketplace Truth)

These are cross-party, multi-tenant, and require database persistence:

| Domain | Existing Endpoints | Gaps for UI |
|--------|-------------------|-------------|
| **Node Registration** | `POST /aim/nodes/register/challenge`, `POST /aim/nodes/register` | `GET /aim/nodes/mine` (authenticated seller's nodes) |
| **Tool Publishing** | `POST /aim/nodes/{id}/tools/publish` | `GET /aim/nodes/{id}/tools` (list published tools), `PUT /aim/nodes/{id}/tools/{tool_id}` (update), `DELETE /aim/nodes/{id}/tools/{tool_id}` (archive) |
| **Discovery** | `POST /aim/discover/search`, `GET /aim/discover/tools/{id}/versions/{v}`, `estimate-cost`, `estimate-latency`, `sample-invoke` | No gaps — sufficient for buyer UI |
| **Sessions** | `POST /aim/sessions`, `GET /aim/sessions/{id}`, `DELETE /aim/sessions/{id}`, `POST /aim/sessions/{id}/keepalive` | `GET /aim/sessions?node_id={id}&range=7d` (node-scoped history) |
| **Metering** | `POST /aim/metering/events` (existing) | No gaps |
| **Settlement** | `GET /aim/settlements/{session_id}` | `GET /aim/settlements?node_id={id}&range=30d` (node-scoped rollups) |
| **Payouts** | `GET /aim/payouts/balance`, `GET /aim/payouts/history` | `GET /aim/payouts/summary?node_id={id}&group_by=day` (rollups by day/tool) |
| **Trust** | `GET /aim/nodes/{id}/trust`, `GET /aim/nodes/{id}/trust/events` | No gaps |
| **Observability** | `GET /aim/observability/traces/{id}/events` | `GET /aim/observability/traces?node_id={id}&limit=50` (node-scoped feed) |
| **Listings** | `GET /listings/mine`, `POST /listings`, `GET /listings/{id}` | `GET /listings?node_id={id}` (filter by originating node) |
| **allAI** | `POST /allie/chat/agentic` | No gaps — proxy endpoint ready |
| **Auth** | `GET /aim/.well-known/jwks.json` | No gaps |

### 2.2 aim-node Owns (Local Machine Truth)

These are single-tenant, local-only, and stored in local config/memory:

| Domain | Existing Endpoints | Gaps for UI |
|--------|-------------------|-------------|
| **Setup Wizard** | `GET /setup/status`, `POST /setup/keypair`, `POST /setup/test-connection`, `POST /setup/finalize` | `POST /setup/test-upstream` (validate upstream model URL) |
| **Dashboard** | `GET /status` | Extend with tool count, local session stats |
| **Config** | `GET /config`, `PUT /config` | No gaps |
| **Provider Controls** | `POST /provider/start`, `POST /provider/stop`, `GET /provider/health` | `POST /provider/restart`, `POST /provider/reload` |
| **Consumer Controls** | `POST /consumer/start`, `POST /consumer/stop` | No gaps |
| **Sessions (local)** | `GET /sessions`, `GET /sessions/{id}` | `DELETE /sessions/{id}` (kill stuck) |
| **Security** | `POST /unlock`, `GET /keypair`, `GET /health` | `POST /lock`, `POST /keypair/rotate` |
| **Tools (local)** | — | `GET /tools` (local inventory from upstream scan), `POST /tools/discover` (scan upstream endpoint), `POST /tools/{id}/validate` (sample invoke + schema check) |
| **Logs** | — | `GET /logs?level=error&limit=100`, `WS /logs/stream` (real-time) |
| **Metrics (local)** | — | `GET /metrics/summary` (local counters), `GET /metrics/timeseries?range=24h` |
| **allAI (local)** | — | `POST /allai/chat` (proxy to backend with local context injection) |

## 3. Auth Model

### 3.1 Auth Chain: UI → Node → Backend

```
Browser (localhost)
    │
    │  No auth (localhost-only, same-machine)
    ▼
AIM Node Management API (localhost:8080)
    │
    │  JWT signed by node's Ed25519 keypair
    │  + API key from config (for legacy endpoints)
    ▼
ai-market-backend (api.ai.market)
```

**UI → Node:** No authentication required. The management API is bound to localhost only. Network requests from non-localhost MUST be rejected (existing behavior via Starlette middleware or Docker port binding).

**Node → Backend:** The node authenticates to the backend using:
1. **JWT** — signed by the node's Ed25519 private key, verified by backend via JWKS. Used for: session negotiation, heartbeat, tool publish, metering.
2. **API key** — stored in local config, passed as `Authorization: Bearer {api_key}`. Used for: initial registration, legacy endpoints.

**allAI proxy:** The node proxies allAI calls to `POST /api/v1/allie/chat/agentic` using the stored API key. The node injects local context (current page, config state, recent errors) into the system prompt before forwarding.

### 3.2 Security Boundaries

- The UI NEVER calls ai-market-backend directly. All marketplace data flows through the node's management API as a proxy/facade.
- The node's private key and API key are NEVER exposed to the browser.
- The `/allai/chat` proxy MUST strip any tool_use responses that would mutate state without user confirmation (copilot proposes, user confirms).

## 4. Node Proxy/Facade Pattern

For marketplace data the UI needs (earnings, published tools, sessions history), the node management API acts as a facade:

```
UI calls:  GET /api/mgmt/marketplace/earnings?range=7d
Node does: GET https://api.ai.market/api/v1/aim/payouts/summary?node_id={self.node_id}&range=7d
           (with JWT auth header)
Returns:   Formatted response to UI
```

### 4.1 Facade Endpoints (new, on aim-node)

All under `/api/mgmt/marketplace/*`:

| Local Endpoint | Proxies To | Purpose |
|---------------|-----------|---------|
| `GET /marketplace/tools` | `GET /aim/nodes/{id}/tools` | Published tools list |
| `POST /marketplace/tools/publish` | `POST /aim/nodes/{id}/tools/publish` | Publish a tool |
| `GET /marketplace/earnings` | `GET /aim/payouts/summary` | Earnings rollups |
| `GET /marketplace/earnings/history` | `GET /aim/payouts/history` | Payout history |
| `GET /marketplace/sessions` | `GET /aim/sessions?node_id={id}` | Session history |
| `GET /marketplace/trust` | `GET /aim/nodes/{id}/trust` | Trust score |
| `GET /marketplace/discover` | `POST /aim/discover/search` | Tool discovery (buyer) |
| `POST /marketplace/allai` | `POST /allie/chat/agentic` | allAI proxy with context |

### 4.2 Caching Strategy

- Trust score: cache 5 minutes (slow-changing)
- Earnings: cache 1 minute
- Published tools: cache 30 seconds
- Sessions: no cache (real-time)
- allAI: no cache (conversational)

## 5. Error Taxonomy

### 5.1 Error Response Format

All management API errors follow a consistent format:

```json
{
  "error": "error_code",
  "message": "Human-readable description",
  "details": {},
  "recoverable": true,
  "suggested_action": "Check your API key in Settings"
}
```

### 5.2 Error Categories

| Code | HTTP | Category | Example |
|------|------|----------|---------|
| `setup_incomplete` | 412 | Precondition | Node not yet configured |
| `node_locked` | 423 | Auth | Passphrase required |
| `auth_failed` | 401 | Auth | Invalid API key or expired JWT |
| `upstream_unreachable` | 502 | Connectivity | Model endpoint not responding |
| `market_unreachable` | 502 | Connectivity | Cannot reach api.ai.market |
| `tool_validation_failed` | 422 | Validation | Schema mismatch or sample invoke failed |
| `config_invalid` | 422 | Validation | Missing required field |
| `already_running` | 409 | State | Provider already started |
| `not_running` | 409 | State | Provider not started |
| `rate_limited` | 429 | Throttle | Too many requests to backend |
| `internal_error` | 500 | System | Unexpected failure |

### 5.3 allAI Error Handling

When allAI suggests an action that fails, the error response includes the allAI context so the assistant can diagnose:

```json
{
  "error": "upstream_unreachable",
  "message": "Cannot connect to http://localhost:8000",
  "allai_context": "The user's upstream model endpoint is not responding. Possible causes: model server not running, wrong port, Docker networking issue."
}
```

## 6. Data Flow Diagrams

### 6.1 Setup Flow
```
User → UI → POST /setup/keypair → Node generates Ed25519 locally
User → UI → POST /setup/test-connection → Node calls backend /health with api_key
User → UI → POST /setup/test-upstream → Node calls upstream model URL
User → UI → POST /setup/finalize → Node saves config, calls POST /aim/nodes/register, autostarts
```

### 6.2 Publish Tool Flow
```
User → UI → POST /tools/discover → Node scans upstream MCP endpoint for tool schemas
User → UI → Reviews/edits tool metadata (allAI can auto-generate descriptions)
User → UI → POST /marketplace/tools/publish → Node calls backend POST /aim/nodes/{id}/tools/publish
Backend → Creates listing, returns marketplace URL
Node → UI → Shows "Published" status with marketplace link
```

### 6.3 Earnings Query Flow
```
User → UI → GET /marketplace/earnings?range=7d
Node → GET api.ai.market/aim/payouts/summary?node_id={id}&range=7d (JWT auth)
Backend → Returns aggregated earnings data
Node → Formats and returns to UI
UI → Renders revenue chart + KPIs
```

### 6.4 allAI Assist Flow
```
User → UI → POST /allai/chat {message: "Why can't I publish?", page_context: "tools"}
Node → Injects local state: config, recent errors, tool list, provider health
Node → POST api.ai.market/allie/chat/agentic {messages, tools: [local_tools]}
Backend → Claude processes with tool_use, returns structured response
Node → If tool_use: executes local tool (read-only), loops
Node → If text: returns to UI
Node → If action_suggested: returns with confirmation prompt
UI → Renders response, shows confirmation button if action needed
```

## 7. Deliverables

1. This spec document (canonical contract reference)
2. OpenAPI fragment for new aim-node facade endpoints (Section 4.1)
3. OpenAPI fragment for new ai-market-backend gaps (Section 2.1 "Gaps" column)
4. Error taxonomy implementation in aim-node (Section 5)
5. Auth chain documentation in aim-node README

## 8. Out of Scope

- Actual implementation of UI components (covered by downstream BQs)
- Backend API implementation (covered by BQ-AIM-BACKEND-SELLER-APIS)
- allAI local tools implementation (covered by BQ-AIM-NODE-ALLAI-COPILOT)
- Buyer-specific flows (covered by BQ-AIM-NODE-BUYER-MODE)

## 9. Done Criteria

- Ownership matrix accepted by Council (no ambiguous ownership)
- Auth chain reviewed for security (no key exposure to browser)
- Error taxonomy covers all UI-visible failure modes
- Facade pattern validated (node never exposes raw backend URLs to UI)
- allAI integration pattern agreed (copilot proposes, user confirms)
