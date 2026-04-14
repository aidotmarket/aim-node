import { useEffect } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupWizardProvider, useSetupWizard } from '@/hooks/useSetupWizard';
import { ReviewStep } from '../ReviewStep';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function WizardSeed() {
  const { setFingerprint, setConnection, setUpstream, setMode } = useSetupWizard();

  useEffect(() => {
    setFingerprint('ab:cd:ef:12');
    setConnection({
      apiUrl: 'https://api.ai.market',
      apiKey: 'secret-key',
      reachable: true,
      version: '2026.4.0',
    });
    setUpstream({
      url: 'https://upstream.example.com/mcp',
      reachable: true,
      toolsFound: 4,
      error: null,
      skipped: false,
    });
    setMode('both');
  }, []);

  return <ReviewStep />;
}

function renderReviewStep(initialEntries = ['/setup/review']) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <SetupWizardProvider>
          <Routes>
            <Route path="/setup/review" element={<WizardSeed />} />
            <Route path="/setup/keypair" element={<div>Keypair Route</div>} />
            <Route path="/setup/connection" element={<div>Connection Route</div>} />
            <Route path="/setup/upstream" element={<div>Upstream Route</div>} />
            <Route path="/dashboard" element={<div>Dashboard Route</div>} />
          </Routes>
        </SetupWizardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReviewStep', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: true,
        current_step: 4,
      }),
    );
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('renders the review summary from wizard state', async () => {
    renderReviewStep();

    expect(await screen.findByText('Review & Finalize')).toBeInTheDocument();
    expect(screen.getByText('ab:cd:ef:12')).toBeInTheDocument();
    expect(screen.getByText('Version 2026.4.0')).toBeInTheDocument();
    expect(screen.getByText('https://upstream.example.com/mcp')).toBeInTheDocument();
    expect(screen.getByText('4 tools found')).toBeInTheDocument();
  });

  it('updates the selected mode through the radio group', async () => {
    renderReviewStep();

    const providerRadio = await screen.findByRole('radio', { name: 'Provider' });
    fireEvent.click(providerRadio);

    expect(providerRadio).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Both' })).not.toBeChecked();
  });

  it('edit links navigate back to earlier setup steps', async () => {
    renderReviewStep();

    fireEvent.click(await screen.findByRole('link', { name: 'Edit node identity' }));
    expect(await screen.findByText('Keypair Route')).toBeInTheDocument();
  });

  it('finalize sends the full request body and redirects to the dashboard', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        ok: true,
      }),
    );

    renderReviewStep();

    fireEvent.click(await screen.findByRole('button', { name: 'Finalize Setup' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/finalize');
    expect(mockFetch.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        mode: 'both',
        api_url: 'https://api.ai.market',
        api_key: 'secret-key',
        upstream_url: 'https://upstream.example.com/mcp',
      }),
    });
    expect(await screen.findByText('Dashboard Route')).toBeInTheDocument();
  });
});
