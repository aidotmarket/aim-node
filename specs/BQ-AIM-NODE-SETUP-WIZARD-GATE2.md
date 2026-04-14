# BQ-AIM-NODE-SETUP-WIZARD — Gate 2 Spec (R2)
## Implementation Detail — 4 Slices

**BQ Code:** BQ-AIM-NODE-SETUP-WIZARD
**Gate:** 2 (Implementation)
**Gate 1 Ref:** APPROVED R3 (c20a59f)
**Author:** Vulcan (S439)
**R2 Note:** Addresses all 5 findings from MP Gate 2 R1 REJECT. Every API contract verified against `aim_node/management/schemas.py` and `routes.py` at commit 1133865.

---

## R1 Finding Resolution Map

| # | Severity | Finding | Resolution |
|---|----------|---------|------------|
| 1 | CRITICAL | API contracts don't match schemas.py | All request/response types copy-pasted from schemas.py. Every Slice B/C section updated. |
| 2 | HIGH | `mark_setup_step()` in-memory only, `config_writer.write_setup_step()` missing | Added `persist_setup_step()` to config_writer.py (Slice A). Routes call both `state.mark_setup_step(N)` and `persist_setup_step(data_dir, N)`. |
| 3 | HIGH | AllAIChat not in SetupLayout, placeholder with no transport | AllAIChat mounted in SetupLayout (Slice A). Basic transport wired in Slice D with `/allai/chat` endpoint. |
| 4 | MEDIUM | Slice B router imports Slice C pages | Router updates split per-slice. Each slice adds only its own page routes via lazy imports with fallback placeholders. |
| 5 | MEDIUM | `brand-primary`/`brand-success` tokens don't match existing primitives | All references updated to actual tokens: `brand-indigo`, `brand-teal`, `brand-success`, `brand-error`. Border uses `border-[#E8E8E8]`. |

---

## Canonical API Contracts (from schemas.py @ 1133865)

### Request Models

```python
class KeypairRequest(BaseModel):
    passphrase: Optional[str] = None

class TestConnectionRequest(BaseModel):
    api_url: str       # validated http(s)
    api_key: str

class FinalizeSetupRequest(BaseModel):
    mode: Literal["provider", "consumer", "both"]
    api_url: str       # validated http(s)
    api_key: str
    upstream_url: Optional[str] = None  # required if mode in (provider, both)

class UnlockRequest(BaseModel):
    passphrase: str

class TestUpstreamRequest(BaseModel):
    url: str           # validated http(s)
    timeout_s: float = 10.0
```

### Response Models

```python
class SetupStatusResponse(BaseModel):
    setup_complete: bool
    locked: bool
    unlocked: bool
    current_step: int   # 0–5, 5 = done

class KeypairResponse(BaseModel):
    fingerprint: str
    created: bool       # NOT public_key

class TestConnectionResponse(BaseModel):
    reachable: bool     # NOT success
    version: Optional[str] = None

class FinalizeResponse(BaseModel):
    ok: bool = True     # NOT {success, message}

class UnlockResponse(BaseModel):
    unlocked: bool = True  # NOT {success: bool}

class TestUpstreamResponse(BaseModel):
    reachable: bool
    latency_ms: Optional[int] = None
    tools_found: int = 0
    error: Optional[str] = None
```

---

## Slice Plan

| Slice | Scope | Est. Tests | Depends |
|-------|-------|-----------|---------|
| A | Foundation: wizard hook, step indicator, layout update, backend step persistence, AllAIChat in SetupLayout | 10–12 | — |
| B | Steps 0–1: Welcome/Passphrase + Keypair generation + B-only router entries | 8–10 | A |
| C | Steps 2–4: Connection + Upstream + Review/Finalize + C-only router entries | 10–14 | A |
| D | Unlock page + allAI chat transport wiring + integration tests | 8–10 | A, B, C |

**Total estimated: 36–46 tests**

---

## Slice A: Foundation

### A.1 Fix `useSetupStatus` Hook

Current hook expects `{ complete, steps }`. Actual backend response:

```typescript
// Must match SetupStatusResponse exactly
interface SetupStatusResponse {
  setup_complete: boolean;
  locked: boolean;
  unlocked: boolean;
  current_step: number;  // 0–5, 5 = done
}
```

Replace the hook interface. React Query key: `['setup-status']`.

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
  goToStep: (n: number) => void; // jump to completed step only
  markComplete: (step: number) => void; // after successful API call
}
```

- `currentStep` initialized from `GET /api/mgmt/setup/status` → `current_step`
- `markComplete(step)` updates local state (backend persists via route handlers — see A.4)
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
- **Pending:** `border-[#E8E8E8]`, `bg-white`, `text-brand-text-secondary`
- **Active:** `bg-brand-indigo`, white number, `text-brand-indigo` label
- **Complete:** `bg-brand-success`, checkmark icon, `text-brand-success` label
- Connector lines: `bg-[#E8E8E8]` pending, `bg-brand-indigo` complete

Uses existing `Badge` component for status pills where applicable.

### A.4 Backend: Disk Persistence for Setup Steps

**Problem:** `state.mark_setup_step(N)` is in-memory only. If the process restarts mid-setup, `_load_config()` reads `setup_step` from config.toml but only `finalize_setup()` writes it (as step=5).

**Fix:** Add `persist_setup_step()` to `config_writer.py`:

```python
# aim_node/management/config_writer.py — NEW FUNCTION
def persist_setup_step(data_dir: Path, step: int) -> None:
    """Persist intermediate setup step to config.toml."""
    config = read_config(data_dir)
    if "management" not in config:
        config["management"] = {}
    config["management"]["setup_step"] = step
    write_config(data_dir, config)
```

Update `routes.py` handlers to call both:

```python
# In setup_keypair (already calls mark_setup_step(2)):
state.mark_setup_step(2)
persist_setup_step(state._data_dir, 2)  # ADD

# In setup_test_connection (NEW — add at end of success path):
if reachable:
    state.mark_setup_step(3)
    persist_setup_step(state._data_dir, 3)

# In setup_finalize — already handled by finalize_setup() writing step=5
```

Step 0 (passphrase) and step 3 (upstream) do NOT persist separately:
- Step 0: passphrase exists only in React state until keypair generation. If user closes browser, they restart from step 0. This is intentional — no passphrase stored to disk before keypair.
- Step 3 (upstream test): persisted as step 4 only if test succeeds. If skipped, step stays at 3 until finalize.

Import addition in `routes.py`:
```python
from aim_node.management.config_writer import finalize_setup, read_config, write_config, persist_setup_step
```

### A.5 Update SetupLayout

- Widen `max-w-lg` to `max-w-2xl`
- Add `StepIndicator` above `<Outlet />`
- Mount `AllAIChat` component (same floating button as in AppLayout)

```tsx
// frontend/src/layouts/SetupLayout.tsx
import { AllAIChat } from '@/components/AllAIChat';
import { StepIndicator } from '@/components/StepIndicator';

// Inside render:
<div className="min-h-screen bg-brand-surface">
  <div className="max-w-2xl mx-auto py-12 px-4">
    <StepIndicator steps={SETUP_STEPS} currentStep={currentStep} />
    <Outlet />
  </div>
  <AllAIChat />
</div>
```

AllAIChat remains a disabled placeholder in this slice — transport wired in Slice D.

### A.6 Router: Placeholder-Safe Base

Update router to use lazy imports with inline fallback. This slice only adds the `/setup` parent route with the `SetupLayout` wrapper — individual step routes are added in their respective slices.

```typescript
// Slice A: only the parent route + index redirect
{
  path: '/setup',
  element: <SetupLayout />,
  children: [
    { index: true, element: <Navigate to="/setup/welcome" replace /> },
  ],
}
```

### A.7 Slice A Tests (10–12)

- `useSetupWizard`: initialization from API, next/back/goToStep logic, markComplete transitions (5–6 tests)
- `StepIndicator`: renders 5 steps, correct styling for pending/active/complete states (3–4 tests)
- `useSetupStatus`: corrected interface matches `SetupStatusResponse` exactly (2 tests)

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
  - Strength indicator bar (red → yellow → green) using `bg-brand-error` / `bg-brand-warning` / `bg-brand-success`
  - Validation: min 12 chars, 1 uppercase, 1 number
- "Continue" button (`bg-brand-indigo`) disabled until passphrase valid + confirmed match

**State:** Passphrase stored in `useSetupWizard` local React state (NOT persisted anywhere). Cleared from memory after keypair generation succeeds.

### B.2 KeypairStep (Step 1)

```
frontend/src/pages/setup/KeypairStep.tsx
```

**Content:**
- "Generate your node identity" header
- "Generate Keypair" button → calls `POST /api/mgmt/setup/keypair`
- Loading state during generation (`Spinner` component)
- On success: display fingerprint in monospace with copy-to-clipboard button
- "Back" and "Continue" buttons

**API contract (exact):**
```
POST /api/mgmt/setup/keypair
Request:  { passphrase?: string }          // KeypairRequest
Response: { fingerprint: string, created: boolean }  // KeypairResponse
Error:    409 if keypair already exists
```

Backend already calls `mark_setup_step(2)` + (with A.4 fix) `persist_setup_step(data_dir, 2)` on success.

### B.3 Router Addition (Slice B only)

```typescript
// Add to /setup children — only B pages
{ path: 'welcome', element: <WelcomeStep /> },
{ path: 'keypair', element: <KeypairStep /> },
```

Slice C pages are NOT imported here. If a user somehow navigates to `/setup/connection` before Slice C ships, they hit the index redirect back to `/setup/welcome`.

### B.4 Slice B Tests (8–10)

- `WelcomeStep`: renders form, passphrase validation (min length, uppercase, number, match), strength indicator color states (4–5 tests)
- `KeypairStep`: calls correct API endpoint with passphrase, displays `fingerprint` + `created` from response, copy-to-clipboard, 409 error handling (4–5 tests)

---

## Slice C: Steps 2–4 (Connection + Upstream + Review)

### C.1 ConnectionStep (Step 2)

```
frontend/src/pages/setup/ConnectionStep.tsx
```

**Content:**
- "Connect to ai.market" header
- API URL input (pre-filled with `https://api.ai.market`)
- API key input (password-style with show/hide)
- "Test Connection" button
- Response shows: reachable status badge, version if available
- On success: mark step complete, enable Continue

**API contract (exact):**
```
POST /api/mgmt/setup/test-connection
Request:  { api_url: string, api_key: string }               // TestConnectionRequest
Response: { reachable: boolean, version: string | null }      // TestConnectionResponse
```

With A.4 fix, backend marks step 3 and persists on success.

### C.2 UpstreamStep (Step 3)

```
frontend/src/pages/setup/UpstreamStep.tsx
```

**Content:**
- "Configure upstream endpoint" header + explanation of what MCP upstream means
- URL input for MCP endpoint
- "Test Upstream" button
- On success: show `tools_found` count, `reachable` status
- On failure: show `error` message + allow skip with warning ("You can configure this later in Settings")

**API contract (exact):**
```
POST /api/mgmt/setup/test-upstream
Request:  { url: string, timeout_s?: number }                          // TestUpstreamRequest
Response: { reachable: boolean, latency_ms: int | null, tools_found: int, error: string | null }  // TestUpstreamResponse
```

No automatic step persistence on upstream test. Step advances to 4 only at finalize.

### C.3 ReviewStep (Step 4)

```
frontend/src/pages/setup/ReviewStep.tsx
```

**Content:**
- "Review & Finalize" header
- Summary card showing: fingerprint, ai.market connection status (reachable + version), upstream URL + tools_found count
- Mode selector: radio group for "Provider", "Consumer", or "Both"
- Each section has an "Edit" link that navigates back to that step
- "Finalize Setup" primary button (`bg-brand-indigo`)

**API contract (exact):**
```
POST /api/mgmt/setup/finalize
Request:  {                                    // FinalizeSetupRequest
  mode: "provider" | "consumer" | "both",
  api_url: string,
  api_key: string,
  upstream_url?: string                        // required if mode in (provider, both)
}
Response: { ok: boolean }                      // FinalizeResponse
```

On success: redirect to `/dashboard`. Backend calls `finalize_setup()` which writes full config.toml and `mark_setup_complete(mode)`.

**Important:** The frontend must collect `api_url`, `api_key`, and `upstream_url` from earlier steps via wizard state and pass them all in the finalize request. These are NOT re-read from the backend — they haven't been persisted yet (only `setup_step` is persisted intermediately).

### C.4 Router Addition (Slice C only)

```typescript
// Add to /setup children — only C pages
{ path: 'connection', element: <ConnectionStep /> },
{ path: 'upstream', element: <UpstreamStep /> },
{ path: 'review', element: <ReviewStep /> },
```

### C.5 Slice C Tests (10–14)

- `ConnectionStep`: renders form with pre-filled api_url, calls correct endpoint with `{api_url, api_key}`, displays `reachable` + `version`, error handling (3–4 tests)
- `UpstreamStep`: renders form, calls test-upstream with `{url}`, shows `tools_found`, skip-with-warning flow, displays `error` on failure (4–5 tests)
- `ReviewStep`: renders summary from wizard state, mode selector, edit links navigate back, finalize sends correct `FinalizeSetupRequest` shape with all fields, redirects on `{ok: true}` (3–5 tests)

---

## Slice D: Unlock + allAI Transport + Integration

### D.1 UnlockPage

```
frontend/src/pages/setup/UnlockPage.tsx
```

**Content:**
- "Unlock your node" header
- Passphrase input + "Unlock" button
- On success: redirect to `/dashboard`
- On failure: show error, allow retry

**API contract (exact):**
```
POST /api/mgmt/unlock
Request:  { passphrase: string }        // UnlockRequest
Response: { unlocked: boolean }          // UnlockResponse (unlocked=true on success)
Error:    401/403 on wrong passphrase
```

### D.2 allAI Chat Transport Wiring

The AllAIChat component (already mounted in SetupLayout from Slice A) gets basic send/receive wired:

```typescript
// AllAIChat.tsx — replace disabled placeholder
// Transport: POST /allai/chat with { message: string }
// Response: { reply: string } (streamed or single response)
```

Implementation:
- Remove `disabled` from Input and Button
- Replace `EmptyState` with a messages list (`useState<Message[]>`)
- `onSubmit`: POST to `/allai/chat`, append response to messages
- No streaming required in this BQ — simple request/response is sufficient
- Error handling: show error badge inline, allow retry

The allAI backend has `_safe_status_context()` which currently picks `healthy`, `setup_complete`, `locked`, `provider_running`, and `node_id`. Slice D extends this to also include `current_step` and `mode`:

```python
# aim_node/management/allai.py — _safe_status_context() pick list
# Current pick list (from allai.py @ 1133865):
("healthy", "setup_complete", "locked", "provider_running", "node_id")
# Updated (add current_step and mode):
("healthy", "setup_complete", "locked", "provider_running", "node_id", "current_step", "mode")
```

Note: `get_status()` returns `current_step` (which maps to the internal `_setup_step` field). The pick key must be `current_step` to match the status dict key.

### D.3 Router Addition (Slice D only)

```typescript
// Add to /setup children
{ path: 'unlock', element: <UnlockPage /> },
```

### D.4 Integration Tests

Full wizard flow tests with mocked API:

1. **Happy path:** Welcome → passphrase → keypair (`{fingerprint, created: true}`) → connection (`{reachable: true, version: "1.0"}`) → upstream (`{reachable: true, tools_found: 3}`) → review (sends `FinalizeSetupRequest` with all fields) → redirect to dashboard
2. **Resume:** Start fresh → complete through keypair → close browser → reopen → API returns `current_step: 2` → wizard resumes at connection step
3. **Error recovery:** Connection test returns `{reachable: false}` → retry → returns `{reachable: true}` → proceed
4. **Unlock flow:** Setup complete + locked node → passphrase → `{unlocked: true}` → redirect to dashboard
5. **Skip upstream:** Upstream test returns `{reachable: false, error: "timeout"}` → skip with warning → proceed to review (upstream_url omitted from finalize if mode is "consumer")

### D.5 Slice D Tests (8–10)

- `UnlockPage`: renders form, calls `/api/mgmt/unlock` with `{passphrase}`, success redirect on `{unlocked: true}`, error retry (3–4 tests)
- allAI context: verify `current_step` is included in `_safe_status_context()` output (1 backend unit test)
- allAI chat: sends message to `/allai/chat`, displays reply, error handling (2 tests)
- Integration: happy path, resume, error recovery, unlock, skip upstream (4–5 tests — can be combined)

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
- `frontend/src/hooks/useSetupStatus.ts` — fix interface to match `SetupStatusResponse`
- `frontend/src/router.tsx` — add step routes incrementally per slice (A: parent + index, B: welcome + keypair, C: connection + upstream + review, D: unlock)
- `frontend/src/layouts/SetupLayout.tsx` — widen to `max-w-2xl`, add `StepIndicator`, mount `AllAIChat`
- `frontend/src/components/AllAIChat.tsx` — wire basic transport to `/allai/chat` (Slice D)

### Modified files (backend)
- `aim_node/management/config_writer.py` — add `persist_setup_step()` function
- `aim_node/management/routes.py` — add `persist_setup_step()` calls alongside `mark_setup_step()`, add `mark_setup_step(3)` in `setup_test_connection` success path
- `aim_node/management/allai.py` — add `current_step` to `_safe_status_context()` pick list

### Removed files
- `frontend/src/pages/placeholders/SetupPlaceholder.tsx`
- `frontend/src/pages/placeholders/UnlockPlaceholder.tsx`

---

## Design Token Reference (from tailwind.config.ts @ 1133865)

| Token | Value | Usage |
|-------|-------|-------|
| `brand-indigo` | `#3F51B5` | Primary buttons, active step indicator, links |
| `brand-teal` | `#0F6E56` | Secondary accents |
| `brand-surface` | `#F8F9FA` | Page backgrounds |
| `brand-text` | `#1A1A2E` | Primary text |
| `brand-text-secondary` | `#6B7280` | Muted text, pending step labels |
| `brand-success` | `#10B981` | Complete step indicator, success badges |
| `brand-warning` | `#F59E0B` | Passphrase medium strength |
| `brand-error` | `#EF4444` | Error states, weak passphrase |
| border | `#E8E8E8` | Card borders, step connector lines (use `border-[#E8E8E8]`) |
| border-radius | `rounded-brand` (8px) | Cards, buttons |
| font | Plus Jakarta Sans | All text |

**No `brand-primary` or `brand-border` tokens exist.** All references use the actual token names above.

---

## Build Notes

- All frontend components use existing UI primitives: `Card`, `Button`, `Input`, `Field`, `Spinner`, `Badge`, `EmptyState`
- Form validation is client-side only (backend validates on API call)
- Passphrase is NEVER stored in localStorage or any persistent storage — React state only, cleared after keypair generation
- Each step component is self-contained with its own API call and error handling
- MSW or manual fetch mocks for test API mocking (consistent with scaffold test patterns)
- Slices are independently committable and testable — each slice adds only its own router entries
- The `FinalizeSetupRequest` requires fields from earlier steps (api_url, api_key, upstream_url) — the wizard hook must accumulate these in React state across steps
