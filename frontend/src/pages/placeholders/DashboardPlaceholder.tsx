import { LayoutDashboard } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function DashboardPlaceholder() {
  return (
    <>
      <PageHeader title="Dashboard" description="Provider health, sessions, and metrics at a glance." />
      <EmptyState
        icon={<LayoutDashboard size={40} />}
        title="Coming Soon"
        description="Dashboard will show real-time provider metrics."
      />
    </>
  );
}
