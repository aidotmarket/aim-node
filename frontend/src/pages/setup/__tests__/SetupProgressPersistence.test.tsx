import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupLayout } from '@/layouts/SetupLayout';
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

describe('setup progress persistence', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('resumes at the connection step after a successful keypair request saves progress', async () => {
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
          setup_complete: false,
          locked: false,
          unlocked: true,
          current_step: 2,
        }),
      );

    const firstRender = renderWizard();

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
    expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/keypair');

    firstRender.unmount();
    renderWizard();

    expect(await screen.findByText('Connect to ai.market')).toBeInTheDocument();
    expect(mockFetch.mock.calls[2][0]).toContain('/api/mgmt/setup/status');
  });

  it('resumes at the upstream step after a successful connection test saves progress', async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse({
          setup_complete: false,
          locked: false,
          unlocked: true,
          current_step: 2,
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
          setup_complete: false,
          locked: false,
          unlocked: true,
          current_step: 3,
        }),
      );

    const firstRender = renderWizard(['/setup/connection']);

    expect(await screen.findByText('Connect to ai.market')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('API Key'), {
      target: { value: 'secret-key' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Test Connection' }));

    expect(await screen.findByText('Version 2026.4.0')).toBeInTheDocument();
    expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/test-connection');

    firstRender.unmount();
    renderWizard();

    expect(await screen.findByText('Configure upstream endpoint')).toBeInTheDocument();
    expect(mockFetch.mock.calls[2][0]).toContain('/api/mgmt/setup/status');
  });
});
