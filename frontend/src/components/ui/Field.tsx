interface FieldProps {
  label: string;
  children: React.ReactNode;
  error?: string;
  hint?: string;
  required?: boolean;
}

export function Field({ label, children, error, hint, required }: FieldProps) {
  return (
    <div className="flex flex-col gap-1">
      <label className="text-sm font-medium text-brand-text">
        {label}
        {required && <span className="text-brand-error ml-0.5">*</span>}
      </label>
      {children}
      {error && <p className="text-xs text-brand-error">{error}</p>}
      {hint && !error && <p className="text-xs text-brand-text-secondary">{hint}</p>}
    </div>
  );
}
