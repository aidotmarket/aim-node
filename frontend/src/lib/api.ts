const API_BASE = '/api/mgmt';

export class ApiError extends Error {
  constructor(
    public code: string,
    message: string,
    public status: number,
    public details?: unknown,
  ) {
    super(message);
  }
}

class ApiClient {
  private csrfToken: string | null = null;

  async get<T>(path: string, params?: Record<string, string>): Promise<T> {
    const url = new URL(`${API_BASE}${path}`, window.location.origin);
    if (params) Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
    const res = await fetch(url.toString());
    this.extractCsrf(res);
    if (!res.ok) throw await this.parseError(res);
    return res.json();
  }

  async post<T>(path: string, body?: unknown): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
    });
    this.extractCsrf(res);
    if (!res.ok) throw await this.parseError(res);
    return res.json();
  }

  async delete<T>(path: string): Promise<T> {
    const res = await fetch(`${API_BASE}${path}`, {
      method: 'DELETE',
      headers: { ...(this.csrfToken ? { 'X-CSRF-Token': this.csrfToken } : {}) },
    });
    this.extractCsrf(res);
    if (!res.ok) throw await this.parseError(res);
    return res.json();
  }

  private extractCsrf(res: Response) {
    const token = res.headers.get('X-CSRF-Token');
    if (token) this.csrfToken = token;
  }

  private async parseError(res: Response): Promise<ApiError> {
    const body = await res.json().catch(() => ({}));
    return new ApiError(body.code ?? 'unknown', body.message ?? 'Request failed', res.status, body);
  }
}

export const api = new ApiClient();
