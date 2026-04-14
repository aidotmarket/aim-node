import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { AppLayout } from '@/layouts/AppLayout';
import { SetupLayout } from '@/layouts/SetupLayout';
import { DashboardPlaceholder } from '@/pages/placeholders/DashboardPlaceholder';
import { EarningsPlaceholder } from '@/pages/placeholders/EarningsPlaceholder';
import { SessionsPlaceholder } from '@/pages/placeholders/SessionsPlaceholder';
import { SessionDetailPlaceholder } from '@/pages/placeholders/SessionDetailPlaceholder';
import { LogsPlaceholder } from '@/pages/placeholders/LogsPlaceholder';
import { SettingsPlaceholder } from '@/pages/placeholders/SettingsPlaceholder';
import { NotFound } from '@/pages/NotFound';
import { SetupIndexRedirect } from '@/router';
import { UnlockPage } from '@/pages/setup/UnlockPage';
import { ToolsListPage } from '@/pages/tools/ToolsListPage';
import { ToolDetailPage } from '@/pages/tools/ToolDetailPage';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

beforeEach(() => {
  globalThis.fetch = mockFetch;
  mockFetch.mockImplementation((input: RequestInfo | URL) => {
    const url = String(input);

    if (url.includes('/api/mgmt/setup/status')) {
      return Promise.resolve(
        jsonResponse({
          setup_complete: false,
          locked: false,
          unlocked: true,
          current_step: 0,
        }),
      );
    }

    if (url.includes('/api/mgmt/tools/tool-123')) {
      return Promise.resolve(
        jsonResponse({
          tool_id: 'tool-123',
          name: 'route.tool',
          version: '1.0.0',
          description: 'Tool detail route payload',
          input_schema: { type: 'object' },
          output_schema: { type: 'object' },
          validation_status: 'pending',
          last_scanned_at: '2026-04-14T12:00:00Z',
          last_validated_at: null,
        }),
      );
    }

    if (url.includes('/api/mgmt/tools')) {
      return Promise.resolve(
        jsonResponse({
          scanned_at: '2026-04-14T12:00:00Z',
          tools: [
            {
              tool_id: 'tool-123',
              name: 'route.tool',
              version: '1.0.0',
              description: 'Tool list route payload',
              validation_status: 'passed',
              last_scanned_at: '2026-04-14T12:00:00Z',
            },
          ],
        }),
      );
    }

    if (url.includes('/api/mgmt/marketplace/tools')) {
      return Promise.resolve(jsonResponse({ tools: [] }));
    }

    return Promise.reject(new Error(`Unhandled URL: ${url}`));
  });
});

afterEach(() => {
  globalThis.fetch = originalFetch;
  mockFetch.mockReset();
});

const routes = [
  {
    path: '/setup',
    element: <SetupLayout />,
    children: [
      { index: true, element: <SetupIndexRedirect /> },
      { path: 'welcome', element: <div>Setup Welcome</div> },
      { path: 'unlock', element: <UnlockPage /> },
    ],
  },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { path: 'dashboard', element: <DashboardPlaceholder /> },
      { path: 'tools', element: <ToolsListPage /> },
      { path: 'tools/:toolId', element: <ToolDetailPage /> },
      { path: 'earnings', element: <EarningsPlaceholder /> },
      { path: 'sessions', element: <SessionsPlaceholder /> },
      { path: 'sessions/:id', element: <SessionDetailPlaceholder /> },
      { path: 'logs', element: <LogsPlaceholder /> },
      { path: 'settings', element: <SettingsPlaceholder /> },
    ],
  },
  { path: '*', element: <NotFound /> },
];

function renderRoute(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('Route rendering', () => {
  it('renders dashboard page', async () => {
    renderRoute('/dashboard');
    await waitFor(() =>
      expect(screen.getByText('Provider health, sessions, and metrics at a glance.')).toBeInTheDocument(),
    );
  });

  it('renders tools page', async () => {
    renderRoute('/tools');
    await waitFor(() =>
      expect(
        screen.getByText('Manage your local tools and track marketplace publish status.'),
      ).toBeInTheDocument(),
    );
  });

  it('renders tool detail page', async () => {
    renderRoute('/tools/tool-123');
    await waitFor(() => expect(screen.getByText('route.tool')).toBeInTheDocument());
  });

  it('renders earnings page', async () => {
    renderRoute('/earnings');
    await waitFor(() =>
      expect(screen.getByText('Track your earnings from tool sessions.')).toBeInTheDocument(),
    );
  });

  it('renders sessions page', async () => {
    renderRoute('/sessions');
    await waitFor(() =>
      expect(screen.getByText('View active and past MCP sessions.')).toBeInTheDocument(),
    );
  });

  it('renders session detail page', async () => {
    renderRoute('/sessions/abc');
    await waitFor(() =>
      expect(screen.getByText('Inspect a specific session.')).toBeInTheDocument(),
    );
  });

  it('renders logs page', async () => {
    renderRoute('/logs');
    await waitFor(() =>
      expect(screen.getByText('View system and request logs.')).toBeInTheDocument(),
    );
  });

  it('renders settings page', async () => {
    renderRoute('/settings');
    await waitFor(() =>
      expect(screen.getByText('Node configuration and preferences.')).toBeInTheDocument(),
    );
  });

  it('renders setup page', async () => {
    renderRoute('/setup');
    await waitFor(() => expect(screen.getByText('Setup Welcome')).toBeInTheDocument());
  });

  it('renders unlock page', async () => {
    renderRoute('/setup/unlock');
    await waitFor(() => expect(screen.getByText('Unlock your node')).toBeInTheDocument());
  });

  it('renders not found for unknown routes', async () => {
    renderRoute('/nonexistent');
    await waitFor(() => expect(screen.getByText('Page Not Found')).toBeInTheDocument());
  });
});

describe('Layout rendering', () => {
  it('app layout shows sidebar nav items', async () => {
    renderRoute('/dashboard');
    await waitFor(() => {
      expect(screen.getByText('AIM Node')).toBeInTheDocument();
      // Nav items are links in the sidebar
      for (const label of ['Dashboard', 'Tools', 'Earnings', 'Sessions', 'Logs', 'Settings']) {
        expect(screen.getAllByText(label).length).toBeGreaterThanOrEqual(1);
      }
    });
  });

  it('setup layout shows AIM Node branding', async () => {
    renderRoute('/setup');
    await waitFor(() => {
      expect(screen.getByText('AIM Node')).toBeInTheDocument();
      expect(screen.getByText('Setup & Configuration')).toBeInTheDocument();
    });
  });
});
