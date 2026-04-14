import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToolDetailPage } from '../ToolDetailPage';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderToolDetailPage(initialEntries: string[] = ['/tools/tool-alpha']) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={initialEntries}>
        <Routes>
          <Route path="/tools/:toolId" element={<ToolDetailPage />} />
          <Route path="/setup/review" element={<div>Setup Review Route</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ToolDetailPage', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('renders tool detail, schemas, and action buttons', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);

      if (url.includes('/api/mgmt/tools/tool-alpha')) {
        return Promise.resolve(
          jsonResponse({
            tool_id: 'tool-alpha',
            name: 'alpha.tool',
            version: '1.2.3',
            description: 'Summarizes records',
            input_schema: {
              type: 'object',
              properties: {
                text: { type: 'string' },
              },
            },
            output_schema: {
              type: 'object',
              properties: {
                summary: { type: 'string' },
              },
            },
            validation_status: 'passed',
            last_scanned_at: '2026-04-14T12:00:00Z',
            last_validated_at: '2026-04-14T12:05:00Z',
          }),
        );
      }

      if (url.includes('/api/mgmt/marketplace/tools')) {
        return Promise.resolve(
          jsonResponse({
            tools: [
              {
                tool_name: 'alpha.tool',
                listing_id: 'listing-1',
                status: 'published',
                price_usd: 1.25,
                updated_at: '2026-04-14T12:10:00Z',
              },
            ],
          }),
        );
      }

      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    renderToolDetailPage();

    expect(await screen.findByText('alpha.tool')).toBeInTheDocument();
    expect(screen.getByText('Summarizes records')).toBeInTheDocument();
    expect(screen.getByText('Input Schema')).toBeInTheDocument();
    expect(screen.getByText('Output Schema')).toBeInTheDocument();
    expect(screen.getAllByText('Published').length).toBeGreaterThan(0);
    expect(screen.getAllByText('$1.25').length).toBeGreaterThan(0);
    expect(screen.getByRole('button', { name: 'Publish' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Update' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unpublish' })).toBeInTheDocument();
  });

  it('shows the registration banner when marketplace data is unavailable with 412', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);

      if (url.includes('/api/mgmt/tools/tool-alpha')) {
        return Promise.resolve(
          jsonResponse({
            tool_id: 'tool-alpha',
            name: 'alpha.tool',
            version: '1.2.3',
            description: 'Summarizes records',
            input_schema: { type: 'object' },
            output_schema: { type: 'object' },
            validation_status: 'pending',
            last_scanned_at: '2026-04-14T12:00:00Z',
            last_validated_at: null,
          }),
        );
      }

      if (url.includes('/api/mgmt/marketplace/tools')) {
        return Promise.resolve(
          jsonResponse(
            {
              code: 'setup_incomplete',
              message: 'Node not yet configured',
            },
            412,
          ),
        );
      }

      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    renderToolDetailPage();

    expect(
      await screen.findByText('Complete node registration to manage marketplace tools'),
    ).toBeInTheDocument();
    expect(screen.getByText('alpha.tool')).toBeInTheDocument();
    expect(screen.getAllByText('Unpublished').length).toBeGreaterThan(0);
  });
});

