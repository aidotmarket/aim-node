import { forwardRef } from 'react';

interface InputProps extends React.InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  hint?: string;
}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ label, error, hint, id, className = '', ...props }, ref) => {
    const inputId = id ?? label?.toLowerCase().replace(/\s+/g, '-');
    return (
      <div className="flex flex-col gap-1">
        {label && (
          <label htmlFor={inputId} className="text-sm font-medium text-brand-text">
            {label}
          </label>
        )}
        <input
          ref={ref}
          id={inputId}
          className={`rounded-brand border border-[#E8E8E8] px-3 py-2 text-sm text-brand-text placeholder:text-brand-text-secondary focus:border-brand-indigo focus:outline-none focus:ring-1 focus:ring-brand-indigo ${error ? 'border-brand-error' : ''} ${className}`}
          {...props}
        />
        {error && <p className="text-xs text-brand-error">{error}</p>}
        {hint && !error && <p className="text-xs text-brand-text-secondary">{hint}</p>}
      </div>
    );
  },
);

Input.displayName = 'Input';
