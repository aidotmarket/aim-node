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
