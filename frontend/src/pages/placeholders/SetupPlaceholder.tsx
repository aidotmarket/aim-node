import { Rocket } from 'lucide-react';
import { EmptyState } from '@/components/ui';

export function SetupPlaceholder() {
  return (
    <EmptyState
      icon={<Rocket size={40} />}
      title="Setup Wizard"
      description="Node setup wizard will guide you through configuration."
    />
  );
}
