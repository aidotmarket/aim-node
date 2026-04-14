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

function SkippedUpstreamProviderSeed({
  mode,
}: {
  mode: 'provider' | 'both';
}) {
  const { setConnection, setFingerprint, setMode, setUpstream } = useSetupWizard();

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
      reachable: false,
      toolsFound: 0,
      error: 'timeout',
      skipped: true,
    });
    setMode(mode);
  }, [mode, setConnection, setFingerprint, setMode, setUpstream]);

  return <ReviewStep />;
}

function renderReviewStep(mode: 'provider' | 'both') {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/setup/review']}>
        <SetupWizardProvider>
          <Routes>
            <Route path="/setup/review" element={<SkippedUpstreamProviderSeed mode={mode} />} />
            <Route path="/dashboard" element={<div>Dashboard Route</div>} />
          </Routes>
        </SetupWizardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ReviewStep skipped upstream finalize', () => {
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

  it.each(['provider', 'both'] as const)(
    'includes upstream_url in the finalize payload when upstream was skipped in %s mode',
    async (mode) => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({
          ok: true,
        }),
      );

      renderReviewStep(mode);

      fireEvent.click(await screen.findByRole('button', { name: 'Finalize Setup' }));

      await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
      expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/finalize');
      expect(mockFetch.mock.calls[1][1]).toMatchObject({
        method: 'POST',
        body: JSON.stringify({
          mode,
          api_url: 'https://api.ai.market',
          api_key: 'secret-key',
          upstream_url: 'https://upstream.example.com/mcp',
        }),
      });
      expect(await screen.findByText('Dashboard Route')).toBeInTheDocument();
    },
  );
});
