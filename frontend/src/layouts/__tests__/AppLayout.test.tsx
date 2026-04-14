import { render, screen } from '@testing-library/react';
import { MemoryRouter, Routes, Route } from 'react-router-dom';
import { beforeEach, describe, expect, it } from 'vitest';
import { AppLayout } from '@/layouts/AppLayout';
import { useNodeStore } from '@/store/nodeStore';

describe('AppLayout', () => {
  beforeEach(() => {
    useNodeStore.setState(useNodeStore.getInitialState(), true);
  });

  function renderLayout() {
    return render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <Routes>
          <Route path="/" element={<AppLayout />}>
            <Route path="dashboard" element={<div>Dashboard Page</div>} />
          </Route>
        </Routes>
      </MemoryRouter>,
    );
  }

  it('renders the allAI chat widget', () => {
    renderLayout();
    expect(screen.getByLabelText('Open allAI chat')).toBeInTheDocument();
  });

  it('reflects the store health status in the badge', () => {
    useNodeStore.setState({ healthStatus: 'healthy' });
    renderLayout();
    expect(screen.getByText('Healthy')).toBeInTheDocument();
  });
});
