import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupWizardProvider } from '@/hooks/useSetupWizard';
import { WelcomeStep } from '../WelcomeStep';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderWelcomeStep() {
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
          <WelcomeStep />
        </SetupWizardProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('WelcomeStep', () => {
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

  it('renders the passphrase form with continue disabled by default', async () => {
    renderWelcomeStep();

    await waitFor(() => expect(screen.getByText('Welcome to AIM Node')).toBeInTheDocument());
    expect(screen.getByLabelText('Create Passphrase')).toBeInTheDocument();
    expect(screen.getByLabelText('Confirm Passphrase')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('shows a weak red strength state for a short passphrase', async () => {
    renderWelcomeStep();

    const passphraseInput = await screen.findByLabelText('Create Passphrase');
    fireEvent.change(passphraseInput, { target: { value: 'short' } });

    expect(screen.getByTestId('passphrase-strength-fill')).toHaveClass('bg-brand-error');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('shows a warning yellow strength state when the number requirement is missing', async () => {
    renderWelcomeStep();

    const passphraseInput = await screen.findByLabelText('Create Passphrase');
    fireEvent.change(passphraseInput, { target: { value: 'ValidPassphrase' } });

    expect(screen.getByTestId('passphrase-strength-fill')).toHaveClass('bg-brand-warning');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('keeps continue disabled when the uppercase requirement is missing', async () => {
    renderWelcomeStep();

    const passphraseInput = await screen.findByLabelText('Create Passphrase');
    const confirmInput = screen.getByLabelText('Confirm Passphrase');

    fireEvent.change(passphraseInput, { target: { value: 'lowercasepass1' } });
    fireEvent.change(confirmInput, { target: { value: 'lowercasepass1' } });

    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();
  });

  it('shows mismatch feedback and only enables continue for a valid matching passphrase', async () => {
    renderWelcomeStep();

    const passphraseInput = await screen.findByLabelText('Create Passphrase');
    const confirmInput = screen.getByLabelText('Confirm Passphrase');

    fireEvent.change(passphraseInput, { target: { value: 'SecurePassphrase1' } });
    fireEvent.change(confirmInput, { target: { value: 'SecurePassphrase2' } });

    expect(screen.getByText('Passphrases do not match')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Continue' })).toBeDisabled();

    fireEvent.change(confirmInput, { target: { value: 'SecurePassphrase1' } });

    expect(screen.getByTestId('passphrase-strength-fill')).toHaveClass('bg-brand-success');
    expect(screen.getByRole('button', { name: 'Continue' })).toBeEnabled();
  });
});
