# BQ-AIM-NODE-UI-SCAFFOLD — Gate 2 Spec
## Implementation: React SPA Scaffold for AIM Node Web UI

**BQ Code:** BQ-AIM-NODE-UI-SCAFFOLD
**Epic:** AIM-NODE-UI
**Phase:** 2 — Implementation
**Prerequisite:** Gate 1 approved (S432)
**Author:** Vulcan (S435)

---

## Overview

Scaffold the React SPA that runs inside the AIM Node Docker container. This creates the foundational project structure, app shell, routing, API client, state management, and brand system. All downstream UI BQs (Dashboard, Tools, Earnings, Setup Wizard, etc.) build on this foundation.

## Codebase Baseline

The `frontend/` directory does not yet exist. This BQ creates it from scratch. The Starlette static file serving and SPA fallback are owned by BQ-AIM-NODE-MGMT-API-V2 (Slice D) — this BQ only produces the build artifacts.

**Existing aim-node structure:**
```
aim_node/
├── management/app.py     — Starlette factory (static placeholder exists at line ~routes)
├── Dockerfile             — Python-only, needs multi-stage update
└── ...
```

---

## Slice A: Project Setup + Brand System + App Shell (est 5h)

### A.1 Project Initialization

```bash
frontend/
├── package.json          # React 18, Vite 5, TypeScript 5
├── package-lock.json     # Required for reproducible npm ci
├── tsconfig.json
├── vite.config.ts        # Proxy /api → localhost:8080 for dev
├── tailwind.config.ts    # Brand tokens
├── postcss.config.js
├── index.html            # Vite entry
└── src/
    ├── main.tsx          # React root
    ├── App.tsx           # Router + layout
    ├── vite-env.d.ts
    └── ...
```

**Vite config:**
```typescript
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true },
    },
  },
  build: {
    outDir: 'dist',
    sourcemap: false,
  },
});
```

### A.2 Tailwind Brand Tokens

```typescript
// tailwind.config.ts
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        'brand-indigo': '#3F51B5',
        'brand-teal': '#0F6E56',
        'brand-surface': '#F8F9FA',
        'brand-text': '#1A1A2E',
        'brand-text-secondary': '#6B7280',
        'brand-success': '#10B981',
        'brand-warning': '#F59E0B',
        'brand-error': '#EF4444',
      },
      fontFamily: {
        sans: ['"Plus Jakarta Sans"', 'system-ui', 'sans-serif'],
      },
      borderRadius: {
        brand: '8px',
      },
    },
  },
};
```

Import Plus Jakarta Sans via `@fontsource/plus-jakarta-sans` npm package (no CDN dependency).

### A.3 App Shell Layout

```typescript
// src/layouts/AppLayout.tsx
// Responsive sidebar (collapsible on mobile) + top bar + main content
// Sidebar nav items: Dashboard, Tools, Earnings, Sessions, Logs, Settings
// Top bar: AIM Node logo + node status badge (healthy/degraded/unknown)
// Bottom-right: allAI chat widget toggle

// src/layouts/SetupLayout.tsx
// Minimal layout for setup flow — centered card, no sidebar
```

### A.4 Route Definitions

```typescript
// src/router.tsx
const routes = [
  { path: '/', element: <RootRedirect /> },
  // Setup flow (minimal layout)
  { path: '/setup', element: <SetupLayout />, children: [
    { index: true, element: <SetupPlaceholder /> },
    { path: 'unlock', element: <UnlockPlaceholder /> },
  ]},
  // Main app (full layout)
  { path: '/', element: <AppLayout />, children: [
    { path: 'dashboard', element: <DashboardPlaceholder /> },
    { path: 'tools', element: <ToolsPlaceholder /> },
    { path: 'tools/:id', element: <ToolDetailPlaceholder /> },
    { path: 'earnings', element: <EarningsPlaceholder /> },
    { path: 'sessions', element: <SessionsPlaceholder /> },
    { path: 'sessions/:id', element: <SessionDetailPlaceholder /> },
    { path: 'logs', element: <LogsPlaceholder /> },
    { path: 'settings', element: <SettingsPlaceholder /> },
  ]},
  { path: '*', element: <NotFound /> },
];
```

**RootRedirect logic:**
```typescript
function RootRedirect() {
  const { loading, locked, setupComplete } = useNodeState();
  if (loading) return <LoadingScreen />;
  if (locked) return <Navigate to="/setup/unlock" replace />;
  if (!setupComplete) return <Navigate to="/setup" replace />;
  return <Navigate to="/dashboard" replace />;
}
```

### A.5 Placeholder Pages

Each placeholder: centered card with route name, Lucide icon, and "Coming Soon" text. Consistent style using brand tokens.

```typescript
// src/pages/placeholders/DashboardPlaceholder.tsx
export default function DashboardPlaceholder() {
  return (
    <PlaceholderPage
      icon={<LayoutDashboard />}
      title="Dashboard"
      description="Provider health, sessions, and metrics at a glance."
    />
  );
}
```

### A.6 Done Criteria — Slice A
- `npm ci && npm run build` succeeds (Node 20 LTS)
- Build output in `frontend/dist/` with hashed assets
- Brand colors + Plus Jakarta Sans applied
- App shell renders with sidebar, top bar, routing
- All 11 routes accessible with placeholder content
- Root redirect handles three states (loading → locked → setup → dashboard)
- `npm run dev` proxies API calls to :8080
- Tests: Vitest, 10+ (route rendering, redirect logic, layout rendering)

---

## Slice B: API Client + State Management + Chat Widget (est 4h)

### B.1 Typed API Client

```typescript
// src/lib/api.ts
const API_BASE = '/api/mgmt';

class ApiClient {
  private csrfToken: string | null = null;

  async get<T>(path: string, params?: Record<string, string>): Promise<T> {
    const url = new URL(`${API_BASE}${path}`, window.location.origin);
    if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url.toString());
    this.extractCsrf(res);
    if (!res.ok) throw await this.parseError(res);
    return res.json();
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    this.extractCsrf(res);
    if (!res.ok) throw await this.parseError(res);
    return res.json();
  }

  // Similarly: put, delete

  private extractCsrf(res: Response) {
    const token = res.headers.get('X-CSRF-Token');
    if (token) this.csrfToken = token;
  }

  private async parseError(res: Response): Promise<ApiError> {
    const body = await res.json().catch(() => ({}));
    return new ApiError(body.code ?? 'unknown', body.message ?? 'Request failed', res.status, body);
  }
}

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: unknown,
  ) { super(message); }
}

export const api = new ApiClient();
```

### B.2 React Query Hooks

```typescript
// src/hooks/useHealth.ts
export function useHealth() {
  return useQuery({
    queryKey: ['health'],
    queryFn: () => api.get<HealthResponse>('/health'),
    refetchInterval: 10_000, // 10s polling for real-time status
    refetchOnWindowFocus: true,
  });
}

// src/hooks/useSetupStatus.ts
export function useSetupStatus() {
  return useQuery({
    queryKey: ['setup-status'],
    queryFn: () => api.get<SetupStatusResponse>('/setup/status'),
    staleTime: 30_000,
  });
}
```

Only implement hooks for approved/existing endpoints (health, setup/status). Other hooks added when corresponding MGMT-API-V2 slices land.

### B.3 Zustand Store

```typescript
// src/store/nodeStore.ts
interface NodeState {
  setupComplete: boolean;
  locked: boolean;
  healthStatus: 'healthy' | 'degraded' | 'unknown';
  csrfToken: string | null;
  loading: boolean;
  bootstrap: () => Promise<void>;
}

export const useNodeStore = create<NodeState>((set) => ({
  setupComplete: false,
  locked: false,
  healthStatus: 'unknown',
  csrfToken: null,
  loading: true,
  bootstrap: async () => {
    try {
      // GET /api/mgmt/health returns: { healthy, setup_complete, locked, csrf_token, session_token }
      const health = await api.get<HealthResponse>('/health');
      set({
        setupComplete: health.setup_complete,
        locked: health.locked,
        healthStatus: health.healthy ? 'healthy' : 'degraded',
        csrfToken: health.csrf_token ?? null, // also extracted from X-CSRF-Token header by ApiClient
        loading: false,
      });
    } catch {
      set({ healthStatus: 'unknown', loading: false });
    }
  },
}));
```

### B.4 allAI Chat Widget Shell

```typescript
// src/components/AllAIChat.tsx
// Collapsible panel, bottom-right corner, fixed position
// States: collapsed (icon button) / expanded (chat panel)
// Chat panel: message list + text input + send button
// Placeholder message: "allAI assistant coming soon"
// No backend integration — UI shell only
// Uses brand-indigo for accent, brand-surface for bubble backgrounds
```

### B.5 Done Criteria — Slice B
- API client prefixes calls with /api/mgmt, handles CSRF, parses normalized errors
- React Query hooks for health + setup status with auto-refresh
- Zustand bootstrap fetches health + setup, populates state atomically
- Loading state prevents flicker/misroute on initial render
- Chat widget opens/closes with smooth animation
- Tests: 12+ (API client mock tests, error parsing, store bootstrap, chat widget toggle)

---

## Slice C: Docker Integration + Dev Docs (est 3h)

### C.1 Multi-Stage Dockerfile

**Preserves existing builder + runtime stages.** Adds a new `frontend-build` stage before the existing `runtime` stage.

```dockerfile
# Stage 1 (NEW): Frontend build
FROM node:20-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ .
RUN npm run build

# Stage 2 (EXISTING): Python builder — unchanged
FROM python:3.11-slim-bookworm AS builder
# ... existing pip install, /install output ...

# Stage 3 (EXISTING): Python runtime — add one COPY line
FROM python:3.11-slim-bookworm AS runtime
# ... existing apt-get, COPY --from=builder, user creation ...

# ADD THIS LINE after existing COPY --from=builder:
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

# Ensure aimnode user owns frontend assets:
# RUN chown -R aimnode:aimnode /app  (already exists)

# ... existing ENTRYPOINT/CMD unchanged ...
```

**Key:** Only one new `FROM` stage and one new `COPY` line added. All existing Python builder/runtime logic, user creation (`aimnode`), and entrypoint remain untouched.

### C.2 .dockerignore Updates

```
frontend/node_modules
frontend/.vite
frontend/dist
```

### C.3 Dev Documentation

Update `README.md` or create `docs/DEVELOPMENT.md`:
- Prerequisites: Node 20 LTS, npm
- Frontend dev: `cd frontend && npm install && npm run dev`
- API proxy: Vite proxies /api to :8080
- Build: `npm run build` outputs to frontend/dist
- Docker: Multi-stage builds frontend automatically
- Brand tokens: How to use brand-* Tailwind classes

### C.4 Done Criteria — Slice C
- `docker build` produces image with frontend assets at /app/frontend/dist
- Docker image size reasonable (< 500MB including Python + Node build cache)
- README documents dev workflow
- CI: frontend build step added (npm ci + npm run build + npm test)
- Tests: 5+ (Dockerfile build verification, dev server starts, build output structure)

---

## Summary

| Slice | Scope | New Files | Tests |
|-------|-------|-----------|-------|
| A: Project + Brand + Shell | Vite/React/TS, Tailwind, layout, routes, placeholders | ~25 files in frontend/ | 10 |
| B: API Client + State + Chat | Typed fetch wrapper, React Query, Zustand, chat widget | ~10 files | 12 |
| C: Docker + Docs | Multi-stage Dockerfile, README, CI | 3-4 files | 5 |
| **Total** | | **~38 files** | **27** |

## Done Criteria (Full BQ)

1. `npm ci && npm run build` produces optimized bundle (Node 20, npm, package-lock.json)
2. Docker multi-stage build places assets at /app/frontend/dist
3. App shell: sidebar nav, top bar with status, responsive layout
4. All 11 routes render placeholder pages
5. Root redirect: loading → locked → setup → dashboard (three-state)
6. API client: /api/mgmt prefix, CSRF handling, normalized error parsing
7. React Query hooks for health + setup with auto-refresh
8. Zustand store bootstraps atomically, prevents flicker
9. allAI chat widget shell (UI only, no backend)
10. Brand system: Primary Indigo, Secondary Teal, Plus Jakarta Sans, 8px radius
11. Dev mode: `npm run dev` with API proxy to :8080
12. 27+ tests passing

## Out of Scope

- Actual screen implementations (downstream BQs)
- allAI backend integration (BQ-AIM-NODE-ALLAI-COPILOT)
- Starlette static serving + SPA fallback (BQ-AIM-NODE-MGMT-API-V2 Slice D)
- Backend API changes (BQ-AIM-BACKEND-SELLER-APIS)
