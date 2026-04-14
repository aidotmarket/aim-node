import { Badge } from '@/components/ui';
import { PublishStatus } from '@/types/marketplace';

interface ToolStatusBadgeProps {
  status: PublishStatus;
}

const statusConfig: Record<
  PublishStatus,
  {
    label: string;
    variant: 'success' | 'warning' | 'neutral';
  }
> = {
  live: {
    label: 'Published',
    variant: 'success',
  },
  draft: {
    label: 'Draft',
    variant: 'warning',
  },
  not_published: {
    label: 'Unpublished',
    variant: 'neutral',
  },
};

export function ToolStatusBadge({ status }: ToolStatusBadgeProps) {
  const config = statusConfig[status];

  return <Badge variant={config.variant}>{config.label}</Badge>;
}

