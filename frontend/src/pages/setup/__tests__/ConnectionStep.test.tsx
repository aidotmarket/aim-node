import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupWizardProvider } from '@/hooks/useSetupWizard';
import { ConnectionStep } from '../ConnectionStep';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderConnectionStep() {
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
          <ConnectionStep />
        </SetupWizardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ConnectionStep', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: true,
        current_step: 2,
      }),
    );
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('renders the form with the default api url prefilled', async () => {
    renderConnectionStep();

    expect(await screen.findByText('Connect to ai.market')).toBeInTheDocument();
    expect(screen.getByLabelText('API URL')).toHaveValue('https://api.ai.market');
    expect(screen.getByLabelText('API Key')).toHaveValue('');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('posts the exact connection payload and shows reachable status with version', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        reachable: true,
        version: '2026.4.0',
      }),
    );

    renderConnectionStep();

    fireEvent.change(await screen.findByLabelText('API Key'), { target: { value: 'secret-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/test-connection');
    expect(mockFetch.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({
        api_url: 'https://api.ai.market',
        api_key: 'secret-key',
      }),
    });
    expect(await screen.findByText('Connection status:')).toBeInTheDocument();
    expect(screen.getAllByText('Reachable')).toHaveLength(2);
    expect(screen.getByText('Version 2026.4.0')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });

  it('shows unreachable status when the backend reports reachable false', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        reachable: false,
        version: null,
      }),
    );

    renderConnectionStep();

    fireEvent.change(await screen.findByLabelText('API Key'), { target: { value: 'secret-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }));

    expect(await screen.findByText('Connection status:')).toBeInTheDocument();
    expect(screen.getAllByText('Unreachable')).toHaveLength(2);
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('displays an error message when the request fails', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          code: 'connection_failed',
          message: 'Unable to reach api.ai.market',
        },
        502,
      ),
    );

    renderConnectionStep();

    fireEvent.change(await screen.findByLabelText('API Key'), { target: { value: 'secret-key' } });
    fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Unable to reach api.ai.market');
    expect(screen.getAllByText('Unreachable')).toHaveLength(2);
  });
});
