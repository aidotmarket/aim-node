import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { PublishFlow } from '../PublishFlow';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderPublishFlow(initialEntries: string[] = ['/tools/publish?toolId=tool-alpha']) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/tools/publish" element={<PublishFlow />} />
          <Route path="/tools/:toolId" element={<div>Tool Detail Route</div>} />
          <Route path="/tools" element={<div>Tools List Route</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function defaultFetchImpl({
  publishStatus = 200,
  publishBody = { id: 'mt-1', status: 'published' },
}: { publishStatus?: number; publishBody?: unknown } = {}) {
  return (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const method = init?.method ?? 'GET';

    if (url.includes('/api/mgmt/tools/tool-alpha')) {
      return Promise.resolve(
        jsonResponse({
          tool_id: 'tool-alpha',
          name: 'alpha.tool',
          version: '1.2.3',
          description: 'desc',
          input_schema: { type: 'object' },
          output_schema: { type: 'object' },
          validation_status: 'passed',
          last_scanned_at: '2026-04-14T12:00:00Z',
          last_validated_at: null,
        }),
      );
    }

    if (url.includes('/api/mgmt/marketplace/tools/publish') && method === 'POST') {
      return Promise.resolve(jsonResponse(publishBody, publishStatus));
    }

    if (url.includes('/api/mgmt/marketplace/tools')) {
      return Promise.resolve(jsonResponse({ tools: [] }));
    }

    if (url.includes('/api/mgmt/marketplace/listings')) {
      return Promise.resolve(
        jsonResponse({
          listings: [
            { listing_id: 'listing-1', title: 'Existing Listing' },
          ],
        }),
      );
    }

    if (url.includes('/api/mgmt/tools') && !url.includes('marketplace')) {
      return Promise.resolve(
        jsonResponse({
          tools: [
            {
              tool_id: 'tool-alpha',
              name: 'alpha.tool',
              version: '1.2.3',
              description: 'desc',
              validation_status: 'passed',
              last_scanned_at: '2026-04-14T12:00:00Z',
            },
          ],
          scanned_at: '2026-04-14T12:00:00Z',
        }),
      );
    }

    return Promise.reject(new Error(`Unhandled URL: ${url}`));
  };
}

describe('PublishFlow', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });
  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('navigates through steps and publishes with correct payload shape', async () => {
    mockFetch.mockImplementation(defaultFetchImpl());

    renderPublishFlow();

    expect(await screen.findByText(/Step 1 of 5/)).toBeInTheDocument();

    // Step 1: tool pre-selected via ?toolId=
    const toolSelect = (await screen.findByLabelText('Tool')) as HTMLSelectElement;
    await waitFor(() => expect(toolSelect.value).toBe('tool-alpha'));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Step 2: choose listing
    await screen.findByText(/Step 2 of 5/);
    const listingSelect = await screen.findByLabelText('Listing');
    fireEvent.change(listingSelect, { target: { value: 'listing-1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Step 3: description
    await screen.findByText(/Step 3 of 5/);
    fireEvent.change(screen.getByLabelText('Natural language description'), {
      target: { value: 'does things' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Step 4: pricing
    await screen.findByText(/Step 4 of 5/);
    fireEvent.change(screen.getByLabelText('Price (cents)'), { target: { value: '25' } });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    // Step 5: review
    await screen.findByText(/Step 5 of 5/);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Publish' }));
    });

    await waitFor(() => {
      expect(screen.getByText('Tool Detail Route')).toBeInTheDocument();
    });

    const publishCall = mockFetch.mock.calls.find(([url, init]) =>
      String(url).includes('/marketplace/tools/publish') && (init as RequestInit | undefined)?.method === 'POST',
    );
    expect(publishCall).toBeDefined();
    const body = JSON.parse((publishCall![1] as RequestInit).body as string);
    expect(body).toMatchObject({
      listing_id: 'listing-1',
      tool_name: 'alpha.tool',
      version: '1.2.3',
      nl_description: 'does things',
      pricing_formula: { model: 'per_call', price_cents: 25 },
      execution_mode: 'sync',
      task_taxonomy_tags: [],
      sample_io_pairs: [],
    });
    expect(body.input_schema).toEqual({ type: 'object' });
    expect(body.output_schema).toEqual({ type: 'object' });
  });

  it('shows error on publish failure and stays on review step', async () => {
    mockFetch.mockImplementation(
      defaultFetchImpl({
        publishStatus: 400,
        publishBody: { code: 'bad_request', message: 'listing invalid' },
      }),
    );

    renderPublishFlow();

    await screen.findByText(/Step 1 of 5/);
    const toolSelect = (await screen.findByLabelText('Tool')) as HTMLSelectElement;
    await waitFor(() => expect(toolSelect.value).toBe('tool-alpha'));
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    await screen.findByText(/Step 2 of 5/);
    fireEvent.change(await screen.findByLabelText('Listing'), {
      target: { value: 'listing-1' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    await screen.findByText(/Step 3 of 5/);
    fireEvent.change(screen.getByLabelText('Natural language description'), {
      target: { value: 'x' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    await screen.findByText(/Step 4 of 5/);
    fireEvent.click(screen.getByRole('button', { name: 'Next' }));

    await screen.findByText(/Step 5 of 5/);

    await act(async () => {
      fireEvent.click(screen.getByRole('button', { name: 'Publish' }));
    });

    expect(await screen.findByText(/listing invalid/)).toBeInTheDocument();
    expect(screen.getByText(/Step 5 of 5/)).toBeInTheDocument();
  });
});
