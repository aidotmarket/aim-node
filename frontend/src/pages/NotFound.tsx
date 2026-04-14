import { FileQuestion } from 'lucide-react';
import { useNavigate } from 'react-router-dom';
import { EmptyState, Button } from '@/components/ui';

export function NotFound() {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen bg-brand-surface flex items-center justify-center p-6">
      <EmptyState
        icon={<FileQuestion size={40} />}
        title="Page Not Found"
        description="The page you're looking for doesn't exist."
        action={
          <Button variant="primary" onClick={() => navigate('/')}>
            Go Home
          </Button>
        }
      />
    </div>
  );
}
