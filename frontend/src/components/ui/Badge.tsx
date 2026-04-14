interface BadgeProps {
  variant: 'success' | 'warning' | 'error' | 'info' | 'neutral';
  children: React.ReactNode;
}

const variantStyles: Record<BadgeProps['variant'], string> = {
  success: 'bg-[#E1F5EE] text-brand-teal',
  warning: 'bg-amber-50 text-amber-700',
  error: 'bg-red-50 text-brand-error',
  info: 'bg-indigo-50 text-brand-indigo',
  neutral: 'bg-gray-100 text-brand-text-secondary',
};

export function Badge({ variant, children }: BadgeProps) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${variantStyles[variant]}`}>
      {children}
    </span>
  );
}
