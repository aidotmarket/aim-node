import { Settings } from 'lucide-react';
import { PageHeader, EmptyState } from '@/components/ui';

export function SettingsPlaceholder() {
  return (
    <>
      <PageHeader title="Settings" description="Node configuration and preferences." />
      <EmptyState
        icon={<Settings size={40} />}
        title="Coming Soon"
        description="Settings will be available here."
      />
    </>
  );
}
