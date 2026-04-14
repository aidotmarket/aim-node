import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupWizardProvider } from '@/hooks/useSetupWizard';
import { KeypairStep } from '../KeypairStep';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();
const writeText = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderKeypairStep(initialPassphrase = 'SecurePassphrase1') {
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
        <SetupWizardProvider initialPassphrase={initialPassphrase}>
          <KeypairStep />
        </SetupWizardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('KeypairStep', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
    Object.defineProperty(globalThis.navigator, 'clipboard', {
      configurable: true,
      value: { writeText },
    });
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: true,
        current_step: 1,
      }),
    );
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
    writeText.mockReset();
  });

  it('posts the passphrase to the keypair endpoint and displays the fingerprint', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        fingerprint: 'ab:cd:ef:12',
        created: true,
      }),
    );

    renderKeypairStep();

    fireEvent.click(await screen.findByRole('button', { name: 'Generate Keypair' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(mockFetch.mock.calls[1][0]).toBe('/api/mgmt/setup/keypair');
    expect(mockFetch.mock.calls[1][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ passphrase: 'SecurePassphrase1' }),
    });
    expect(await screen.findByText('ab:cd:ef:12')).toBeInTheDocument();
    expect(screen.getByText('Created')).toBeInTheDocument();
  });

  it('shows the existing-keypair status from the response when created is false', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        fingerprint: 'ff:ee:dd:44',
        created: false,
      }),
    );

    renderKeypairStep();

    fireEvent.click(await screen.findByRole('button', { name: 'Generate Keypair' }));

    expect(await screen.findByText('ff:ee:dd:44')).toBeInTheDocument();
    expect(screen.getByText('Reused existing')).toBeInTheDocument();
  });

  it('copies the fingerprint to the clipboard', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        fingerprint: '11:22:33:44',
        created: true,
      }),
    );
    writeText.mockResolvedValue(undefined);

    renderKeypairStep();

    fireEvent.click(await screen.findByRole('button', { name: 'Generate Keypair' }));
    await screen.findByText('11:22:33:44');

    fireEvent.click(screen.getByRole('button', { name: 'Copy' }));

    await waitFor(() => expect(writeText).toHaveBeenCalledWith('11:22:33:44'));
    expect(screen.getByRole('button', { name: 'Copied' })).toBeInTheDocument();
  });

  it('shows a 409 conflict error when a keypair already exists', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse(
        {
          code: 'keypair_exists',
          message: 'Keypair already exists',
        },
        409,
      ),
    );

    renderKeypairStep();

    fireEvent.click(await screen.findByRole('button', { name: 'Generate Keypair' }));

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'A node identity already exists for this installation.',
    );
    expect(screen.getByText('Already exists')).toBeInTheDocument();
  });
});
