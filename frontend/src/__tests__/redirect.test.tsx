import { render, screen, waitFor } from '@testing-library/react';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { describe, it, expect, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { RootRedirect } from '@/router';
import { useNodeStore } from '@/store/nodeStore';

beforeEach(() => {
  useNodeStore.setState(useNodeStore.getInitialState(), true);
});

function renderRedirect() {
  const routes = [
    { path: '/', element: <RootRedirect /> },
    { path: '/dashboard', element: <div>Dashboard Page</div> },
    { path: '/setup', element: <div>Setup Page</div> },
    { path: '/setup/unlock', element: <div>Unlock Page</div> },
  ];
  const router = createMemoryRouter(routes, { initialEntries: ['/'] });
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  );
}

describe('RootRedirect', () => {
  it('shows spinner while loading', () => {
    useNodeStore.setState({ loading: true });
    renderRedirect();
    expect(screen.getByRole('status')).toBeInTheDocument();
  });

  it('redirects to /setup when not setup complete', async () => {
    useNodeStore.setState({ loading: false, locked: false, setupComplete: false });
    renderRedirect();
    await waitFor(() => expect(screen.getByText('Setup Page')).toBeInTheDocument());
  });

  it('redirects to /setup/unlock when locked', async () => {
    useNodeStore.setState({ loading: false, locked: true, setupComplete: true });
    renderRedirect();
    await waitFor(() => expect(screen.getByText('Unlock Page')).toBeInTheDocument());
  });

  it('redirects to /dashboard when setup complete', async () => {
    useNodeStore.setState({ loading: false, locked: false, setupComplete: true });
    renderRedirect();
    await waitFor(() => expect(screen.getByText('Dashboard Page')).toBeInTheDocument());
  });
});
