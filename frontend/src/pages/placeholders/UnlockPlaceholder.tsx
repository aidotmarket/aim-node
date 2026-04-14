import { Lock } from 'lucide-react';
import { EmptyState } from '@/components/ui';

export function UnlockPlaceholder() {
  return (
    <EmptyState
      icon={<Lock size={40} />}
      title="Unlock Node"
      description="Enter your passphrase to unlock the node."
    />
  );
}
