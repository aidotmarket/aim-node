# BQ-AIM-NODE-SELLER-PUBLISH — Gate 2 Spec
## Implementation: Seller Registration Fix + Tool Publish UI

**BQ Code:** BQ-AIM-NODE-SELLER-PUBLISH
**Epic:** AIM-NODE-UI
**Phase:** 2 — Implementation
**Prerequisite:** Gate 1 approved, BQ-AIM-NODE-MGMT-API-V2 Gate 2 complete, BQ-AIM-NODE-SETUP-WIZARD Gate 2 complete
**Author:** Codex (Synthesis)

---

## Implementation Details

This Gate 2 spec is limited to the local `aim-node` codebase:

- Python registration/client changes in `aim_node/`
- Setup-finalize integration in the management API
- React replacement of the tools placeholders in `frontend/src/`

Out of scope:

- New marketplace facade routes
- ai.market backend API changes
- Buyer/discovery UX outside the seller publish flow

### Gate 1 Mandates Resolved Here

1. `MarketClient.register_node()` must stop sending raw Ed25519 bytes and always send a base64 string.
2. `MarketClient.register_node()` must match the real backend 2-step challenge + proof-of-possession flow shown in `tests/smoke/test_smoke_aim_node.py`.

### Existing Codebase Baseline

Relevant current files:

- `aim_node/core/market_client.py` — still implements a single `POST /nodes/register`
- `aim_node/management/routes.py` — `setup_finalize()` is the wizard integration point
- `aim_node/management/config_writer.py` — persists final config, currently no registration write-back
- `frontend/src/router.tsx` — still routes `/tools` and `/tools/:id` to placeholders
- `frontend/src/lib/api.ts` — no `put()` helper yet
- `frontend/src/pages/placeholders/ToolsPlaceholder.tsx`
- `frontend/src/pages/placeholders/ToolDetailPlaceholder.tsx`
- `aim_node/management/tools.py` and `aim_node/management/schemas.py` — local tool discovery/detail/validation contracts already exist

### Registration Flow Change

#### 1. `aim_node/core/market_client.py`

Modify:

- `MarketClient.register_node()`
- Add `MarketClient.register_challenge()`

Target behavior:

1. Normalize the caller-supplied Ed25519 public key into a base64 string.
2. `POST /api/v1/aim/nodes/register/challenge` with `{ public_key, endpoint_url }`
3. Sign the returned `challenge` with the node Ed25519 private key
4. `POST /api/v1/aim/nodes/register` with `{ public_key, endpoint_url, serial, challenge, pop_signature }`

Implementation notes:

- Accept `public_key: str | bytes` in `register_node()` and `register_challenge()`
- If `public_key` is `bytes`, encode with `base64.b64encode(...).decode("ascii")`
- If `public_key` is already `str`, treat it as the transport value and do not double-encode
- Use `DeviceCrypto.sign()` for challenge signing
- Encode `pop_signature` with `base64.urlsafe_b64encode(...).decode("ascii")` to match the smoke test contract
- Keep auth header handling inside `_request()` unchanged

Suggested signatures:

```python
async def register_challenge(
    self,
    public_key: str | bytes,
    endpoint_url: str,
) -> dict[str, Any]:
    ...

async def register_node(
    self,
    public_key: str | bytes,
    endpoint_url: str,
    serial: str,
    private_key: ed25519.Ed25519PrivateKey,
) -> dict[str, Any]:
    ...
```

#### 2. `aim_node/management/routes.py`

`setup_finalize()` is the existing integration point and remains the only setup entrypoint for this BQ.

Required change:

- After `finalize_setup(...)` writes the local config and before autostart, perform seller registration when `mode in ("provider", "both")`
- Load the node keypair from the existing keystore using `_crypto_for(...)`
- Read `core.node_serial` and provider endpoint URL from config
- Call `MarketClient.register_node(...)`
- Persist the returned backend `node_id` into `config.toml` under `core.node_id`

This is required because the publish UI depends on the existing marketplace facade, and `MarketplaceFacade.create()` already requires `config.node_id`.

Suggested helper extraction:

- Add a small internal helper in `aim_node/management/routes.py` or `aim_node/management/config_writer.py` to persist `core.node_id`
- Rebuild `request.app.state.facade` after registration so `/api/mgmt/marketplace/*` is immediately available on the next request

#### 3. `aim_node/management/config_writer.py`

Minimal extension only:

- add a helper to persist `core.node_id`
- do not redesign `finalize_setup()`

Suggested helper:

```python
def persist_node_id(data_dir: Path, node_id: str) -> None:
    config = read_config(data_dir)
    config.setdefault("core", {})
    config["core"]["node_id"] = node_id
    write_config(data_dir, config)
```

#### 4. Registration Error Handling

Use existing normalized management errors. Map failures as:

- challenge/register connectivity failure: `market_unreachable` or `market_timeout`
- non-2xx marketplace response: `market_error`
- malformed payload or missing `challenge`/`node_id`: `internal_error`

`setup_finalize()` should fail the request if seller registration fails for `provider` or `both`; the UI should not report setup success while the seller node is unusable for publish.

### Frontend Page Replacement

Replace the placeholder pages with real seller publish pages:

```text
frontend/src/pages/tools/
├── ToolsListPage.tsx
├── ToolDetailPage.tsx
└── PublishFlow.tsx
```

Supporting files:

```text
frontend/src/hooks/
├── useLocalTools.ts
├── useMarketplaceTools.ts
└── usePublishFlow.ts

frontend/src/components/tools/
├── ToolStatusBadge.tsx
├── ToolSchemaPanel.tsx
└── PublishSummaryCard.tsx

frontend/src/types/marketplace.ts
```

Modify:

- `frontend/src/router.tsx`
- `frontend/src/lib/api.ts`
- `frontend/src/components/AllAIChat.tsx` only if Slice D ships

### API Client Extension

`frontend/src/lib/api.ts` must add:

```typescript
async put<T>(path: string, body?: unknown): Promise<T>
```

This is needed for the existing `PUT /api/mgmt/marketplace/tools/{tool_id}` route.

## API Contracts

This BQ uses only existing local contracts plus the registration fix above.

### Python Registration Contract

Challenge request:

```json
POST /api/v1/aim/nodes/register/challenge
{
  "public_key": "<base64-ed25519-public-key>",
  "endpoint_url": "https://upstream.example.com/mcp"
}
```

Challenge response:

```json
{
  "challenge": "..."
}
```

Register request:

```json
POST /api/v1/aim/nodes/register
{
  "public_key": "<base64-ed25519-public-key>",
  "endpoint_url": "https://upstream.example.com/mcp",
  "serial": "<core.node_serial>",
  "challenge": "...",
  "pop_signature": "<base64url-signature>"
}
```

Register response fields consumed locally:

```typescript
interface RegisterNodeResponse {
  node_id: string;
  api_key?: string;
  status?: string;
  created_at?: string;
}
```

Only `node_id` is mandatory for this BQ. Do not spec or require any ai.market-side contract change.

### Frontend Local Tool Contracts

Existing local-tool responses from `aim_node/management/schemas.py`:

```typescript
export interface ToolSummary {
  tool_id: string;
  name: string;
  version: string;
  description: string;
  validation_status: string;
  last_scanned_at: string;
}

export interface ToolListResponse {
  tools: ToolSummary[];
  scanned_at: string | null;
}

export interface ToolDetailResponse {
  tool_id: string;
  name: string;
  version: string;
  description: string;
  input_schema: Record<string, unknown>;
  output_schema: Record<string, unknown>;
  validation_status: string;
  last_scanned_at: string;
  last_validated_at: string | null;
}

export interface ToolValidationResponse {
  tool_id: string;
  status: string;
  latency_ms: number;
  error: string | null;
}
```

### Frontend Marketplace View Models

Add `frontend/src/types/marketplace.ts`:

```typescript
export type PublishStatus = 'not_published' | 'draft' | 'live';

export interface MarketplaceTool {
  tool_id: string;
  listing_id?: string;
  status: PublishStatus;
  title?: string;
  description?: string;
  category?: string;
  tags?: string[];
  price_usd?: number;
  free_tier_calls?: number;
  rate_limit_per_minute?: number;
  published_at?: string;
  updated_at?: string;
}

export interface ToolListItemViewModel extends ToolSummary {
  publish_status: PublishStatus;
  listing_id?: string;
  price_usd?: number;
  category?: string;
  tags?: string[];
}
```

The page layer owns normalization from existing facade payloads into these view models. Do not change the facade contract in this spec.

## Component Specs

### `frontend/src/pages/tools/ToolsListPage.tsx`

Purpose:

- Replace `ToolsPlaceholder`
- Show the locally discovered tools list, joined with marketplace publish state

Responsibilities:

- Fetch local tools from `GET /api/mgmt/tools`
- Fetch marketplace tool state from existing `GET /api/mgmt/marketplace/tools`
- Merge both by `tool_id`
- Trigger discovery with `POST /api/mgmt/tools/discover`
- Provide filter chips for `all`, `not_published`, `draft`, `live`
- Route to `/tools/:id`

Component interface:

```typescript
interface ToolsListPageState {
  items: ToolListItemViewModel[];
  isLoading: boolean;
  isRefreshing: boolean;
  error: string | null;
  activeFilter: 'all' | PublishStatus;
}
```

UI requirements:

- reuse `PageHeader`, `Card`, `Badge`, `Button`, `EmptyState`
- header action: `Discover Tools`
- card rows show name, description, version, validation status, publish status, price summary
- empty state when `tools.length === 0`

### `frontend/src/pages/tools/ToolDetailPage.tsx`

Purpose:

- Replace `ToolDetailPlaceholder`
- Show schema, validation, and marketplace publish controls for one tool

Responsibilities:

- Fetch `GET /api/mgmt/tools/{tool_id}`
- Fetch marketplace tools and derive the selected tool’s marketplace state
- Trigger validation with `POST /api/mgmt/tools/{tool_id}/validate`
- Mount `PublishFlow`
- Show published metadata and destructive `Unpublish` action via existing `DELETE /api/mgmt/marketplace/tools/{tool_id}`

Component interface:

```typescript
interface ToolDetailPageProps {
  toolId?: string;
}

interface ToolDetailViewModel {
  tool: ToolDetailResponse;
  marketplace: MarketplaceTool | null;
  canPublish: boolean;
  lastValidationLabel: string | null;
}
```

UI requirements:

- top section with tool name and badges
- schema section split into input/output panels
- raw JSON viewer in a scrollable `Card`
- validation result card with pass/fail state and latency
- publish action area:
  - if not published: render `PublishFlow`
  - if published: render listing summary plus `Edit` and `Unpublish`

### `frontend/src/pages/tools/PublishFlow.tsx`

Purpose:

- Inline multistep publish form embedded inside `ToolDetailPage`

Steps:

1. Tool details
2. Pricing
3. Confirm
4. Go live result

Component interfaces:

```typescript
export interface PublishDetailsForm {
  title: string;
  description: string;
  category: string;
  tags: string[];
}

export interface PublishPricingForm {
  price_usd: string;
  free_tier_calls: string;
  rate_limit_per_minute: string;
}

export interface PublishFlowProps {
  tool: ToolDetailResponse;
  marketplace: MarketplaceTool | null;
  onPublished: () => void;
}

export interface UsePublishFlowResult {
  step: 'details' | 'pricing' | 'confirm';
  details: PublishDetailsForm;
  pricing: PublishPricingForm;
  errors: Record<string, string>;
  setDetails: (patch: Partial<PublishDetailsForm>) => void;
  setPricing: (patch: Partial<PublishPricingForm>) => void;
  nextStep: () => void;
  prevStep: () => void;
  submitDraft: () => Promise<void>;
  submitLive: () => Promise<void>;
  isSubmitting: boolean;
}
```

Publish semantics using existing facade routes:

- create/update draft metadata with `PUT /api/mgmt/marketplace/tools/{tool_id}` when a marketplace record already exists
- first-time publish uses existing `POST /api/mgmt/marketplace/tools/publish`
- the payload shape sent by the frontend should be adapted to the existing facade/backend contract in the page hook layer, not encoded into the route spec here

Validation rules:

- `title`: required, max 80 chars
- `description`: required, max 500 chars
- `category`: required
- `tags`: max 5, normalized trim/lowercase
- `price_usd`: required, numeric, `>= 0.001`
- `free_tier_calls`: integer, `>= 0`
- `rate_limit_per_minute`: integer, `>= 0`

### Optional Slice D: allAI Publish Context

If shipped, extend local allAI context only.

Files:

- `frontend/src/components/AllAIChat.tsx`
- `aim_node/management/allai.py`
- `tests/test_management_allai.py`
- `frontend/src/components/__tests__/AllAIChat.test.tsx`

Add optional props:

```typescript
export interface AllAIContextPayload {
  screen: 'tools_list' | 'tool_detail' | 'publish_flow';
  tool_id?: string;
  tool_name?: string;
  publish_status?: PublishStatus;
  draft?: Partial<PublishDetailsForm & PublishPricingForm>;
}

interface AllAIChatProps {
  context?: AllAIContextPayload;
}
```

This slice remains optional because seller publish works without it.

## State Management

Use React Query for remote state and keep draft form state local to `PublishFlow`.

### New hooks

`frontend/src/hooks/useLocalTools.ts`

```typescript
interface UseLocalToolsResult {
  tools: ToolSummary[];
  scannedAt: string | null;
  isLoading: boolean;
  error: ApiError | null;
  discover: () => Promise<void>;
  isDiscovering: boolean;
}
```

Queries/mutations:

- query key: `['tools', 'local']`
- query: `GET /tools`
- mutation: `POST /tools/discover`
- invalidate `['tools', 'local']` after discover

`frontend/src/hooks/useMarketplaceTools.ts`

```typescript
interface UseMarketplaceToolsResult {
  tools: MarketplaceTool[];
  isLoading: boolean;
  error: ApiError | null;
  refresh: () => Promise<void>;
  publishTool: (payload: unknown) => Promise<void>;
  updateTool: (toolId: string, payload: unknown) => Promise<void>;
  deleteTool: (toolId: string) => Promise<void>;
}
```

Queries/mutations:

- query key: `['tools', 'marketplace']`
- query: `GET /marketplace/tools`
- mutation: `POST /marketplace/tools/publish`
- mutation: `PUT /marketplace/tools/{tool_id}`
- mutation: `DELETE /marketplace/tools/{tool_id}`

`frontend/src/hooks/usePublishFlow.ts`

- pure UI hook for step progression and form validation
- no direct network calls; page container wires mutations into it

### Router updates

Modify `frontend/src/router.tsx`:

- `/tools` → `ToolsListPage`
- `/tools/:id` → `ToolDetailPage`

No new top-level routes are required.

### Node store

No Zustand expansion is required for this BQ. Seller publish state is page-scoped and query-backed, not global app state.

## Slice Plan

### Slice A: Registration Fix + Tests

Scope:

- `aim_node/core/market_client.py`
- `aim_node/management/routes.py`
- `aim_node/management/config_writer.py`
- Python tests only

Deliverables:

- 2-step challenge + PoP registration
- public key base64 normalization
- finalize integration for `provider` and `both`
- `core.node_id` persistence

Files:

- modify `aim_node/core/market_client.py`
- modify `aim_node/management/routes.py`
- modify `aim_node/management/config_writer.py`
- add or extend `tests/test_slice2.py`
- add `tests/test_management_finalize_registration.py`

Ship criteria:

- setup finalize fails on seller registration failure
- setup finalize writes `core.node_id` on success
- smoke-contract parity covered in unit/integration tests

### Slice B: Tools List + Tool Detail

Scope:

- replace placeholders
- render local tools and existing marketplace state
- validation UX

Files:

- add `frontend/src/pages/tools/ToolsListPage.tsx`
- add `frontend/src/pages/tools/ToolDetailPage.tsx`
- add `frontend/src/components/tools/ToolStatusBadge.tsx`
- add `frontend/src/components/tools/ToolSchemaPanel.tsx`
- add `frontend/src/hooks/useLocalTools.ts`
- add `frontend/src/hooks/useMarketplaceTools.ts`
- add `frontend/src/types/marketplace.ts`
- modify `frontend/src/router.tsx`

Tests:

- add `frontend/src/pages/tools/__tests__/ToolsListPage.test.tsx`
- add `frontend/src/pages/tools/__tests__/ToolDetailPage.test.tsx`
- extend `frontend/src/__tests__/routes.test.tsx`

### Slice C: Publish Flow + Pricing + Go Live

Scope:

- inline publish flow in tool detail
- pricing validation
- publish/update/delete mutations against existing facade routes

Files:

- add `frontend/src/pages/tools/PublishFlow.tsx`
- add `frontend/src/hooks/usePublishFlow.ts`
- add `frontend/src/components/tools/PublishSummaryCard.tsx`
- modify `frontend/src/lib/api.ts`
- modify `frontend/src/pages/tools/ToolDetailPage.tsx`

Tests:

- add `frontend/src/pages/tools/__tests__/PublishFlow.test.tsx`
- add `frontend/src/pages/tools/__tests__/ToolPublish.integration.test.tsx`
- extend `frontend/src/lib/__tests__/api.test.ts`

### Slice D: Optional allAI Publish Context

Scope:

- contextual allAI help on tools pages

Files:

- modify `frontend/src/components/AllAIChat.tsx`
- modify `aim_node/management/allai.py`
- extend `tests/test_management_allai.py`
- extend `frontend/src/components/__tests__/AllAIChat.test.tsx`

Ship criteria:

- entirely optional
- must not block Slices A-C

## Test Plan

### Slice A Tests

Unit:

- `MarketClient.register_challenge()` sends base64 public key string even when called with raw bytes
- `MarketClient.register_node()` performs challenge then register in order
- `MarketClient.register_node()` signs the returned challenge and sends `pop_signature`
- `MarketClient.register_node()` surfaces malformed payload errors when `challenge` is missing

Recommended locations:

- extend `tests/test_slice2.py` for direct `MarketClient` transport tests
- add `tests/test_management_finalize_registration.py` for finalize integration

Integration:

- `setup_finalize()` in `provider` mode loads the keystore, registers the seller node, persists `core.node_id`, and returns `{"ok": true}`
- `setup_finalize()` in `both` mode behaves the same
- `setup_finalize()` in `consumer` mode does not call seller registration
- seller registration failure returns normalized error and does not persist `core.node_id`

### Slice B Tests

Component tests using existing Vitest patterns from `frontend/src/pages/setup/__tests__/*`:

- tools page renders loading, empty, and populated states
- discover action refreshes local tool list
- local + marketplace payloads are merged by `tool_id`
- tool detail shows input/output schemas and validation status
- validate button invokes `POST /api/mgmt/tools/{id}/validate` and refreshes detail state
- route `/tools/:id` renders the real detail page

Recommended locations:

- `frontend/src/pages/tools/__tests__/ToolsListPage.test.tsx`
- `frontend/src/pages/tools/__tests__/ToolDetailPage.test.tsx`
- `frontend/src/__tests__/routes.test.tsx`

### Slice C Tests

Component/unit:

- details step validation
- pricing step numeric validation
- confirm step summary rendering
- draft save submits normalized payload
- go-live action submits publish mutation and calls `onPublished`
- delete/unpublish flow confirms before mutation

Integration:

- happy path: discover/tool detail/publish/update/live state refresh
- error path: publish mutation error renders inline normalized message

Recommended locations:

- `frontend/src/pages/tools/__tests__/PublishFlow.test.tsx`
- `frontend/src/pages/tools/__tests__/ToolPublish.integration.test.tsx`
- `frontend/src/lib/__tests__/api.test.ts` for new `put()`

### Slice D Tests

- allAI chat request includes seller publish context when mounted from `ToolDetailPage`
- context is omitted on pages that do not pass it

### Test Count Target

- Slice A: 8-12 tests
- Slice B: 10-14 tests
- Slice C: 10-14 tests
- Slice D: 4-6 tests

Total target: 28-46 tests

## Risk & Dependencies

### Risks

1. `register_node()` currently has no caller that passes a private key.
   Resolution: Gate 2 explicitly wires seller registration through `setup_finalize()`, which already has access to the local keystore.

2. The existing marketplace facade requires `config.node_id`, but setup currently persists only `node_serial`.
   Resolution: persist backend `node_id` immediately after successful seller registration.

3. Existing marketplace tool payload shape may not match the frontend view model one-to-one.
   Resolution: normalize in the hook/page layer and keep route contracts unchanged.

4. `api.ts` lacks `put()`, which blocks metadata/pricing updates.
   Resolution: add `put()` in Slice C and cover it with the existing `frontend/src/lib/__tests__/api.test.ts` pattern.

5. Setup finalize currently reports success before any seller-specific verification.
   Resolution: for provider-capable modes, registration becomes part of finalize success criteria.

### Dependencies

- Depends on the current setup wizard finalize path remaining `POST /api/mgmt/setup/finalize`
- Depends on local tool endpoints in `aim_node/management/tools.py`
- Depends on the existing marketplace facade routes in `aim_node/management/marketplace.py`
- Depends on keystore access through `DeviceCrypto`

### Explicit Non-Goals

- No new facade route design
- No direct frontend calls to ai.market
- No ai.market backend contract changes
- No redesign of the setup wizard UI outside the finalize integration point

