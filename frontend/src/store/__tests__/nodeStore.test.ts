import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { useNodeStore } from '../nodeStore';

describe('nodeStore', () => {
  const mockFetch = vi.fn();
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = mockFetch;
    useNodeStore.setState(useNodeStore.getInitialState(), true);
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  function jsonResponse(data: unknown, status = 200) {
    return new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json' },
    });
  }

  it('has correct initial state', () => {
    const state = useNodeStore.getState();
    expect(state.setupComplete).toBe(false);
    expect(state.locked).toBe(false);
    expect(state.healthStatus).toBe('unknown');
    expect(state.csrfToken).toBeNull();
    expect(state.loading).toBe(true);
  });

  it('bootstrap populates state from health response', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        healthy: true,
        locked: false,
        setup_complete: true,
        csrf_token: 'tok',
      }),
    );

    await useNodeStore.getState().bootstrap();

    const state = useNodeStore.getState();
    expect(state.setupComplete).toBe(true);
    expect(state.locked).toBe(false);
    expect(state.healthStatus).toBe('healthy');
    expect(state.csrfToken).toBe('tok');
    expect(state.loading).toBe(false);
  });

  it('bootstrap sets degraded status for non-healthy response', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({ healthy: false, locked: false, setup_complete: false }),
    );

    await useNodeStore.getState().bootstrap();

    expect(useNodeStore.getState().healthStatus).toBe('degraded');
  });

  it('bootstrap handles fetch error gracefully', async () => {
    mockFetch.mockRejectedValueOnce(new Error('Network error'));

    await useNodeStore.getState().bootstrap();

    const state = useNodeStore.getState();
    expect(state.healthStatus).toBe('unknown');
    expect(state.loading).toBe(false);
  });

  it('sets loading true during bootstrap', async () => {
    let resolvePromise: (value: Response) => void;
    const pending = new Promise<Response>((resolve) => { resolvePromise = resolve; });
    mockFetch.mockReturnValueOnce(pending);

    const bootstrapPromise = useNodeStore.getState().bootstrap();

    // Should be loading while fetch is pending
    expect(useNodeStore.getState().loading).toBe(true);

    resolvePromise!(jsonResponse({ healthy: true, locked: false, setup_complete: true }));
    await bootstrapPromise;

    expect(useNodeStore.getState().loading).toBe(false);
  });
});
