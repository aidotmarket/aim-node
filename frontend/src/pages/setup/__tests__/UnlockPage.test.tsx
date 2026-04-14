import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { UnlockPage } from '../UnlockPage';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderUnlockPage() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={['/setup/unlock']}>
        <Routes>
          <Route path="/setup/unlock" element={<UnlockPage />} />
          <Route path="/dashboard" element={<div>Dashboard Route</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('UnlockPage', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('renders the unlock form', () => {
    renderUnlockPage();

    expect(screen.getByText('Unlock your node')).toBeInTheDocument();
    expect(screen.getByLabelText('Passphrase')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unlock' })).toBeDisabled();
  });

  it('posts the exact unlock payload', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        unlocked: true,
      }),
    );

    renderUnlockPage();

    fireEvent.change(screen.getByLabelText('Passphrase'), {
      target: { value: 'test-passphrase' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Unlock' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(mockFetch.mock.calls[0][0]).toBe('/api/mgmt/unlock');
    expect(mockFetch.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ passphrase: 'test-passphrase' }),
    });
  });

  it('redirects to the dashboard after a successful unlock', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        unlocked: true,
      }),
    );

    renderUnlockPage();

    fireEvent.change(screen.getByLabelText('Passphrase'), {
      target: { value: 'correct-passphrase' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Unlock' }));

    expect(await screen.findByText('Dashboard Route')).toBeInTheDocument();
  });

  it('shows an error and allows retry after a failed unlock', async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse(
          {
            code: 'auth_failed',
            message: 'Invalid passphrase',
          },
          401,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          unlocked: true,
        }),
      );

    renderUnlockPage();

    const input = screen.getByLabelText('Passphrase');
    fireEvent.change(input, {
      target: { value: 'wrong-passphrase' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Unlock' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid passphrase');

    fireEvent.change(input, {
      target: { value: 'correct-passphrase' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Unlock' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Dashboard Route')).toBeInTheDocument();
  });
});
