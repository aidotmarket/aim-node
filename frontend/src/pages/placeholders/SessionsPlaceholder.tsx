import { Radio } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function SessionsPlaceholder() {
  return (
    <>
      <PageHeader title="Sessions" description="View active and past MCP sessions." />
      <EmptyState
        icon={<Radio size={40} />}
        title="Coming Soon"
        description="Session monitoring will be available here."
      />
    </>
  );
}
