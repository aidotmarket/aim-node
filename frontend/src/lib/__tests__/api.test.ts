import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { api, ApiError } from '../api';

describe('ApiClient', () => {
  const mockFetch = vi.fn();
  const originalFetch = globalThis.fetch;

  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  function jsonResponse(data: unknown, status = 200, headers?: Record<string, string>) {
    return new Response(JSON.stringify(data), {
      status,
      headers: { 'Content-Type': 'application/json', ...headers },
    });
  }

  describe('GET', () => {
    it('fetches from the correct URL', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));
      const result = await api.get('/health');
      expect(result).toEqual({ ok: true });
      expect(mockFetch).toHaveBeenCalledOnce();
      const url = mockFetch.mock.calls[0][0];
      expect(url).toContain('/api/mgmt/health');
    });

    it('appends query params', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({}));
      await api.get('/search', { q: 'test', page: '2' });
      const url = mockFetch.mock.calls[0][0];
      expect(url).toContain('q=test');
      expect(url).toContain('page=2');
    });
  });

  describe('POST', () => {
    it('sends JSON body with correct headers', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ id: 1 }));
      const result = await api.post('/items', { name: 'test' });
      expect(result).toEqual({ id: 1 });
      const [, init] = mockFetch.mock.calls[0];
      expect(init.method).toBe('POST');
      expect(init.headers['Content-Type']).toBe('application/json');
      expect(JSON.parse(init.body)).toEqual({ name: 'test' });
    });

    it('sends no body when none provided', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));
      await api.post('/action');
      const [, init] = mockFetch.mock.calls[0];
      expect(init.body).toBeUndefined();
    });
  });

  describe('DELETE', () => {
    it('sends DELETE request', async () => {
      mockFetch.mockResolvedValueOnce(jsonResponse({ deleted: true }));
      const result = await api.delete('/items/1');
      expect(result).toEqual({ deleted: true });
      const [, init] = mockFetch.mock.calls[0];
      expect(init.method).toBe('DELETE');
    });
  });

  describe('error parsing', () => {
    it('throws ApiError with code and status on non-ok response', async () => {
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ code: 'not_found', message: 'Item not found' }, 404),
      );
      try {
        await api.get('/missing');
        expect.fail('should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.code).toBe('not_found');
        expect(apiErr.message).toBe('Item not found');
        expect(apiErr.status).toBe(404);
      }
    });

    it('handles non-JSON error bodies gracefully', async () => {
      mockFetch.mockResolvedValueOnce(new Response('Internal Server Error', { status: 500 }));
      try {
        await api.get('/broken');
        expect.fail('should have thrown');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.code).toBe('unknown');
        expect(apiErr.status).toBe(500);
      }
    });
  });

  describe('CSRF extraction', () => {
    it('extracts CSRF token from response and sends it on subsequent POST', async () => {
      // First request returns a CSRF token in response header
      mockFetch.mockResolvedValueOnce(
        jsonResponse({ ok: true }, 200, { 'X-CSRF-Token': 'tok-abc123' }),
      );
      await api.get('/health');

      // Second POST should include the extracted token
      mockFetch.mockResolvedValueOnce(jsonResponse({ ok: true }));
      await api.post('/action', { data: 1 });
      const [, init] = mockFetch.mock.calls[1];
      expect(init.headers['X-CSRF-Token']).toBe('tok-abc123');
    });
  });
});
