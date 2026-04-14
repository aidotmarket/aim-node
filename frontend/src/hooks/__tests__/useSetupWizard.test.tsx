import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor, act } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { SetupWizardProvider, useSetupWizard } from '../useSetupWizard';

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
    <QueryClientProvider client={queryClient}>
      <SetupWizardProvider>{children}</SetupWizardProvider>
    </QueryClientProvider>
  );
}

describe('useSetupWizard', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('initializes the wizard from the backend current_step', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: true,
        current_step: 2,
      }),
    );

    const { result } = renderHook(() => useSetupWizard(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.isLoading).toBe(false));
    expect(result.current.currentStep).toBe(2);
    expect(result.current.stepStatus).toMatchObject({
      0: 'complete',
      1: 'complete',
      2: 'active',
      3: 'pending',
      4: 'pending',
    });
  });

  it('blocks next until the current step is complete', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: false,
        current_step: 1,
      }),
    );

    const { result } = renderHook(() => useSetupWizard(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.currentStep).toBe(1));

    act(() => {
      result.current.next();
    });

    expect(result.current.currentStep).toBe(1);
  });

  it('advances after markComplete marks the current step complete', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: false,
        current_step: 2,
      }),
    );

    const { result } = renderHook(() => useSetupWizard(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.currentStep).toBe(2));

    act(() => {
      result.current.markComplete(2);
    });

    act(() => {
      result.current.next();
    });

    expect(result.current.currentStep).toBe(3);
    expect(result.current.stepStatus[2]).toBe('complete');
    expect(result.current.stepStatus[3]).toBe('active');
  });

  it('allows moving backward regardless of completion state', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: false,
        current_step: 3,
      }),
    );

    const { result } = renderHook(() => useSetupWizard(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.currentStep).toBe(3));

    act(() => {
      result.current.back();
    });

    expect(result.current.currentStep).toBe(2);
    expect(result.current.stepStatus[2]).toBe('active');
    expect(result.current.stepStatus[3]).toBe('complete');
  });

  it('goToStep only allows jumping to completed steps', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: false,
        locked: false,
        unlocked: false,
        current_step: 3,
      }),
    );

    const { result } = renderHook(() => useSetupWizard(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.currentStep).toBe(3));

    act(() => {
      result.current.goToStep(1);
    });

    expect(result.current.currentStep).toBe(1);
    expect(result.current.stepStatus[1]).toBe('active');

    act(() => {
      result.current.goToStep(4);
    });

    expect(result.current.currentStep).toBe(1);
  });

  it('clamps completed backend state to the review step and marks all steps complete', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        setup_complete: true,
        locked: false,
        unlocked: true,
        current_step: 5,
      }),
    );

    const { result } = renderHook(() => useSetupWizard(), { wrapper: createWrapper() });

    await waitFor(() => expect(result.current.currentStep).toBe(4));
    expect(result.current.stepStatus).toMatchObject({
      0: 'complete',
      1: 'complete',
      2: 'complete',
      3: 'complete',
      4: 'complete',
    });
  });
});
