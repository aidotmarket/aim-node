# Development

## Prerequisites

- Python 3.11+
- Node 20 LTS
- npm

## Frontend development

Run the Vite dev server from the frontend workspace:

```bash
cd frontend
npm install
npm run dev
```

## API proxy

The Vite dev server proxies `/api` requests to `http://localhost:8080`. This is configured in `frontend/vite.config.ts`.

## Build

Build the frontend from the `frontend/` directory:

```bash
cd frontend
npm run build
```

The production bundle is written to `frontend/dist`.

## Docker

The Docker image uses a multi-stage frontend build automatically during `docker build`. Built assets are copied into `/data/frontend/dist`, which is the path served by the management UI runtime.

## Brand tokens

Use the Tailwind brand token classes defined in `frontend/tailwind.config.ts` for consistent UI styling:

- `brand-indigo`
- `brand-teal`
- `brand-surface`

Examples include `text-brand-indigo`, `bg-brand-teal`, and `bg-brand-surface`.

## Base components

Import shared UI primitives from the barrel at `@/components/ui`:

```ts
import { Button, Card, EmptyState, Input, PageHeader, Spinner, StatusBadge } from '@/components/ui';
```

Follow the existing variant and size APIs exposed by each component. For example, `Button` supports `variant="primary" | "secondary" | "ghost" | "danger"` and `size="sm" | "md" | "lg"`, while `Card` uses a `padding` prop with `none`, `sm`, `md`, and `lg`.

## Testing

- Frontend: `cd frontend && npm test`
- Backend: `python3 -m pytest`
