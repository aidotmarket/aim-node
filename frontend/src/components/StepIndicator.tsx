import { Check } from 'lucide-react';
import { Badge } from '@/components/ui';

type StepIndicatorStatus = 'pending' | 'active' | 'complete';

interface StepIndicatorProps {
  steps: Array<{ label: string; status: StepIndicatorStatus }>;
  currentStep: number;
}

const circleStyles: Record<StepIndicatorStatus, string> = {
  pending: 'border border-[#E8E8E8] bg-white text-brand-text-secondary',
  active: 'border border-brand-indigo bg-brand-indigo text-white',
  complete: 'border border-brand-success bg-brand-success text-white',
};

const labelStyles: Record<StepIndicatorStatus, string> = {
  pending: 'text-brand-text-secondary',
  active: 'text-brand-indigo',
  complete: 'text-brand-success',
};

const connectorStyles: Record<'pending' | 'complete', string> = {
  pending: 'bg-[#E8E8E8]',
  complete: 'bg-brand-indigo',
};

export function StepIndicator({ steps, currentStep }: StepIndicatorProps) {
  return (
    <div className="mb-8" aria-label="Setup progress">
      <ol className="grid grid-cols-5 gap-3" role="list">
        {steps.map((step, index) => {
          const connectorStatus = index < currentStep ? 'complete' : 'pending';
          const badge =
            step.status === 'active' ? <Badge variant="info">Current</Badge> :
            step.status === 'complete' ? <Badge variant="success">Done</Badge> :
            null;

          return (
            <li key={step.label} className="relative flex flex-col items-center text-center">
              {index < steps.length - 1 ? (
                <span
                  data-testid={`connector-${index}`}
                  aria-hidden="true"
                  className={`absolute left-1/2 top-5 h-0.5 w-full ${connectorStyles[connectorStatus]}`}
                />
              ) : null}
              <span
                data-testid={`step-circle-${index}`}
                aria-current={index === currentStep ? 'step' : undefined}
                className={`relative z-10 flex h-10 w-10 items-center justify-center rounded-full text-sm font-semibold ${circleStyles[step.status]}`}
              >
                {step.status === 'complete' ? <Check size={18} aria-label={`${step.label} complete`} /> : index + 1}
              </span>
              <span
                data-testid={`step-label-${index}`}
                className={`mt-3 text-sm font-medium ${labelStyles[step.status]}`}
              >
                {step.label}
              </span>
              <span className="mt-2 min-h-5">{badge}</span>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
