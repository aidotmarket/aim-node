import { CheckCircle, AlertTriangle, HelpCircle, Lock, XCircle } from 'lucide-react';
import { Badge } from './Badge';

interface StatusBadgeProps {
  status: 'healthy' | 'degraded' | 'unknown' | 'locked' | 'error';
}

const statusConfig: Record<
  StatusBadgeProps['status'],
  { variant: 'success' | 'warning' | 'error' | 'info' | 'neutral'; icon: React.ReactNode; label: string }
> = {
  healthy: { variant: 'success', icon: <CheckCircle size={12} />, label: 'Healthy' },
  degraded: { variant: 'warning', icon: <AlertTriangle size={12} />, label: 'Degraded' },
  unknown: { variant: 'neutral', icon: <HelpCircle size={12} />, label: 'Unknown' },
  locked: { variant: 'info', icon: <Lock size={12} />, label: 'Locked' },
  error: { variant: 'error', icon: <XCircle size={12} />, label: 'Error' },
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status];
  return (
    <Badge variant={config.variant}>
      <span className="inline-flex items-center gap-1">
        {config.icon}
        {config.label}
      </span>
    </Badge>
  );
}
