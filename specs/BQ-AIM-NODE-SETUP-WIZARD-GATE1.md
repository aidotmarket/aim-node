# BQ-AIM-NODE-SETUP-WIZARD — Gate 1 Spec
## Guided First-Run Experience with allAI Assist

**BQ Code:** BQ-AIM-NODE-SETUP-WIZARD
**Epic:** AIM-NODE-UI
**Phase:** 2
**Priority:** P0
**Estimated Hours:** 15
**Depends On:** BQ-AIM-NODE-UI-SCAFFOLD (Gate 4 ✅), BQ-AIM-NODE-MGMT-API-V2 (Gate 4 ✅)
**Author:** Vulcan (S438)
**Revision:** R3 — addresses Gate 1 R1+R2 mandates (MP): resume model, upstream API, allAI contract, hook schema

---

## 1. Problem Statement

AIM Node ships with a management API and a React SPA scaffold, but all UI pages are placeholders. A first-time user who starts the node lands on `/setup` and sees a blank placeholder. There is no guided experience to help them:

1. Secure their node with a passphrase
2. Generate an Ed25519 keypair for identity
3. Connect to the ai.market marketplace
4. Point the node at an upstream MCP-compatible model or tool server
5. Finalize and start serving

The management API already has all necessary endpoints (`/setup/status`, `/setup/keypair`, `/setup/test-connection`, `/setup/finalize`, `/unlock`). The allAI chat transport layer (chat/confirm endpoints) is wired but has no intelligence. This BQ replaces the `SetupPlaceholder` and `UnlockPlaceholder` pages with a fully interactive, step-by-step wizard.

## 2. User Stories

| ID | Story | Acceptance |
|----|-------|------------|
| SW-1 | As a new user, I see a welcome screen that explains what AIM Node does and prompts me to create a passphrase | Welcome step renders on first visit; passphrase form has strength indicator; proceed is blocked until passphrase meets minimum |
| SW-2 | As a new user, I generate my node's keypair and see my fingerprint | Keypair step calls `POST /setup/keypair`; fingerprint displayed; copy-to-clipboard button works |
| SW-3 | As a new user, I enter my ai.market API key and test the connection | Connection step calls `POST /setup/test-connection`; success/failure clearly displayed; user can retry on failure |
| SW-4 | As a new user, I configure my upstream MCP endpoint URL | Upstream step accepts URL; optional: test upstream reachability; shows discovered tool count on success |
| SW-5 | As a new user, I review my choices and finalize setup | Review step shows summary of all config; calls `POST /setup/finalize`; on success redirects to `/dashboard` |
| SW-6 | As a returning user with a locked node, I enter my passphrase to unlock | Unlock page calls `POST /unlock`; on success redirects to `/dashboard`; on failure shows error with retry |
| SW-7 | As a user on any step, I can ask allAI for help via the chat widget | AllAIChat widget is visible on all setup steps; questions about setup return contextual guidance |

## 3. Architecture

### 3.1 Page Components (replace placeholders)

```
frontend/src/pages/setup/
├── WelcomeStep.tsx          # Step 0: intro + passphrase creation
├── KeypairStep.tsx          # Step 1: generate keypair, show fingerprint
├── ConnectionStep.tsx       # Step 2: ai.market API key + test
├── UpstreamStep.tsx         # Step 3: upstream MCP endpoint config
├── ReviewStep.tsx           # Step 4: summary + finalize
└── UnlockPage.tsx           # Standalone: passphrase unlock for returning users
```

### 3.2 Wizard State Management

A `useSetupWizard` hook (or extend `useSetupStatus`) manages:

- `currentStep: number` (0–4) — synced with `/setup/status` → `current_step`
- `stepData: Record<number, StepPayload>` — local form data per step
- `stepStatus: Record<number, 'pending' | 'complete' | 'error'>` — completion state
- Navigation: `next()`, `back()`, `goToStep(n)` — `back()` always allowed; `next()` requires current step complete
- **Step persistence:** Each step completion must call the management API to persist progress via `mark_setup_step(n)`. Currently the backend only persists at steps 2 (keypair) and 5 (finalize); Gate 2 must extend this to persist all steps 0–4 so resume works at step granularity.
- On page load: call `GET /setup/status` → resume at `current_step` (supports interrupted setups)

### 3.2.1 Hook Schema Correction

The existing `useSetupStatus` hook expects `{ complete: boolean, steps: Record<string, boolean> }`, but the actual backend response (`SetupStatusResponse` schema) returns `{ setup_complete: bool, locked: bool, unlocked: bool, current_step: int }`. The hook interface must be corrected to match the real schema before wizard implementation begins.

### 3.3 Step Flow

```
[Welcome + Passphrase] → [Keypair Gen] → [ai.market Connection] → [Upstream Config] → [Review + Finalize]
        Step 0               Step 1             Step 2                 Step 3              Step 4
```

Each step is a self-contained form that calls one management API endpoint on submit. Steps are sequential — the user cannot skip ahead but can navigate back to review/edit completed steps.

### 3.4 Existing API Mapping

| Step | API Endpoint | Method | Purpose |
|------|-------------|--------|---------|
| 0 | — | — | Passphrase stored locally for keypair generation (passed to Step 1) |
| 1 | `/api/mgmt/setup/keypair` | POST | Generate Ed25519 keypair with passphrase |
| 2 | `/api/mgmt/setup/test-connection` | POST | Validate ai.market API key |
| 3 | `/api/mgmt/setup/test-upstream` | POST | Test upstream MCP endpoint reachability and discover tool count; on success, write URL to config |
| 4 | `/api/mgmt/setup/finalize` | POST | Mark setup complete, start provider |
| Unlock | `/api/mgmt/unlock` | POST | Decrypt keystore, resume operations |

### 3.5 allAI Integration

The AllAIChat widget (already scaffolded) appears in the SetupLayout sidebar or as a floating panel. During setup, the chat system prompt is augmented with:

- Current step number and name
- Which steps are complete vs pending
- Common setup issues (connection failures, passphrase requirements, upstream compatibility)

The allAI `/chat` endpoint builds context server-side via `_gather_context()`, which gathers node status, sessions, dashboard metrics, and discovered tools. The frontend does NOT send context — it only sends `message` and optional `conversation_id` per `AllAIChatRequest`. Note: `_safe_status_context()` currently forwards `healthy`, `setup_complete`, `locked`, `provider_running`, and `node_id` but does NOT include `current_step`. Gate 2 must extend `_safe_status_context()` to include `current_step` so the allAI copilot can provide step-aware guidance during setup.

**Scope boundary:** The allAI copilot intelligence (NLU, tool routing, multi-turn reasoning) is BQ-AIM-NODE-ALLAI-COPILOT scope. This BQ wires the widget to send setup context; responses use the existing basic chat relay.

## 4. UI Design

### 4.1 Layout

The setup wizard uses `SetupLayout` (already scaffolded) which provides:
- Centered content area (max-width 640px)
- Brand header with AIM Node logo
- No sidebar navigation (setup is linear)

Each step renders inside the content area with:
- Step indicator bar at top (horizontal stepper: numbered circles, active/complete/pending states)
- Step title + description
- Form fields
- Back / Continue buttons (footer)
- AllAIChat toggle in bottom-right corner

### 4.2 Step Indicator

Horizontal stepper with 5 circles connected by lines:
- **Pending:** `border-brand-border`, `bg-white`, muted text
- **Active:** `bg-brand-primary`, white number, `text-brand-primary` label
- **Complete:** `bg-brand-success`, checkmark icon, `text-brand-success` label

### 4.3 Passphrase Strength Indicator

- Minimum 12 characters, at least one uppercase, one number
- Visual bar: red (weak) → yellow (fair) → green (strong)
- Confirm field with match validation

### 4.4 Error States

- API errors render inline below the relevant form field
- Network failures show a banner at step top with retry button
- allAI is not required to proceed — if chat fails, setup continues normally

## 5. Test Strategy

| Layer | Scope | Count (est.) |
|-------|-------|-------------|
| Unit | Step components render, form validation, wizard hook state transitions | 15–20 |
| Integration | Full wizard flow with mocked API (happy path + error paths) | 5–8 |
| a11y | Keyboard navigation, focus management between steps, screen reader labels | 3–5 |

**Total estimated: 23–33 tests**

Testing uses Vitest + React Testing Library (already configured in scaffold). API calls mocked via MSW or manual fetch mocks (consistent with scaffold test patterns).

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Passphrase stored in React state could leak | Medium | Clear from state after keypair generation; never persist to localStorage |
| User closes browser mid-setup | Low | `/setup/status` returns `current_step` — wizard resumes where left off |
| Upstream MCP endpoint unreachable | Medium | Step 3 allows skip with warning; can be configured later in Settings |
| allAI chat unavailable | Low | Chat is advisory-only; all steps work without it |

## 7. Out of Scope

- allAI copilot intelligence / NLU (BQ-AIM-NODE-ALLAI-COPILOT)
- Tool discovery and publishing (BQ-AIM-NODE-SELLER-PUBLISH)
- Dashboard content (BQ-AIM-NODE-DASHBOARD)
- Settings page for post-setup config changes (BQ-AIM-NODE-SETTINGS, future)
- Mobile-responsive layout (Phase 3)

## 8. Definition of Done

- [ ] All 5 setup step pages render with correct forms and validation
- [ ] UnlockPage handles passphrase entry and redirect
- [ ] Wizard state persists via `/setup/status` API (resume support)
- [ ] Step indicator reflects current progress
- [ ] allAI chat widget receives setup context
- [ ] All tests pass (target: 25+)
- [ ] No TypeScript errors, no ESLint warnings
- [ ] Placeholder pages removed for setup routes
