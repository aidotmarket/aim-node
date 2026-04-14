import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { Field } from '../Field';

describe('Field', () => {
  it('renders label and children', () => {
    render(<Field label="Name"><input data-testid="child" /></Field>);
    expect(screen.getByText('Name')).toBeInTheDocument();
    expect(screen.getByTestId('child')).toBeInTheDocument();
  });

  it('shows required indicator', () => {
    render(<Field label="Name" required><input /></Field>);
    expect(screen.getByText('*')).toBeInTheDocument();
  });

  it('shows error', () => {
    render(<Field label="Name" error="Required"><input /></Field>);
    expect(screen.getByText('Required')).toBeInTheDocument();
  });
});
