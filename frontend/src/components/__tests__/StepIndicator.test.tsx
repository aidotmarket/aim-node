import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StepIndicator } from '../StepIndicator';

const steps = [
  { label: 'Welcome', status: 'complete' as const },
  { label: 'Keypair', status: 'active' as const },
  { label: 'Connection', status: 'pending' as const },
  { label: 'Upstream', status: 'pending' as const },
  { label: 'Review', status: 'pending' as const },
];

describe('StepIndicator', () => {
  it('renders all five setup steps', () => {
    render(<StepIndicator steps={steps} currentStep={1} />);

    for (const label of ['Welcome', 'Keypair', 'Connection', 'Upstream', 'Review']) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });

  it('shows complete styling and check icon for completed steps', () => {
    render(<StepIndicator steps={steps} currentStep={1} />);

    expect(screen.getByLabelText('Welcome complete')).toBeInTheDocument();
    expect(screen.getByTestId('step-circle-0')).toHaveClass('bg-brand-success', 'border-brand-success');
    expect(screen.getByTestId('step-label-0')).toHaveClass('text-brand-success');
    expect(screen.getByText('Done')).toBeInTheDocument();
  });

  it('shows active styling for the current step', () => {
    render(<StepIndicator steps={steps} currentStep={1} />);

    expect(screen.getByTestId('step-circle-1')).toHaveClass('bg-brand-indigo', 'text-white');
    expect(screen.getByTestId('step-label-1')).toHaveClass('text-brand-indigo');
    expect(screen.getByText('Current')).toBeInTheDocument();
  });

  it('shows pending styling and connector states for upcoming steps', () => {
    render(<StepIndicator steps={steps} currentStep={1} />);

    expect(screen.getByTestId('step-circle-2')).toHaveClass('bg-white', 'border-[#E8E8E8]');
    expect(screen.getByTestId('step-label-2')).toHaveClass('text-brand-text-secondary');
    expect(screen.getByTestId('connector-0')).toHaveClass('bg-brand-indigo');
    expect(screen.getByTestId('connector-1')).toHaveClass('bg-[#E8E8E8]');
  });
});
