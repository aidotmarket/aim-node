# BQ-AIM-NODE-UI-SCAFFOLD — Gate 1 Spec
## React SPA Scaffold for AIM Node Web UI

**BQ Code:** BQ-AIM-NODE-UI-SCAFFOLD
**Epic:** AIM-NODE-UI
**Phase:** 2 — Provider MVP
**Priority:** P0
**Estimated Hours:** 12
**Depends On:** BQ-AIM-NODE-CONTRACTS (Gate 1 APPROVED)
**Author:** Vulcan (S431)

---

## 1. Problem Statement

AIM Node needs a React SPA web interface served from within the Docker container. This BQ creates the foundational app shell, build pipeline, component library, routing, and brand system that all subsequent UI BQs build on.

## 2. Technology Stack

- **Framework:** React 18+ with TypeScript
- **Build:** Vite (fast builds, ESM-native, small output)
- **Routing:** React Router v6 (client-side, SPA fallback from Starlette)
- **State:** Zustand (lightweight, no boilerplate) for global state; React Query (TanStack Query) for server state/caching
- **Styling:** Tailwind CSS with ai.market brand tokens
- **HTTP Client:** Built-in fetch with a typed API client wrapper
- **Charts:** Recharts (for dashboard metrics later)
- **Icons:** Lucide React

## 3. Brand System

Per ai.market brand guidelines:

```
Primary Indigo:  #3F51B5
Secondary Teal:  #0F6E56
Font:            Plus Jakarta Sans (600 headings, 400-500 body)
Border Radius:   8px
Backgrounds:     White (#FFFFFF)
Surface:         #F8F9FA (cards, sidebars)
Text Primary:    #1A1A2E
Text Secondary:  #6B7280
Success:         #10B981
Warning:         #F59E0B
Error:           #EF4444
```

Tailwind config extends with these as `brand-*` color tokens.

## 4. Application Shell

### 4.1 Layout

```
┌─────────────────────────────────────────┐
│ Top Bar: AIM Node logo + node status    │
├──────────┬──────────────────────────────┤
│          │                              │
│ Sidebar  │    Main Content Area         │
│ Nav      │                              │
│          │                              │
│ - Dash   │                              │
│ - Tools  │                              │
│ - Earn   │                              │
│ - Sess   │                              │
│ - Logs   │                              │
│ - Config │                              │
│          │                              │
├──────────┴──────────────────────────────┤
│ allAI Chat Widget (collapsible, bottom-right) │
└─────────────────────────────────────────┘
```

### 4.2 Routes

| Route | Screen | Status |
|-------|--------|--------|
| `/` | Redirect → `/dashboard` or `/setup` (based on setup_complete) | Scaffold |
| `/setup` | Setup Wizard | Future BQ |
| `/setup/unlock` | Unlock Screen | Future BQ |
| `/dashboard` | Provider Dashboard | Future BQ |
| `/tools` | Tool Management | Future BQ |
| `/tools/:id` | Tool Detail | Future BQ |
| `/earnings` | Earnings & Payouts | Future BQ |
| `/sessions` | Sessions List | Future BQ |
| `/sessions/:id` | Session Detail | Future BQ |
| `/logs` | Log Viewer | Future BQ |
| `/settings` | Configuration | Future BQ |

Scaffold BQ implements: route definitions, layout shell, placeholder pages with "Coming Soon" for each route, and the root redirect logic.

### 4.3 API Client

Typed wrapper around fetch that:
- Prefixes all calls with `/api/mgmt`
- Reads CSRF token from health response, attaches to mutating requests
- Handles error responses per normalized format (Contracts Section 5)
- Provides React Query hooks: `useHealth()`, `useSetupStatus()`, `useDashboard()`, etc.
- Auto-refreshes on focus/interval for real-time data

### 4.4 Global State (Zustand)

```typescript
interface NodeState {
  setupComplete: boolean;
  locked: boolean;
  csrfToken: string | null;
  // Set on initial health check
}
```

### 4.5 allAI Chat Widget Shell

A collapsible chat panel in the bottom-right corner. Scaffold provides:
- Open/close toggle button
- Chat container with message list
- Text input with send button
- Placeholder: "allAI assistant coming soon"
- No backend integration in this BQ (covered by BQ-AIM-NODE-ALLAI-COPILOT)

## 5. Docker Integration

### 5.1 Build Pipeline

The Dockerfile gets a multi-stage build:
```
Stage 1: Node.js — npm install, npm run build (outputs to dist/)
Stage 2: Python — existing aim-node install, COPY dist/ into frontend/dist/
```

### 5.2 Development Mode

For local dev: `npm run dev` runs Vite dev server on :5173 with proxy to :8080 for API calls. This avoids rebuilding Docker for every frontend change.

## 6. Deliverables

1. `frontend/` directory in aim-node repo with React/Vite/TS project
2. Tailwind config with ai.market brand tokens
3. App shell with sidebar nav, top bar, route definitions
4. Typed API client with React Query hooks
5. Zustand store for global state
6. allAI chat widget shell (UI only, no backend)
7. Multi-stage Dockerfile update
8. `npm run dev` development workflow documented
9. Placeholder pages for all routes

## 7. Done Criteria

- `npm run build` produces optimized static bundle
- Docker image serves SPA at localhost:8080 (root redirects to /dashboard or /setup)
- Client-side routing works (direct URL access to any route returns index.html)
- API client correctly prefixes calls and handles errors
- Brand colors, typography, and spacing match ai.market guidelines
- allAI chat widget opens/closes (placeholder content)
- Dev mode (Vite + API proxy) works for rapid iteration
- All routes render placeholder pages without errors

## 8. Out of Scope

- Actual screen implementations (each covered by downstream BQs)
- allAI backend integration (covered by BQ-AIM-NODE-ALLAI-COPILOT)
- Backend API changes (covered by BQ-AIM-BACKEND-SELLER-APIS)
- Management API extensions (covered by BQ-AIM-NODE-MGMT-API-V2)
