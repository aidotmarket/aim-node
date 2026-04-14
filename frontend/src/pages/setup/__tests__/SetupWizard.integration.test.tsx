import { useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, MemoryRouter, Route, RouterProvider, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupLayout } from '@/layouts/SetupLayout';
import { SetupWizardProvider, useSetupWizard } from '@/hooks/useSetupWizard';
import { SetupIndexRedirect } from '@/router';
import { WelcomeStep } from '../WelcomeStep';
import { KeypairStep } from '../KeypairStep';
import { ConnectionStep } from '../ConnectionStep';
import { UpstreamStep } from '../UpstreamStep';
import { ReviewStep } from '../ReviewStep';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function ConsumerModeSeed() {
  const { setConnection, setMode } = useSetupWizard();

  useEffect(() => {
    setConnection({
      apiUrl: 'https://api.ai.market',
      apiKey: 'seeded-api-key',
      reachable: true,
      version: '2026.4.0',
    });
    setMode('consumer');
  }, []);

  return <UpstreamStep />;
}

function renderWizard(initialEntries = ['/setup']) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  const router = createMemoryRouter(
    [
      {
        path: '/setup',
        element: <SetupLayout />,
        children: [
          { index: true, element: <SetupIndexRedirect /> },
          { path: 'welcome', element: <WelcomeStep /> },
          { path: 'keypair', element: <KeypairStep /> },
          { path: 'connection', element: <ConnectionStep /> },
          { path: 'upstream', element: <UpstreamStep /> },
          { path: 'review', element: <ReviewStep /> },
        ],
      },
      { path: '/dashboard', element: <div>Dashboard Route</div> },
    ],
    { initialEntries },
  );

  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

function renderSeededConsumerUpstreamFlow() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/setup/upstream']}>
        <SetupWizardProvider>
          <Routes>
            <Route path="/setup/upstream" element={<ConsumerModeSeed />} />
            <Route path="/setup/review" element={<ReviewStep />} />
            <Route path="/dashboard" element={<div>Dashboard Route</div>} />
          </Routes>
        </SetupWizardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Setup wizard integration', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('completes the happy path from welcome to finalize', async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({
          setup_complete: false,
          locked: false,
          unlocked: true,
          current_step: 0,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          fingerprint: 'ab:cd:ef:12',
          created: true,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          reachable: true,
          version: '2026.4.0',
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          reachable: true,
          latency_ms: 32,
          tools_found: 3,
          error: null,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ok: true,
        }),
      );

    renderWizard();

    expect(await screen.findByText('Welcome to AIM Node')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Create Passphrase'), {
      target: { value: 'SecurePassphrase1' },
    });
    fireEvent.change(screen.getByLabelText('Confirm Passphrase'), {
      target: { value: 'SecurePassphrase1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByText('Generate your node identity')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Generate Keypair' }));
    expect(await screen.findByText('ab:cd:ef:12')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByText('Connect to ai.market')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('API Key'), {
      target: { value: 'secret-key' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }));
    expect(await screen.findByText('Version 2026.4.0')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByText('Configure upstream endpoint')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('MCP Endpoint URL'), {
      target: { value: 'https://upstream.example.com/mcp' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Test Upstream' }));
    expect(await screen.findByText('3 tools found')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Continue' }));

    expect(await screen.findByText('Review & Finalize')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Finalize Setup' }));

    expect(await screen.findByText('Dashboard Route')).toBeInTheDocument();
    expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/keypair');
    expect(mockFetch.mock.calls[2][0]).toBe('/api/mgmt/setup/test-connection');
    expect(mockFetch.mock.calls[3][0]).toBe('/api/mgmt/setup/test-upstream');
    expect(mockFetch.mock.calls[4][0]).toBe('/api/mgmt/setup/finalize');
    expect(mockFetch.mock.calls[4][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        mode: 'consumer',
        api_url: 'https://api.ai.market',
        api_key: 'secret-key',
        upstream_url: 'https://upstream.example.com/mcp',
      }),
    });
  });

  it('resumes from the current step when reopening /setup', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: true,
        current_step: 2,
      }),
    );

    renderWizard();

    expect(await screen.findByText('Connect to ai.market')).toBeInTheDocument();
  });

  it('allows skipping upstream and omits upstream_url on consumer finalize', async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({
          setup_complete: false,
          locked: false,
          unlocked: true,
          current_step: 3,
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          reachable: false,
          latency_ms: null,
          tools_found: 0,
          error: 'timeout',
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          ok: true,
        }),
      );

    renderSeededConsumerUpstreamFlow();

    expect(await screen.findByText('Configure upstream endpoint')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('MCP Endpoint URL'), {
      target: { value: 'https://upstream.example.com/mcp' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Test Upstream' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('timeout');

    fireEvent.click(screen.getByRole('button', { name: 'Skip for now' }));
    expect(await screen.findByText('Review & Finalize')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Finalize Setup' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(3));
    expect(mockFetch.mock.calls[2][0]).toBe('/api/mgmt/setup/finalize');
    expect(mockFetch.mock.calls[2][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        mode: 'consumer',
        api_url: 'https://api.ai.market',
        api_key: 'seeded-api-key',
      }),
    });
    expect(await screen.findByText('Dashboard Route')).toBeInTheDocument();
  });
});
