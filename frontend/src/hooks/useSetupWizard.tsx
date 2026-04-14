import { createContext, useContext, useEffect, useMemo, useRef, useState } from 'react';
import { useSetupStatus } from '@/hooks/useSetupStatus';

export type SetupWizardStepStatus = 'pending' | 'active' | 'complete' | 'error';

export interface UseSetupWizard {
  currentStep: number;
  stepStatus: Record<number, SetupWizardStepStatus>;
  isLoading: boolean;
  error: string | null;
  next: () => void;
  back: () => void;
  goToStep: (n: number) => void;
  markComplete: (step: number) => void;
  passphrase: string;
  setPassphrase: (value: string) => void;
  clearPassphrase: () => void;
}

const TOTAL_STEPS = 5;
const SetupWizardContext = createContext<UseSetupWizard | null>(null);

function clampStep(step: number) {
  return Math.max(0, Math.min(step, TOTAL_STEPS - 1));
}

function buildInitialStepStatus(currentStep: number, setupComplete: boolean) {
  const status: Record<number, SetupWizardStepStatus> = {};

  for (let step = 0; step < TOTAL_STEPS; step += 1) {
    if (setupComplete || step < currentStep) {
      status[step] = 'complete';
    } else if (step === currentStep) {
      status[step] = 'active';
    } else {
      status[step] = 'pending';
    }
  }

  return status;
}

function useSetupWizardState(initialPassphrase = ''): UseSetupWizard {
  const { data, isLoading, error } = useSetupStatus();
  const [currentStep, setCurrentStep] = useState(0);
  const [stepStatus, setStepStatus] = useState<Record<number, SetupWizardStepStatus>>(
    buildInitialStepStatus(0, false),
  );
  const [passphrase, setPassphrase] = useState(initialPassphrase);
  const currentStepRef = useRef(currentStep);
  const stepStatusRef = useRef(stepStatus);

  useEffect(() => {
    currentStepRef.current = currentStep;
  }, [currentStep]);

  useEffect(() => {
    stepStatusRef.current = stepStatus;
  }, [stepStatus]);

  useEffect(() => {
    if (!data) return;

    const nextCurrentStep = clampStep(data.current_step);
    setCurrentStep(nextCurrentStep);
    setStepStatus(buildInitialStepStatus(nextCurrentStep, data.current_step >= TOTAL_STEPS));
  }, [data]);

  const message = useMemo(() => {
    if (!error) return null;
    return error instanceof Error ? error.message : 'Failed to load setup status';
  }, [error]);

  const next = () => {
    const step = currentStepRef.current;
    const status = stepStatusRef.current;
    if (step >= TOTAL_STEPS - 1 || status[step] !== 'complete') return;

    const targetStep = step + 1;
    setCurrentStep(targetStep);
    setStepStatus((prev) => ({
      ...prev,
      [targetStep]: prev[targetStep] === 'complete' ? 'complete' : 'active',
    }));
  };

  const back = () => {
    const step = currentStepRef.current;
    if (step <= 0) return;

    const targetStep = step - 1;
    setCurrentStep(targetStep);
    setStepStatus((prev) => ({
      ...prev,
      [targetStep]: 'active',
      [step]: prev[step] === 'error' ? 'error' : 'complete',
    }));
  };

  const goToStep = (n: number) => {
    const targetStep = clampStep(n);
    const step = currentStepRef.current;
    const status = stepStatusRef.current;

    if (targetStep === step) return;
    if (status[targetStep] !== 'complete') return;

    setCurrentStep(targetStep);
    setStepStatus((prev) => ({
      ...prev,
      [targetStep]: 'active',
      [step]: prev[step] === 'error' ? 'error' : prev[step] === 'complete' ? 'complete' : 'pending',
    }));
  };

  const markComplete = (step: number) => {
    const targetStep = clampStep(step);
    setStepStatus((prev) => ({
      ...prev,
      [targetStep]: 'complete',
    }));
  };

  return {
    currentStep,
    stepStatus,
    isLoading,
    error: message,
    next,
    back,
    goToStep,
    markComplete,
    passphrase,
    setPassphrase,
    clearPassphrase: () => setPassphrase(''),
  };
}

export function SetupWizardProvider({
  children,
  initialPassphrase,
}: {
  children: React.ReactNode;
  initialPassphrase?: string;
}) {
  const value = useSetupWizardState(initialPassphrase);
  return <SetupWizardContext.Provider value={value}>{children}</SetupWizardContext.Provider>;
}

export function useSetupWizard(): UseSetupWizard {
  const context = useContext(SetupWizardContext);

  if (!context) {
    throw new Error('useSetupWizard must be used within a SetupWizardProvider');
  }

  return context;
}
