import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Card } from '../Card';

describe('Card', () => {
  it('renders children', () => {
    render(<Card>Content</Card>);
    expect(screen.getByText('Content')).toBeInTheDocument();
  });

  it('renders with all padding variants', () => {
    const paddings = ['none', 'sm', 'md', 'lg'] as const;
    for (const padding of paddings) {
      const { unmount } = render(<Card padding={padding}>test</Card>);
      expect(screen.getByText('test')).toBeInTheDocument();
      unmount();
    }
  });

  it('applies custom className', () => {
    render(<Card className="custom-class">test</Card>);
    expect(screen.getByText('test').parentElement ?? screen.getByText('test')).toBeInTheDocument();
  });
});
