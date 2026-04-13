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

### 3.1 Management Plane Security (UI → Node)

**Mandate M1: Loopback-only bind + origin validation.**

The management API (`/api/mgmt/*`) MUST enforce:

1. **Bind to loopback only.** The CLI `serve` command MUST default to `--host 127.0.0.1` (not `0.0.0.0`). Docker compose binds `127.0.0.1:8080:8080`. An explicit `--host 0.0.0.0` flag is available for advanced users with a warning.

2. **Origin/CSRF protection.** All state-mutating requests (POST/PUT/DELETE) MUST validate:
   - `Origin` header matches `http://localhost:*` or `http://127.0.0.1:*`, OR
   - A per-session CSRF token is present in `X-CSRF-Token` header (issued via `GET /api/mgmt/health` response).
   - Requests without valid origin or token are rejected with 403.

3. **No remote access without explicit opt-in.** If `--host 0.0.0.0` is used, the management API MUST require a local session token (issued on first localhost access, stored in browser, validated on every request).

### 3.2 Node → Backend Auth Chain

**Mandate M2: Exact auth per endpoint family.**

The node authenticates to ai-market-backend using a two-step flow that already exists in `aim_node/core/auth.py`:

1. **API Key Exchange:** Node sends `X-API-Key` header to `POST /auth/token` on the backend. Backend returns `access_token` + `refresh_token`. Tokens stored locally in `auth_token.json`.

2. **Bearer Token:** All subsequent backend calls use `Authorization: Bearer {access_token}`. On 401, node refreshes via stored `refresh_token`.

**Auth per endpoint family:**

| Endpoint Family | Auth Method | Token Claims |
|----------------|------------|-------------|
| Registration (`/aim/nodes/register/challenge`, `/aim/nodes/register`) | `X-API-Key` (initial), then Ed25519 signed challenge-response | `node_id`, `public_key` |
| Tool Publish (`/aim/nodes/{id}/tools/publish`) | Bearer token | `node_id`, `seller_id` |
| Sessions (`/aim/sessions/*`) | Bearer token | `node_id`, `session_id` |
| Metering (`/aim/metering/events`) | Bearer token + Ed25519 signed payload | `node_id` |
| Payouts/Settlements (`/aim/payouts/*`, `/aim/settlements/*`) | Bearer token | `node_id`, `seller_id` |
| Discovery (`/aim/discover/*`) | Bearer token (buyer) or public (search) | `node_id` |
| Trust (`/aim/nodes/{id}/trust*`) | Bearer token | `node_id` |
| Observability (`/aim/observability/*`) | Bearer token | `node_id` |
| allAI (`/allie/chat/agentic`) | Bearer token (via API key) | `user_id` |

**Registration choreography (full):**
```
1. Node calls POST /aim/nodes/register/challenge with {public_key, endpoint_url}
2. Backend returns {challenge: random_bytes, challenge_id}
3. Node signs challenge with Ed25519 private key
4. Node calls POST /aim/nodes/register with {challenge_id, signature, public_key, endpoint_url}
5. Backend verifies signature, creates/reactivates node, returns {node_id, node_serial}
6. Node stores node_id in local config
```

### 3.3 Security Boundaries

- The UI NEVER calls ai-market-backend directly. All marketplace data flows through the node management API as a proxy/facade.
- The node's private key, API key, and bearer tokens are NEVER exposed to the browser.
- The `/allai/chat` proxy MUST apply redaction rules (Section 6) before forwarding context.

## 4. Node Proxy/Facade Pattern

For marketplace data the UI needs (earnings, published tools, sessions history), the node management API acts as a facade:

```
UI calls:  GET /api/mgmt/marketplace/earnings?range=7d
Node does: GET https://api.ai.market/api/v1/aim/payouts/summary?node_id={self.node_id}&range=7d
           (with JWT auth header)
Returns:   Formatted response to UI
```

### 4.1 Facade Endpoints (new, on aim-node)

**Mandate M3: Complete facade coverage for every backend capability the UI consumes.**

All under `/api/mgmt/marketplace/*`:

| Local Endpoint | Proxies To | Purpose |
|---------------|-----------|---------|
| `GET /marketplace/node` | `GET /aim/nodes/mine` | Seller's node details |
| `GET /marketplace/tools` | `GET /aim/nodes/{id}/tools` | Published tools list |
| `POST /marketplace/tools/publish` | `POST /aim/nodes/{id}/tools/publish` | Publish a tool |
| `PUT /marketplace/tools/{tool_id}` | `PUT /aim/nodes/{id}/tools/{tool_id}` | Update tool metadata |
| `DELETE /marketplace/tools/{tool_id}` | `DELETE /aim/nodes/{id}/tools/{tool_id}` | Archive a tool |
| `GET /marketplace/earnings` | `GET /aim/payouts/summary?node_id={id}` | Earnings rollups |
| `GET /marketplace/earnings/history` | `GET /aim/payouts/history` | Payout history |
| `GET /marketplace/sessions` | `GET /aim/sessions?node_id={id}` | Session history (marketplace view) |
| `GET /marketplace/settlements` | `GET /aim/settlements?node_id={id}` | Settlement records |
| `GET /marketplace/trust` | `GET /aim/nodes/{id}/trust` | Trust score |
| `GET /marketplace/trust/events` | `GET /aim/nodes/{id}/trust/events` | Trust event history |
| `GET /marketplace/traces` | `GET /aim/observability/traces?node_id={id}` | Observability traces |
| `GET /marketplace/listings` | `GET /listings?node_id={id}` | Listings originated by this node |
| `GET /marketplace/discover` | `POST /aim/discover/search` | Tool discovery (buyer mode) |
| `POST /marketplace/allai` | `POST /allie/chat/agentic` | allAI proxy with context injection |

**Naming convention:** Local runtime sessions at `/api/mgmt/sessions/*` (existing). Marketplace session history at `/api/mgmt/marketplace/sessions`. The UI uses the namespace to distinguish local vs marketplace data.

**Listings vs Tools:** A "tool" is a capability registered by a node. A "listing" is a marketplace entity that may reference one or more tools. The UI treats them as linked resources: the Tools screen shows local tools with their marketplace listing status.

### 4.2 Caching Strategy

- Trust score: cache 5 minutes (slow-changing)
- Earnings: cache 1 minute
- Published tools: cache 30 seconds
- Sessions: no cache (real-time)
- allAI: no cache (conversational)

## 5. Error Taxonomy

**Mandate M5: Complete, normalized error contract.**

### 5.1 Error Response Format

All management API errors MUST follow this format. Current ad-hoc `{"error": ...}` responses must be migrated.

```json
{
  "code": "upstream_unreachable",
  "message": "Cannot connect to http://localhost:8000",
  "details": {"url": "http://localhost:8000", "timeout_ms": 3000},
  "retryable": true,
  "request_id": "req_abc123",
  "suggested_action": "Check that your model server is running"
}
```

Required fields: `code`, `message`. Optional: `details`, `retryable`, `request_id`, `suggested_action`.

### 5.2 Error Code Registry

| Code | HTTP | Category | When |
|------|------|----------|------|
| `setup_incomplete` | 412 | Precondition | Node not yet configured |
| `node_locked` | 423 | Auth | Passphrase required to unlock |
| `auth_failed` | 401 | Auth | Invalid API key or expired bearer token |
| `csrf_rejected` | 403 | Auth | Missing or invalid CSRF/origin |
| `forbidden` | 403 | Auth | Operation not permitted |
| `not_found` | 404 | Resource | Session, tool, or resource not found |
| `already_exists` | 409 | State | Keypair/resource already exists |
| `already_running` | 409 | State | Provider/consumer already started |
| `not_running` | 409 | State | Provider/consumer not started |
| `config_invalid` | 422 | Validation | Missing required field or bad value |
| `tool_validation_failed` | 422 | Validation | Schema mismatch or sample invoke failed |
| `upstream_unreachable` | 502 | Connectivity | Model endpoint not responding |
| `market_unreachable` | 502 | Connectivity | Cannot reach api.ai.market |
| `market_error` | 502 | Connectivity | Backend returned non-2xx (passthrough details in `details`) |
| `upstream_timeout` | 504 | Connectivity | Model endpoint timed out |
| `market_timeout` | 504 | Connectivity | Backend request timed out |
| `service_unavailable` | 503 | System | Node shutting down or unhealthy |
| `rate_limited` | 429 | Throttle | Too many requests |
| `internal_error` | 500 | System | Unexpected failure |

### 5.3 Backend Error Passthrough

When the node facade receives a non-2xx response from the backend, it wraps it:

```json
{
  "code": "market_error",
  "message": "Marketplace returned an error",
  "details": {"status": 403, "backend_error": "Invalid or expired token", "endpoint": "/aim/nodes/register"},
  "retryable": false,
  "suggested_action": "Check your API key in Settings"
}
```

## 6. allAI Integration Contract

**Mandate M4: Redaction, allowlist, confirmation, and failure semantics.**

### 6.1 Context Injection Rules

The node injects local context into allAI prompts. The following rules apply:

**Allowed context (sent to backend):**
- Current UI page/screen name
- Node status (healthy/locked/setup_complete — booleans only)
- Provider health (upstream_reachable, latency_ms — no URLs)
- Tool names and schemas (public information, already on marketplace)
- Error messages from last 5 failed operations
- Session counts and aggregate metrics (no peer fingerprints)

**Redacted (NEVER sent):**
- API key / bearer tokens / refresh tokens
- Ed25519 private key material
- Passphrase
- Raw config file contents (only sanitized summaries)
- Peer fingerprints or buyer identifiers
- Full log output (only last 5 error messages, truncated to 500 chars each)

**Prompt size limit:** Max 4000 tokens of injected context per request.

### 6.2 Tool Allowlist

allAI may invoke these local tools via tool_use responses:

**Read-only (auto-execute, no confirmation):**
- `inspect_local_config` — returns sanitized config summary
- `test_market_auth` — tests backend connectivity
- `scan_provider_endpoint` — discovers tool schemas from upstream
- `list_local_tools` — returns registered tool names
- `tail_recent_logs` — last 20 log lines, errors only
- `explain_last_failure` — describes most recent error

**Generative (auto-execute, returns draft for user review):**
- `generate_input_output_schema` — generates schema from endpoint inspection
- `draft_publish_payload` — drafts tool publish request
- `estimate_pricing` — suggests pricing based on marketplace data

**Mutating (REQUIRES explicit user confirmation before execution):**
- `test_tool_invocation` — sends a sample request to upstream
- `recommend_spend_cap` — suggests config change (user must confirm)
- `compare_provider_versions` — may trigger network calls

### 6.3 Confirmation Contract

For mutating tool_use, the node returns to the UI:

```json
{
  "type": "action_proposed",
  "tool": "test_tool_invocation",
  "description": "Send a sample request to your model at http://localhost:8000",
  "params": {"endpoint": "http://localhost:8000", "sample_input": {...}},
  "requires_confirmation": true
}
```

The UI shows a confirmation dialog. On user approval, the UI sends `POST /allai/confirm` with the action ID. On rejection, the conversation continues without execution.

### 6.4 Failure Semantics

- If allAI proxy call fails (network, auth, rate limit): return error to chat UI with retry button
- If tool execution fails: return error to allAI for diagnosis (loop continues)
- If allAI returns no tool_use and no text: return generic "I couldn't help with that" message
- Max tool_use loop depth: 5 iterations per user message

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
- Management plane security enforced (loopback bind + CSRF/origin validation)
- Auth chain per endpoint family fully specified with exact header names and token flows
- Registration challenge-response choreography documented
- Facade routes cover every backend capability consumed by the UI
- Local vs marketplace sessions clearly namespaced
- Listings vs Tools relationship defined
- Error taxonomy covers all UI-visible failure modes with normalized response format
- allAI redaction rules, tool allowlist, confirmation contract, and failure semantics defined
- Facade pattern validated (node never exposes raw backend URLs to UI)

## 10. R1 Review Response

MP R1 verdict: REVISE (6 findings, 5 mandates). All addressed in this revision:
- M1: Section 3.1 — loopback bind + CSRF/origin protection
- M2: Section 3.2 — exact auth per endpoint family with registration choreography
- M3: Section 4.1 — complete facade table with naming conventions
- M4: Section 6 — full allAI contract (redaction, allowlist, confirmation, failure)
- M5: Section 5 — expanded error taxonomy with 19 codes + backend passthrough
