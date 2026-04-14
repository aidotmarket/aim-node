import { DollarSign } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function EarningsPlaceholder() {
  return (
    <>
      <PageHeader title="Earnings" description="Track your earnings from tool sessions." />
      <EmptyState
        icon={<DollarSign size={40} />}
        title="Coming Soon"
        description="Earnings tracking will be available here."
      />
    </>
  );
}
