import { useState } from 'react';
import { MessageCircle, X, Send } from 'lucide-react';
import { Button, Card, Input, EmptyState } from '@/components/ui';

export function AllAIChat() {
  const [open, setOpen] = useState(false);

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
              <EmptyState
                icon={<MessageCircle size={32} />}
                title="allAI Assistant"
                description="allAI assistant coming soon"
              />
            </div>

            {/* Input area */}
            <div className="border-t border-[#E8E8E8] p-3">
              <form
                className="flex items-center gap-2"
                onSubmit={(e) => e.preventDefault()}
              >
                <Input
                  placeholder="Type a message..."
                  className="flex-1"
                  disabled
                />
                <Button variant="primary" size="sm" disabled>
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
