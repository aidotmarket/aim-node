import { FormEvent, useState } from 'react';
import { MessageCircle, X, Send } from 'lucide-react';
import { Button, Card, Input } from '@/components/ui';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  text: string;
}

interface ChatResponse {
  reply: string;
}

export function AllAIChat() {
  const [open, setOpen] = useState(false);
  const [input, setInput] = useState('');
  const [messages, setMessages] = useState<Message[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [retryMessage, setRetryMessage] = useState<string | null>(null);
  const [isSending, setIsSending] = useState(false);

  const sendMessage = async (message: string, appendUser = true) => {
    const trimmed = message.trim();
    if (!trimmed) return;

    setError(null);
    setRetryMessage(trimmed);
    setIsSending(true);

    if (appendUser) {
      setMessages((current) => [
        ...current,
        { id: `user-${Date.now()}`, role: 'user', text: trimmed },
      ]);
    }

    try {
      const response = await fetch('/allai/chat', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: trimmed }),
      });

      const body = await response.json().catch(() => ({}));
      if (!response.ok) {
        const message = typeof body.message === 'string' ? body.message : 'Failed to send message';
        throw new Error(message);
      }

      const data = body as ChatResponse;
      setMessages((current) => [
        ...current,
        { id: `assistant-${Date.now()}`, role: 'assistant', text: data.reply },
      ]);
      setRetryMessage(null);
    } catch (caughtError) {
      setError(caughtError instanceof Error ? caughtError.message : 'Failed to send message');
    } finally {
      setIsSending(false);
    }
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();

    const message = input.trim();
    if (!message) return;

    setInput('');
    await sendMessage(message);
  };

  return (
    <div className="fixed bottom-6 right-6 z-50">
      {open ? (
        <div
          className="animate-in fade-in slide-in-from-bottom-4 duration-200"
          style={{ width: 360, height: 480 }}
        >
          <Card padding="none" className="flex flex-col h-full shadow-lg">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-[#E8E8E8]">
              <div className="flex items-center gap-2">
                <MessageCircle size={18} className="text-brand-indigo" />
                <span className="text-sm font-semibold text-brand-text">allAI Chat</span>
              </div>
              <button
                onClick={() => setOpen(false)}
                className="text-brand-text-secondary hover:text-brand-text transition-colors"
                aria-label="Close chat"
              >
                <X size={18} />
              </button>
            </div>

            {/* Message area */}
            <div className="flex-1 overflow-y-auto p-4">
              <div className="flex h-full flex-col gap-3">
                {messages.length === 0 ? (
                  <p className="text-sm text-brand-text-secondary">
                    Ask allAI for help with setup, node state, or troubleshooting.
                  </p>
                ) : (
                  messages.map((message) => (
                    <div
                      key={message.id}
                      className={`max-w-[85%] rounded-brand px-3 py-2 text-sm ${
                        message.role === 'user'
                          ? 'ml-auto bg-brand-indigo text-white'
                          : 'bg-brand-surface text-brand-text'
                      }`}
                    >
                      {message.text}
                    </div>
                  ))
                )}
              </div>
            </div>

            {/* Input area */}
            <div className="border-t border-[#E8E8E8] p-3">
              {error && (
                <div className="mb-3 flex items-center justify-between gap-3 rounded-brand border border-[#EF4444] bg-red-50 px-3 py-2 text-sm text-brand-error">
                  <span role="alert">{error}</span>
                  {retryMessage && (
                    <button
                      type="button"
                      className="font-medium text-brand-error"
                      onClick={() => sendMessage(retryMessage, false)}
                      disabled={isSending}
                    >
                      Retry
                    </button>
                  )}
                </div>
              )}
              <form className="flex items-center gap-2" onSubmit={handleSubmit}>
                <Input
                  placeholder="Type a message..."
                  className="flex-1"
                  value={input}
                  onChange={(event) => {
                    setInput(event.target.value);
                    setError(null);
                  }}
                  disabled={isSending}
                />
                <Button
                  variant="primary"
                  size="sm"
                  type="submit"
                  disabled={!input.trim()}
                  loading={isSending}
                  className="shrink-0"
                >
                  <span className="sr-only">Send message</span>
                  <Send size={16} />
                </Button>
              </form>
            </div>
          </Card>
        </div>
      ) : (
        <button
          onClick={() => setOpen(true)}
          className="bg-brand-indigo text-white rounded-full p-3 shadow-lg hover:bg-brand-indigo/90 transition-colors"
          aria-label="Open allAI chat"
        >
          <MessageCircle size={24} />
        </button>
      )}
    </div>
  );
}
