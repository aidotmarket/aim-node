import { Radio } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function SessionDetailPlaceholder() {
  return (
    <>
      <PageHeader title="Session Details" description="Inspect a specific session." />
      <EmptyState
        icon={<Radio size={40} />}
        title="Coming Soon"
        description="Session details will be available here."
      />
    </>
  );
}
