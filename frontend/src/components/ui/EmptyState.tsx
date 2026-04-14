import { Card } from './Card';

interface EmptyStateProps {
  icon: React.ReactNode;
  title: string;
  description: string;
  action?: React.ReactNode;
}

export function EmptyState({ icon, title, description, action }: EmptyStateProps) {
  return (
    <Card padding="lg">
      <div className="flex flex-col items-center text-center py-8">
        <div className="text-brand-text-secondary mb-4">{icon}</div>
        <h3 className="text-lg font-semibold text-brand-text mb-2">{title}</h3>
        <p className="text-sm text-brand-text-secondary max-w-md mb-4">{description}</p>
        {action && <div>{action}</div>}
      </div>
    </Card>
  );
}
