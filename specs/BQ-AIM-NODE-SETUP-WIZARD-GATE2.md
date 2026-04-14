# BQ-AIM-NODE-SETUP-WIZARD — Gate 2 Spec
## Implementation Detail — 4 Slices

**BQ Code:** BQ-AIM-NODE-SETUP-WIZARD
**Gate:** 2 (Implementation)
**Gate 1 Ref:** APPROVED R3 (c20a59f)
**Author:** Vulcan (S438)

---

## Slice Plan

| Slice | Scope | Est. Tests | Depends |
|-------|-------|-----------|---------|
| A | Foundation: wizard hook, step indicator, layout update, backend step persistence | 10–12 | — |
| B | Steps 0–1: Welcome/Passphrase + Keypair generation | 8–10 | A |
| C | Steps 2–4: Connection + Upstream + Review/Finalize | 10–14 | A |
| D | Unlock page + allAI context wiring + integration tests | 8–10 | A, B, C |

**Total estimated: 36–46 tests**

---

## Slice A: Foundation

### A.1 Fix `useSetupStatus` Hook

Current hook expects `{ complete, steps }`. Actual backend response (`SetupStatusResponse`):

```typescript
interface SetupStatusResponse {
  setup_complete: boolean;
  locked: boolean;
  unlocked: boolean;
  current_step: number;  // 0–5, 5 = done
}
```

Replace the hook interface and ensure React Query key is `['setup-status']`.

### A.2 New `useSetupWizard` Hook

```typescript
// frontend/src/hooks/useSetupWizard.ts
interface UseSetupWizard {
  currentStep: number;           // 0–4 (UI steps), from /setup/status
  stepStatus: Record<number, 'pending' | 'active' | 'complete' | 'error'>;
  isLoading: boolean;
  error: string | null;
  next: () => void;              // advance to currentStep + 1
  back: () => void;              // go to currentStep - 1
  goToStep: (n: number) => void; // jump to completed step
  markComplete: (step: number) => void; // after successful API call
}
```

- `currentStep` initialized from `GET /setup/status` → `current_step`
- `markComplete(step)` updates local state and calls backend to persist (see A.4)
- `next()` blocked unless current step status is `complete`
- `back()` always allowed; `goToStep(n)` only to completed steps

### A.3 StepIndicator Component

```typescript
// frontend/src/components/StepIndicator.tsx
interface StepIndicatorProps {
  steps: Array<{ label: string; status: 'pending' | 'active' | 'complete' }>;
  currentStep: number;
}
```

Horizontal stepper with 5 circles connected by lines:
- **Pending:** `border-brand-border`, `bg-white`, muted text
- **Active:** `bg-brand-primary`, white number, `text-brand-primary` label
- **Complete:** `bg-brand-success`, checkmark icon, `text-brand-success` label

Uses existing `Badge` and design tokens from UI scaffold.

### A.4 Backend: Extend Step Persistence

Currently `mark_setup_step()` is only called at step 2 (keypair) and step 5 (finalize). Add calls at each step completion:

- Step 0 (passphrase): mark_setup_step(1) after passphrase is set
- Step 1 (keypair): already calls mark_setup_step(2)
- Step 2 (connection): add mark_setup_step(3) in `setup_test_connection` on success
- Step 3 (upstream): add mark_setup_step(4) in `setup_test_upstream` on success (or config write)
- Step 4 (finalize): already calls mark_setup_complete() which sets step=5

Implementation: add `state.mark_setup_step(N)` calls in `routes.py` handlers. Also persist to config.toml via `config_writer.write_setup_step(N)`.

Note: Step 0 has no existing backend route (passphrase is passed to Step 1's keypair generation). Options:
- (a) Create a `POST /api/mgmt/setup/passphrase` endpoint that validates and stores the passphrase temporarily
- (b) Keep passphrase in React state only, pass to keypair endpoint — no step 0 persistence
- Option (b) is simpler; if the user closes the browser before step 1, they just restart. Recommend (b).

### A.5 Update SetupLayout

Widen max-width from `max-w-lg` to `max-w-2xl` to accommodate the step indicator + form content. Add the StepIndicator above the `<Outlet />`.

### A.6 Slice A Tests (10–12)

- `useSetupWizard`: initialization from API, next/back/goToStep logic, markComplete transitions (5–6 tests)
- `StepIndicator`: renders 5 steps, correct styling for pending/active/complete states (3–4 tests)
- `useSetupStatus`: corrected interface matches real API response (2 tests)

---

## Slice B: Steps 0–1 (Passphrase + Keypair)

### B.1 WelcomeStep (Step 0)

```
frontend/src/pages/setup/WelcomeStep.tsx
```

**Content:**
- Welcome header: "Welcome to AIM Node" + brief explanation
- Passphrase creation form:
  - Password input with show/hide toggle
  - Confirm password input
  - Strength indicator bar (red → yellow → green)
  - Validation: min 12 chars, 1 uppercase, 1 number
- "Continue" button (disabled until passphrase valid + confirmed match)

**State:** Passphrase stored in `useSetupWizard` local state (NOT persisted to backend at this step — see A.4 option b). Cleared from memory after keypair generation.

### B.2 KeypairStep (Step 1)

```
frontend/src/pages/setup/KeypairStep.tsx
```

**Content:**
- "Generate your node identity" header
- "Generate Keypair" button → calls `POST /api/mgmt/setup/keypair` with `{ passphrase }`
- Loading state during generation
- On success: display fingerprint with copy-to-clipboard button
- "Back" and "Continue" buttons

**API:** `POST /api/mgmt/setup/keypair`
- Request: `KeypairRequest { passphrase: string }`
- Response: `KeypairResponse { fingerprint: string, public_key: string }`
- Backend already calls `mark_setup_step(2)` on success

### B.3 Router Update

Replace `SetupPlaceholder` import with step-based routing:

```typescript
{
  path: '/setup',
  element: <SetupLayout />,
  children: [
    { index: true, element: <WelcomeStep /> },
    { path: 'keypair', element: <KeypairStep /> },
    { path: 'connection', element: <ConnectionStep /> },
    { path: 'upstream', element: <UpstreamStep /> },
    { path: 'review', element: <ReviewStep /> },
    { path: 'unlock', element: <UnlockPage /> },
  ],
}
```

Navigation between steps uses `useNavigate()` controlled by `useSetupWizard.next()` / `back()`.

### B.4 Slice B Tests (8–10)

- `WelcomeStep`: renders form, passphrase validation (min length, uppercase, number, match), strength indicator states (4–5 tests)
- `KeypairStep`: calls API on generate, displays fingerprint, copy-to-clipboard, error handling (4–5 tests)

---

## Slice C: Steps 2–4 (Connection + Upstream + Review)

### C.1 ConnectionStep (Step 2)

```
frontend/src/pages/setup/ConnectionStep.tsx
```

**Content:**
- "Connect to ai.market" header
- API key input field (password-style with show/hide)
- "Test Connection" button → `POST /api/mgmt/setup/test-connection` with `{ api_key, marketplace_url }`
- Response shows: connection status, node registration status
- On success: mark step complete, enable Continue

**API:** `POST /api/mgmt/setup/test-connection`
- Request: `TestConnectionRequest { api_key: string, marketplace_url: string }`
- Response: `TestConnectionResponse { success: bool, message: str, node_id?: str }`
- Gate 2 adds: `state.mark_setup_step(3)` on success

### C.2 UpstreamStep (Step 3)

```
frontend/src/pages/setup/UpstreamStep.tsx
```

**Content:**
- "Configure upstream endpoint" header + explanation
- URL input for MCP endpoint
- "Test Upstream" button → `POST /api/mgmt/setup/test-upstream` with `{ url }`
- On success: show discovered tool count, tool names (truncated list)
- On failure: show error + allow skip with warning ("You can configure this later in Settings")
- Gate 2 adds: `state.mark_setup_step(4)` on success

**API:** `POST /api/mgmt/setup/test-upstream`
- Request: `TestUpstreamRequest { url: string }`
- Response includes: `{ success: bool, tools_count: int, tools: list[str] }` (verify actual schema)

### C.3 ReviewStep (Step 4)

```
frontend/src/pages/setup/ReviewStep.tsx
```

**Content:**
- "Review & Finalize" header
- Summary card showing: fingerprint, ai.market connection status, upstream URL + tool count
- Each section has an "Edit" link that navigates back to that step
- "Finalize Setup" primary button → `POST /api/mgmt/setup/finalize` with `{ mode: "seller" }`
- On success: redirect to `/dashboard`

**API:** `POST /api/mgmt/setup/finalize`
- Request: `FinalizeSetupRequest { mode: string }`
- Response: `FinalizeResponse { success: bool, message: str }`
- Already calls `mark_setup_complete()` with step=5

### C.4 Slice C Tests (10–14)

- `ConnectionStep`: renders form, calls test-connection API, success/failure states, retry (3–4 tests)
- `UpstreamStep`: renders form, calls test-upstream, shows tool count, skip-with-warning, error handling (4–5 tests)
- `ReviewStep`: renders summary from wizard state, edit links navigate back, finalize calls API + redirects (3–5 tests)

---

## Slice D: Unlock + allAI + Integration

### D.1 UnlockPage

```
frontend/src/pages/setup/UnlockPage.tsx
```

**Content:**
- "Unlock your node" header
- Passphrase input + "Unlock" button
- Calls `POST /api/mgmt/unlock` with `{ passphrase }`
- On success: redirect to `/dashboard`
- On failure: show error, allow retry, optional "Forgot passphrase?" link (leads to reset documentation)

**API:** `POST /api/mgmt/unlock`
- Request: `UnlockRequest { passphrase: string }`
- Response: `{ success: bool }` or error

### D.2 Backend: allAI Context Extension

Extend `_safe_status_context()` in `aim_node/management/allai.py` to include `current_step`:

```python
# Current pick list:
("healthy", "setup_complete", "locked", "provider_running", "node_id")
# Add:
("healthy", "setup_complete", "locked", "provider_running", "node_id", "current_step")
```

This gives the allAI copilot step-aware context during setup without any frontend changes.

### D.3 Integration Tests

Full wizard flow tests with mocked API:

1. Happy path: Welcome → passphrase → keypair → connection → upstream → review → finalize → redirect to dashboard
2. Resume: start at step 0, close, reopen → API returns current_step=2 → wizard resumes at connection
3. Error recovery: connection test fails → retry → succeeds → proceed
4. Unlock flow: locked node → passphrase → unlock → redirect
5. Skip upstream: upstream test fails → skip → proceed to review with warning

### D.4 Slice D Tests (8–10)

- `UnlockPage`: renders form, calls unlock API, success redirect, error retry (3–4 tests)
- allAI context: verify `current_step` is included in context (1 test — backend unit)
- Integration: happy path, resume, error recovery, unlock, skip upstream (4–5 tests)

---

## File Inventory

### New files (frontend)
- `frontend/src/hooks/useSetupWizard.ts`
- `frontend/src/components/StepIndicator.tsx`
- `frontend/src/pages/setup/WelcomeStep.tsx`
- `frontend/src/pages/setup/KeypairStep.tsx`
- `frontend/src/pages/setup/ConnectionStep.tsx`
- `frontend/src/pages/setup/UpstreamStep.tsx`
- `frontend/src/pages/setup/ReviewStep.tsx`
- `frontend/src/pages/setup/UnlockPage.tsx`

### Modified files (frontend)
- `frontend/src/hooks/useSetupStatus.ts` — fix interface to match real schema
- `frontend/src/router.tsx` — replace placeholders with real step routes
- `frontend/src/layouts/SetupLayout.tsx` — widen, add StepIndicator

### Modified files (backend)
- `aim_node/management/routes.py` — add `mark_setup_step()` calls at steps 2 (connection) and 3 (upstream)
- `aim_node/management/allai.py` — add `current_step` to `_safe_status_context()`

### Removed files
- `frontend/src/pages/placeholders/SetupPlaceholder.tsx`
- `frontend/src/pages/placeholders/UnlockPlaceholder.tsx`

---

## Build Notes

- All frontend components use existing UI primitives: `Card`, `Button`, `Input`, `Field`, `Spinner`, `Badge`, `EmptyState`
- Form validation is client-side only (backend validates on API call)
- Passphrase is NEVER stored in localStorage or any persistent storage — React state only, cleared after keypair generation
- Each step component is self-contained with its own API call and error handling
- MSW or manual fetch mocks for test API mocking (consistent with scaffold test patterns)
- Slices are independently committable and testable
