# BQ-AIM-NODE-SELLER-PUBLISH — Gate 1 Spec
## Register, Create Tool, Price, Publish to Marketplace

**BQ Code:** BQ-AIM-NODE-SELLER-PUBLISH
**Epic:** AIM-NODE-UI
**Phase:** 2
**Priority:** P0
**Estimated Hours:** 20
**Depends On:** BQ-AIM-NODE-MGMT-API-V2 (Gate 4 ✅), BQ-AIM-NODE-SETUP-WIZARD (Gate 1+)
**Author:** Vulcan (S438)

---

## 1. Problem Statement

After completing the Setup Wizard, a seller has a running AIM Node connected to ai.market with an upstream MCP endpoint. But there is no UI to:

1. Register the node as a seller on the marketplace
2. Discover what tools the upstream MCP server exposes
3. Create a marketplace listing for a tool
4. Set pricing (per-call, free tier, rate limits)
5. Publish a tool to make it discoverable and purchasable by buyers

The management API already has local tool discovery endpoints (`/tools`, `/tools/discover`, `/tools/{id}/validate`, `/tools/{id}`). The ai.market backend has seller APIs for node registration, listing CRUD, and publish. This BQ builds the frontend flow that connects local tool discovery to marketplace publishing, replacing the `ToolsPlaceholder` and `ToolDetailPlaceholder` pages.

## 2. User Stories

| ID | Story | Acceptance |
|----|-------|------------|
| SP-1 | As a seller, I see my tools page showing locally discovered tools and their marketplace status | Tools page shows list from `GET /tools`; each tool shows name, schema summary, publish status (draft/live/unpublished) |
| SP-2 | As a seller, I can scan my upstream for available tools | "Discover Tools" button calls `POST /tools/discover`; loading state during scan; new tools appear in list |
| SP-3 | As a seller, I can select a tool and see its schema details | Tool detail page shows full JSON schema, input/output types, last validation result |
| SP-4 | As a seller, I can validate a tool works before publishing | "Validate" button calls `POST /tools/{id}/validate`; shows pass/fail with response details |
| SP-5 | As a seller, I can create a marketplace listing for a local tool | Publish flow: name, description, category, tags → creates draft listing via backend API |
| SP-6 | As a seller, I can set pricing for my listing | Pricing form: per-call price (USD), free tier calls/month, rate limit (calls/min); saved to draft |
| SP-7 | As a seller, I can publish a draft listing to make it live | "Go Live" button submits listing to marketplace; confirmation dialog; status updates to "live" |
| SP-8 | As a seller, I can unpublish a live listing | "Unpublish" button with confirmation; status reverts to "draft"; existing sessions wind down |
| SP-9 | As a seller on any publish step, I can ask allAI for guidance | AllAIChat widget available; context includes current tool and publish state |

## 3. Architecture

### 3.1 Page Components (replace placeholders)

```
frontend/src/pages/tools/
├── ToolsListPage.tsx         # List of discovered local tools + marketplace status
├── ToolDetailPage.tsx        # Schema view, validation, publish actions
└── PublishFlow.tsx            # Multi-step inline: listing details → pricing → confirm
```

### 3.2 Data Flow

Local tool discovery happens against the upstream MCP server via the management API. Marketplace operations (register, create listing, pricing, publish) are proxied through the management API's marketplace facade to `api.ai.market`. The frontend never calls `api.ai.market` directly.

### 3.3 Marketplace Facade Endpoints (Management API)

These endpoints proxy to `api.ai.market` using the seller's API key (stored during setup). They may already exist from MGMT-API-V2's marketplace facade design; if not, they're new for this BQ's Gate 2.

| Method | Local Path | Proxies To | Purpose |
|--------|-----------|------------|---------|
| POST | `/api/mgmt/marketplace/register` | `POST /api/v1/aim/nodes/register` | Register this node as a seller |
| GET | `/api/mgmt/marketplace/node` | `GET /api/v1/aim/nodes/me` | Get node's marketplace profile |
| POST | `/api/mgmt/marketplace/listings` | `POST /api/v1/aim/listings` | Create draft listing |
| GET | `/api/mgmt/marketplace/listings` | `GET /api/v1/aim/listings?node_id=self` | List this node's listings |
| PUT | `/api/mgmt/marketplace/listings/{id}` | `PUT /api/v1/aim/listings/{id}` | Update listing details |
| PUT | `/api/mgmt/marketplace/listings/{id}/pricing` | `PUT /api/v1/aim/listings/{id}/pricing` | Set pricing |
| POST | `/api/mgmt/marketplace/listings/{id}/publish` | `POST /api/v1/aim/listings/{id}/publish` | Go live |
| POST | `/api/mgmt/marketplace/listings/{id}/unpublish` | `POST /api/v1/aim/listings/{id}/unpublish` | Take offline |

### 3.4 State Management

Extend the existing React Query pattern:

```typescript
// hooks/useTools.ts — local tool discovery
useQuery(['tools'], () => api.get('/tools'))
useMutation(() => api.post('/tools/discover'))
useMutation((id) => api.post(`/tools/${id}/validate`))

// hooks/useListings.ts — marketplace listings
useQuery(['listings'], () => api.get('/marketplace/listings'))
useMutation((data) => api.post('/marketplace/listings', data))
useMutation(({ id, pricing }) => api.put(`/marketplace/listings/${id}/pricing`, pricing))
useMutation((id) => api.post(`/marketplace/listings/${id}/publish`))
```

### 3.5 Publish Flow (Inline Multi-Step)

The publish flow is not a separate wizard — it's an inline expansion on the tool detail page:

1. **Link to Marketplace** — Select local tool → "Publish to Marketplace" button
2. **Listing Details** — Name (pre-filled from tool schema), description, category (dropdown), tags
3. **Pricing** — Per-call price, free tier, rate limit
4. **Confirm** — Review summary → "Go Live"

Steps are collapsible accordion panels. User can edit any completed step before confirming. This avoids a separate route/wizard for what should feel like a quick action.

### 3.6 Backend Dependency: Seller APIs

This BQ assumes the ai.market backend exposes seller APIs for node registration and listing CRUD. Current state of these APIs needs verification at Gate 2 spec time. If they don't exist, a companion BQ (BQ-AIM-BACKEND-SELLER-APIS) will need to ship first or in parallel.

**Known backend endpoints (from OpenAPI):**
- `/api/v1/aim/nodes/` — node registration exists (from BQ-AIM-NODE-CORE)
- `/api/v1/public/listings` — public listing read exists
- Seller listing CRUD and pricing endpoints — **verify existence**

## 4. UI Design

### 4.1 Tools List Page

| Element | Description |
|---------|-------------|
| Page header | "Tools" + "Discover Tools" action button |
| Tool cards | Grid or list of discovered tools, each showing: name, description (truncated), schema type count, marketplace status badge |
| Status badges | `Draft` (yellow), `Live` (green), `Not Published` (gray), `Validating` (blue pulse) |
| Empty state | "No tools discovered yet. Click Discover Tools to scan your upstream endpoint." |
| Filter/sort | Filter by status; sort by name or status |

### 4.2 Tool Detail Page

| Section | Content |
|---------|--------|
| Header | Tool name, status badge, last validated timestamp |
| Schema | Collapsible JSON schema viewer (input params, output type) |
| Validation | "Run Validation" button, last result (pass/fail + response preview) |
| Marketplace | If not published: "Publish to Marketplace" button → expand publish flow. If published: listing summary + "Edit" / "Unpublish" actions |

### 4.3 Publish Flow (Accordion)

Three collapsible panels stacked vertically within the tool detail page:

**Panel 1: Listing Details**
- Name (text input, pre-filled from tool `name`)
- Description (textarea, 500 char max)
- Category (select: Data Processing, ML Inference, Code Tools, Utilities, Other)
- Tags (tag input, max 5)

**Panel 2: Pricing**
- Per-call price (number input, USD, min $0.001)
- Free tier (number input, calls/month, 0 = no free tier)
- Rate limit (number input, calls/minute, 0 = unlimited)

**Panel 3: Confirm & Publish**
- Summary card: tool name, price, free tier, rate limit
- "Go Live" primary button + "Save as Draft" secondary button
- Confirmation dialog before publish: "This will make [Tool Name] available to all marketplace buyers."

### 4.4 Error States

- Discovery failure: inline error with retry button
- Validation failure: show error details + "Try Again"
- Backend API unreachable: banner with "Cannot reach ai.market — check your connection"
- Listing creation failure: field-level validation errors from backend

## 5. Test Strategy

| Layer | Scope | Count (est.) |
|-------|-------|-------------|
| Unit | Tool list rendering, detail page sections, publish flow form validation, pricing validation | 15–20 |
| Integration | Full discover → validate → publish flow with mocked APIs (happy + error paths) | 8–10 |
| Hook | useTools and useListings hooks with mocked API responses | 5–8 |
| a11y | Accordion keyboard nav, form labels, status announcements | 3–5 |

**Total estimated: 31–43 tests**

### 5.1 Key Test Scenarios

- Discover finds 0 tools → empty state renders correctly
- Discover finds 3 tools → all render with correct schemas
- Validate passes → success state, "Publish" enabled
- Validate fails → error details shown, "Publish" still available (validation is advisory)
- Publish happy path → status changes from "Not Published" → "Draft" → "Live"
- Unpublish → status reverts, confirmation dialog appears first
- Backend 401 (expired API key) → redirect to Settings to re-authenticate

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Backend seller APIs may not exist yet | High | Verify at Gate 2; if missing, scope companion BQ or stub with mock responses |
| Upstream MCP endpoint may expose 50+ tools | Medium | Paginate tool list; lazy-load schemas; consider search/filter |
| Pricing model may change | Low | Pricing form is a simple component — easy to extend with new fields |
| Category list needs marketplace alignment | Low | Fetch categories from backend API if available; fallback to hardcoded list |

## 7. Out of Scope

- Node registration flow if node is not yet registered (assumes Setup Wizard handles initial connection)
- Buyer-side tool discovery UI (separate BQ)
- Revenue/earnings display for published tools (BQ-AIM-NODE-EARNINGS)
- Tool analytics (calls, latency, error rate per tool) — future BQ
- Listing versioning / update-in-place for live tools
- Bulk publish (one tool at a time for V1)
- allAI copilot intelligence for publish guidance (BQ-AIM-NODE-ALLAI-COPILOT)

## 8. Definition of Done

- [ ] ToolsListPage replaces ToolsPlaceholder with real content
- [ ] ToolDetailPage replaces ToolDetailPlaceholder with schema view + actions
- [ ] Discover flow scans upstream and populates tool list
- [ ] Validate flow tests a tool and shows results
- [ ] Publish flow creates listing, sets pricing, goes live
- [ ] Unpublish flow takes a listing offline with confirmation
- [ ] Status badges reflect real marketplace state
- [ ] All tests pass (target: 35+)
- [ ] No TypeScript errors, no ESLint warnings
- [ ] Placeholder pages removed for tool routes

---

## R2 Addendum — Gate 1 R1 REJECT Resolution (S439)

**R1 Findings from MP (S438):**
1. CRITICAL: Marketplace facade endpoints don't exist in aim-node
2. MAJOR: Backend dependency deferred
3. MAJOR: Tools schema lacks marketplace linkage
4. MAJOR: node_id vs node_serial registration gap

### Finding 1 Resolution: Facade Endpoints DO Exist

The R1 review found that the facade endpoints in Section 3.3 don't exist. The endpoints DO exist but were listed with wrong paths/methods. Here are the **actual routes** from `aim_node/management/app.py` and `aim_node/management/marketplace.py` (verified at commit 7728945):

**Local Tool Management (already existed pre-BQ):**

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| GET | `/api/mgmt/tools` | `tools_list_local` | List locally discovered tools |
| POST | `/api/mgmt/tools/discover` | `tools_discover` | Scan upstream MCP for tools |
| GET | `/api/mgmt/tools/{tool_id}` | `tool_detail` | Get tool detail + schema |
| POST | `/api/mgmt/tools/{tool_id}/validate` | `tools_validate` | Validate tool works |

**Marketplace Facade (proxies to api.ai.market via MarketplaceFacade):**

| Method | Path | Backend Route | Purpose |
|--------|------|---------------|---------|
| GET | `/api/mgmt/marketplace/node` | `/aim/nodes/mine` | Node's marketplace profile |
| GET | `/api/mgmt/marketplace/tools` | `/aim/nodes/{node_id}/tools` | Marketplace-registered tools |
| POST | `/api/mgmt/marketplace/tools/publish` | `/aim/nodes/{node_id}/tools/publish` | Publish tool(s) to marketplace |
| PUT | `/api/mgmt/marketplace/tools/{tool_id}` | `/aim/nodes/{node_id}/tools/{tool_id}` | Update tool metadata/pricing |
| DELETE | `/api/mgmt/marketplace/tools/{tool_id}` | `/aim/nodes/{node_id}/tools/{tool_id}` | Remove tool from marketplace |
| GET | `/api/mgmt/marketplace/listings` | `/listings` | Node's marketplace listings |
| POST | `/api/mgmt/marketplace/discover` | `/aim/discover/search` | Search marketplace |

**Section 3.3 in the original spec is REPLACED by the table above.** The original assumed listing-centric CRUD (`/marketplace/listings`, `/marketplace/listings/{id}/publish`). The actual flow is tool-centric: publish tools directly, not create listings as a separate step.

### Finding 2 Resolution: Backend Dependency Complete

BQ-AIM-BACKEND-SELLER-APIS completed Gate 4 in S437. The backend endpoints at `api.ai.market` that the facade proxies to are live and verified. No deferred dependency.

### Finding 3 Resolution: Tool → Marketplace Linkage

The linkage exists through two parallel endpoints:
- **Local tools:** `GET /api/mgmt/tools` returns `ToolListResponse` → `ToolSummary` objects with `tool_id`, `name`, `version`, `validation_status`
- **Marketplace tools:** `GET /api/mgmt/marketplace/tools` returns the marketplace-side view with publish status, pricing, listing metadata

The frontend joins these by `tool_id` — local tools show local state (schema, validation), marketplace tools show publish state (live/draft/unpublished, pricing). The ToolsListPage merges both views.

### Finding 4 Resolution: node_id vs node_serial

- `node_serial` is the local UUID generated during setup (stored in `config.toml` under `core.node_serial`)
- `node_id` is the backend-assigned UUID returned when the node first authenticates with api.ai.market
- The `MarketplaceFacade` requires `node_id` to be set in config (see `facade.py` line ~42: raises if `config.node_id` is None)
- Node registration happens implicitly during the first authenticated API call after setup finalize — the facade's `AuthService` handles this
- No explicit `/register` endpoint is needed in the frontend flow

### Revised Architecture: Publish Flow

The publish flow is simpler than originally spec'd:

1. **Discover:** User clicks "Discover Tools" → `POST /api/mgmt/tools/discover` → upstream scan populates local tool list
2. **Validate:** User selects a tool → `POST /api/mgmt/tools/{tool_id}/validate` → confirms tool responds correctly
3. **Publish:** User clicks "Publish" on a validated tool → fills in metadata (description, tags, pricing) → `POST /api/mgmt/marketplace/tools/publish` with tool details
4. **Update:** User can update pricing/metadata → `PUT /api/mgmt/marketplace/tools/{tool_id}`
5. **Unpublish:** User clicks "Remove" → `DELETE /api/mgmt/marketplace/tools/{tool_id}`

There is no separate "create listing" → "set pricing" → "go live" multi-step. Publishing is a single action with metadata attached. The allAI copilot can help generate descriptions and suggest pricing during step 3.

### Updated User Stories

Replace SP-5 through SP-8 with:

| ID | Story | Acceptance |
|----|-------|------------|
| SP-5 | As a seller, I can publish a validated tool to the marketplace | Publish form: description, tags, pricing (per-call USD) → calls `POST /api/mgmt/marketplace/tools/publish` → tool appears in marketplace |
| SP-6 | As a seller, I can update a published tool's metadata or pricing | Edit form pre-filled from `GET /api/mgmt/marketplace/tools` → saves via `PUT /api/mgmt/marketplace/tools/{tool_id}` |
| SP-7 | As a seller, I can remove a tool from the marketplace | "Remove" button + confirmation → `DELETE /api/mgmt/marketplace/tools/{tool_id}` |

SP-1 through SP-4 and SP-9 remain unchanged.

---

## R3 Addendum — Finding 4 Final Resolution (S439)

### The Gap

`finalize_setup()` writes `core.node_serial` (local UUID) to config.toml but never calls `MarketClient.register_node()` and never writes `core.node_id` (backend-assigned UUID). Without `node_id`, `MarketplaceFacade.create()` raises (facade.py:44), `app.state.facade` stays `None`, and all marketplace routes return 412.

`MarketClient.register_node(public_key, endpoint_url, serial)` → `POST /nodes/register` exists but is never invoked in the setup or publish flow.

### Resolution: New `/api/mgmt/marketplace/register` route

This BQ adds a registration route to the management API that:
1. Calls `MarketClient.register_node()` with the node's public key, endpoint URL, and serial
2. Writes the returned `node_id` to `config.toml` under `core.node_id`
3. Re-initializes `app.state.facade` with the updated config

**New route:**

| Method | Path | Purpose |
|--------|------|---------|
| POST | `/api/mgmt/marketplace/register` | Register node with ai.market, persist node_id, init facade |

**Handler implementation (new file or added to marketplace.py):**

```python
async def marketplace_register(request: Request) -> JSONResponse:
    state = request.app.state.store
    data_dir: Path = state._data_dir
    
    # 1. Load config and build a temporary MarketClient
    raw_config = read_config(data_dir)
    core_cfg = load_core_config(raw_config)
    if core_cfg is None:
        return _facade_unavailable()
    
    # 2. Get public key from keystore
    crypto = _crypto_for(data_dir, passphrase=state.get_passphrase() or "")
    _, ed_pub, _, _ = crypto.get_or_create_keypairs()
    
    # 3. Call register_node
    auth = AuthService(core_cfg)
    client = MarketClient(core_cfg, auth_service=auth)
    result = await client.register_node(
        public_key=ed_pub,
        endpoint_url=core_cfg.upstream_url or "",
        serial=core_cfg.node_serial,
    )
    
    # 4. Persist node_id to config
    node_id = result.get("node_id") or result.get("id")
    if not node_id:
        err = make_error(ErrorCode.MARKET_ERROR, "Registration succeeded but no node_id returned")
        return JSONResponse(err.model_dump(exclude_none=True), status_code=502)
    
    raw_config.setdefault("core", {})["node_id"] = node_id
    write_config(data_dir, raw_config)
    
    # 5. Re-init facade
    updated_cfg = load_core_config(read_config(data_dir))
    request.app.state.facade = MarketplaceFacade.create(updated_cfg)
    
    return JSONResponse({"node_id": node_id, "registered": True})
```

**Mount in app.py:**
```python
Route("/api/mgmt/marketplace/register", marketplace_register, methods=["POST"]),
```

### Updated Frontend Flow

The ToolsListPage checks facade availability on mount:
1. Call `GET /api/mgmt/marketplace/node` — if 412 (facade unavailable), show registration CTA
2. User clicks "Register Node" → `POST /api/mgmt/marketplace/register`
3. On success, facade is initialized, page reloads marketplace tools
4. On failure, show error with retry option

This handles both first-time registration and cases where registration failed during setup (network issues, etc.).

### Why Not in Setup Wizard

Registration requires the node's keypair AND a working internet connection to api.ai.market. The setup wizard's finalize step already does a lot (write config, autostart processes). Adding registration there creates a harder failure mode — if registration fails, does finalize fail? By making registration a separate explicit step in the seller flow, we keep setup finalize simple and let the user retry registration independently.

### Updated Dependency

This BQ now has NO dependency on a separate registration mechanism. It is self-contained: the registration route is part of this BQ's Gate 2 scope.
