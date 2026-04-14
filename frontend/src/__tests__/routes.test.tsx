import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, Navigate, RouterProvider } from 'react-router-dom';
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { AppLayout } from '@/layouts/AppLayout';
import { SetupLayout } from '@/layouts/SetupLayout';
import { DashboardPlaceholder } from '@/pages/placeholders/DashboardPlaceholder';
import { ToolsPlaceholder } from '@/pages/placeholders/ToolsPlaceholder';
import { ToolDetailPlaceholder } from '@/pages/placeholders/ToolDetailPlaceholder';
import { EarningsPlaceholder } from '@/pages/placeholders/EarningsPlaceholder';
import { SessionsPlaceholder } from '@/pages/placeholders/SessionsPlaceholder';
import { SessionDetailPlaceholder } from '@/pages/placeholders/SessionDetailPlaceholder';
import { LogsPlaceholder } from '@/pages/placeholders/LogsPlaceholder';
import { SettingsPlaceholder } from '@/pages/placeholders/SettingsPlaceholder';
import { UnlockPlaceholder } from '@/pages/placeholders/UnlockPlaceholder';
import { NotFound } from '@/pages/NotFound';

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
  mockFetch.mockResolvedValue(
    jsonResponse({
      setup_complete: false,
      locked: false,
      unlocked: true,
      current_step: 0,
    }),
  );
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
      { index: true, element: <Navigate to="/setup/welcome" replace /> },
      { path: 'welcome', element: <div>Setup Welcome</div> },
      { path: 'unlock', element: <UnlockPlaceholder /> },
    ],
  },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { path: 'dashboard', element: <DashboardPlaceholder /> },
      { path: 'tools', element: <ToolsPlaceholder /> },
      { path: 'tools/:id', element: <ToolDetailPlaceholder /> },
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
      expect(screen.getByText('Manage your registered MCP tools.')).toBeInTheDocument(),
    );
  });

  it('renders tool detail page', async () => {
    renderRoute('/tools/123');
    await waitFor(() =>
      expect(screen.getByText('Configure and monitor a specific tool.')).toBeInTheDocument(),
    );
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
    await waitFor(() => expect(screen.getByText('Unlock Node')).toBeInTheDocument());
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
