import { ScrollText } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function LogsPlaceholder() {
  return (
    <>
      <PageHeader title="Logs" description="View system and request logs." />
      <EmptyState
        icon={<ScrollText size={40} />}
        title="Coming Soon"
        description="Log viewer will be available here."
      />
    </>
  );
}
