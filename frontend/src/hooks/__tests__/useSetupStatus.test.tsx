import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useSetupStatus } from '../useSetupStatus';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

describe('useSetupStatus', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('returns setup status fields from the backend response', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: true,
        current_step: 2,
      }),
    );

    const { result } = renderHook(() => useSetupStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toEqual({
      setup_complete: false,
      locked: false,
      unlocked: true,
      current_step: 2,
    });
  });

  it('requests the setup status endpoint with the setup-status query key contract', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: true,
        locked: true,
        unlocked: false,
        current_step: 5,
      }),
    );

    const { result } = renderHook(() => useSetupStatus(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.data?.current_step).toBe(5));
    expect(mockFetch).toHaveBeenCalledOnce();
    expect(String(mockFetch.mock.calls[0][0])).toContain('/api/mgmt/setup/status');
  });
});
