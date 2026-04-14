import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AllAIChat } from '../AllAIChat';

const originalFetch = globalThis.fetch;
const mockFetch = vi.fn();

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('AllAIChat', () => {
  beforeEach(() => {
    globalThis.fetch = mockFetch;
  });

  afterEach(() => {
    globalThis.fetch = originalFetch;
    mockFetch.mockReset();
  });

  it('renders collapsed by default', () => {
    render(<AllAIChat />);
    expect(screen.getByLabelText('Open allAI chat')).toBeInTheDocument();
    expect(screen.queryByText('allAI Chat')).not.toBeInTheDocument();
  });

  it('opens when toggle button is clicked', () => {
    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    expect(screen.getByText('allAI Chat')).toBeInTheDocument();
    expect(screen.getByText('Ask allAI for help with setup, node state, or troubleshooting.')).toBeInTheDocument();
  });

  it('closes when close button is clicked', () => {
    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    expect(screen.getByText('allAI Chat')).toBeInTheDocument();

    fireEvent.click(screen.getByLabelText('Close chat'));
    expect(screen.queryByText('allAI Chat')).not.toBeInTheDocument();
    expect(screen.getByLabelText('Open allAI chat')).toBeInTheDocument();
  });

  it('sends a message to /allai/chat and displays the reply', async () => {
    mockFetch.mockResolvedValueOnce(
      jsonResponse({
        reply: 'Try testing your upstream endpoint next.',
      }),
    );

    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    fireEvent.change(screen.getByPlaceholderText('Type a message...'), {
      target: { value: 'What should I do next?' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(1));
    expect(mockFetch.mock.calls[0][0]).toBe('/allai/chat');
    expect(mockFetch.mock.calls[0][1]).toMatchObject({
      method: 'POST',
      body: JSON.stringify({ message: 'What should I do next?' }),
    });
    expect(await screen.findByText('What should I do next?')).toBeInTheDocument();
    expect(screen.getByText('Try testing your upstream endpoint next.')).toBeInTheDocument();
  });

  it('shows an inline error and retries the failed request', async () => {
    mockFetch
      .mockResolvedValueOnce(
        jsonResponse(
          {
            message: 'Service unavailable',
          },
          503,
        ),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          reply: 'Retry succeeded.',
        }),
      );

    render(<AllAIChat />);
    fireEvent.click(screen.getByLabelText('Open allAI chat'));
    fireEvent.change(screen.getByPlaceholderText('Type a message...'), {
      target: { value: 'Check setup status' },
    });
    fireEvent.click(screen.getByRole('button', { name: /send/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Service unavailable');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));

    await waitFor(() => expect(mockFetch).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Retry succeeded.')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });
});
