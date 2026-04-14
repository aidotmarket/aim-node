import { Wrench } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function ToolsPlaceholder() {
  return (
    <>
      <PageHeader title="Tools" description="Manage your registered MCP tools." />
      <EmptyState
        icon={<Wrench size={40} />}
        title="Coming Soon"
        description="Tool management will be available here."
      />
    </>
  );
}
