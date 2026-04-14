import { Wrench } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function ToolDetailPlaceholder() {
  return (
    <>
      <PageHeader title="Tool Details" description="Configure and monitor a specific tool." />
      <EmptyState
        icon={<Wrench size={40} />}
        title="Coming Soon"
        description="Tool details and configuration will be available here."
      />
    </>
  );
}
