import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupWizardProvider } from '@/hooks/useSetupWizard';
import { UpstreamStep } from '../UpstreamStep';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderUpstreamStep() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <SetupWizardProvider>
          <UpstreamStep />
        </SetupWizardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('UpstreamStep', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: true,
        current_step: 3,
      }),
    );
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('renders the upstream form', async () => {
    renderUpstreamStep();

    expect(await screen.findByText('Configure upstream endpoint')).toBeInTheDocument();
    expect(screen.getByLabelText('MCP Endpoint URL')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Test Upstream' })).toBeDisabled();
  });

  it('posts the upstream url and shows discovered tools on success', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        reachable: true,
        latency_ms: 42,
        tools_found: 7,
        error: null,
      }),
    );

    renderUpstreamStep();

    fireEvent.change(await screen.findByLabelText('MCP Endpoint URL'), {
      target: { value: 'https://upstream.example.com/mcp' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Test Upstream' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/test-upstream');
    expect(mockFetch.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        url: 'https://upstream.example.com/mcp',
      }),
    });
    expect(await screen.findByText('Upstream status:')).toBeInTheDocument();
    expect(screen.getAllByText('Reachable')).toHaveLength(2);
    expect(screen.getByText('7 tools found')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });

  it('displays the backend error and skip warning when the test response is unreachable', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        reachable: false,
        latency_ms: null,
        tools_found: 0,
        error: 'Handshake failed',
      }),
    );

    renderUpstreamStep();

    fireEvent.change(await screen.findByLabelText('MCP Endpoint URL'), {
      target: { value: 'https://upstream.example.com/mcp' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Test Upstream' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Handshake failed');
    expect(screen.getByText('You can configure this later in Settings')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Skip for now' })).toBeInTheDocument();
  });

  it('allows the user to skip after a failure warning', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          code: 'upstream_unreachable',
          message: 'Timed out while connecting upstream',
        },
        504,
      ),
    );

    renderUpstreamStep();

    fireEvent.change(await screen.findByLabelText('MCP Endpoint URL'), {
      target: { value: 'https://upstream.example.com/mcp' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Test Upstream' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Skip for now' }));

    expect(await screen.findByText('You can configure this later in Settings')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });
});
