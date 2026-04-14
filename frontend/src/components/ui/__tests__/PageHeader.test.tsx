import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { PageHeader } from '../PageHeader';

describe('PageHeader', () => {
  it('renders title', () => {
    render(<PageHeader title="Dashboard" />);
    expect(screen.getByText('Dashboard')).toBeInTheDocument();
  });

  it('renders description', () => {
    render(<PageHeader title="Dashboard" description="Overview" />);
    expect(screen.getByText('Overview')).toBeInTheDocument();
  });

  it('renders actions', () => {
    render(<PageHeader title="Dashboard" actions={<button>Add</button>} />);
    expect(screen.getByText('Add')).toBeInTheDocument();
  });
});
