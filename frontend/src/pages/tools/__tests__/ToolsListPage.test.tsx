import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { ToolsListPage } from '../ToolsListPage';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

function renderToolsListPage(initialEntries: string[] = ['/tools']) {
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
          <Route path="/tools" element={<ToolsListPage />} />
          <Route path="/setup/review" element={<div>Setup Review Route</div>} />
          <Route path="/tools/:toolId" element={<div>Tool Detail Route</div>} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ToolsListPage', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('renders merged local and marketplace tool data', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);

      if (url.includes('/api/mgmt/tools')) {
        return Promise.resolve(
          jsonResponse({
            scanned_at: '2026-04-14T12:00:00Z',
            tools: [
              {
                tool_id: 'tool-alpha',
                name: 'alpha.tool',
                version: '1.2.3',
                description: 'Summarizes records',
                validation_status: 'passed',
                last_scanned_at: '2026-04-14T12:00:00Z',
              },
            ],
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
                price_usd: 4.5,
              },
            ],
          }),
        );
      }

      return Promise.reject(new Error(`Unhandled URL: ${url}`));
    });

    renderToolsListPage();

    expect(await screen.findByText('alpha.tool')).toBeInTheDocument();
    expect(screen.getByText('Summarizes records')).toBeInTheDocument();
    expect(screen.getByText('Published')).toBeInTheDocument();
    expect(screen.getByText('$4.50')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /alpha\.tool/i })).toHaveAttribute(
      'href',
      '/tools/tool-alpha',
    );
  });

  it('shows the registration banner and still renders local tools on 412 marketplace response', async () => {
    mockFetch.mockImplementation((input: RequestInfo | URL) => {
      const url = String(input);

      if (url.includes('/api/mgmt/tools')) {
        return Promise.resolve(
          jsonResponse({
            scanned_at: '2026-04-14T12:00:00Z',
            tools: [
              {
                tool_id: 'tool-beta',
                name: 'beta.tool',
                version: '0.9.0',
                description: 'Extracts fields',
                validation_status: 'pending',
                last_scanned_at: '2026-04-14T12:00:00Z',
              },
            ],
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

    renderToolsListPage();

    expect(
      await screen.findByText('Complete node registration to manage marketplace tools'),
    ).toBeInTheDocument();
    expect(screen.getByText('beta.tool')).toBeInTheDocument();

    fireEvent.click(screen.getByRole('link', { name: 'Open setup' }));

    expect(await screen.findByText('Setup Review Route')).toBeInTheDocument();
  });
});
