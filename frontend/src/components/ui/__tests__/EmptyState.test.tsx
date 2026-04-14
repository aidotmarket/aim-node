import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { EmptyState } from '../EmptyState';

describe('EmptyState', () => {
  it('renders icon, title, and description', () => {
    render(
      <EmptyState
        icon={<span data-testid="icon">icon</span>}
        title="No Data"
        description="Nothing here yet."
      />,
    );
    expect(screen.getByTestId('icon')).toBeInTheDocument();
    expect(screen.getByText('No Data')).toBeInTheDocument();
    expect(screen.getByText('Nothing here yet.')).toBeInTheDocument();
  });

  it('renders action when provided', () => {
    render(
      <EmptyState
        icon={<span>icon</span>}
        title="No Data"
        description="Nothing here yet."
        action={<button>Create</button>}
      />,
    );
    expect(screen.getByText('Create')).toBeInTheDocument();
  });
});
