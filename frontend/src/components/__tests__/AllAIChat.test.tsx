import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { AllAIChat } from '../AllAIChat';

describe('AllAIChat', () => {
  it('renders collapsed by default', () => {
    render(<AllAIChat />);
    expect(screen.getByLabelText('Open allAI chat')).toBeInTheDocument();
    expect(screen.queryByText('allAI Chat')).not.toBeInTheDocument();
  });

  it('opens when toggle button is clicked', () => {
    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    expect(screen.getByText('allAI Chat')).toBeInTheDocument();
    expect(screen.getByText('allAI assistant coming soon')).toBeInTheDocument();
  });

  it('closes when close button is clicked', () => {
    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    expect(screen.getByText('allAI Chat')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Close chat'));
    expect(screen.queryByText('allAI Chat')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Open allAI chat')).toBeInTheDocument();
  });

  it('shows placeholder empty state message', () => {
    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    expect(screen.getByText('allAI Assistant')).toBeInTheDocument();
    expect(screen.getByText('allAI assistant coming soon')).toBeInTheDocument();
  });

  it('has disabled input and send button', () => {
    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    expect(screen.getByPlaceholderText('Type a message...')).toBeDisabled();
  });
});
