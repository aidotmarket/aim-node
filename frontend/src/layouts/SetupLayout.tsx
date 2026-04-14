import { Outlet } from 'react-router-dom';
import { AllAIChat } from '@/components/AllAIChat';
import { StepIndicator } from '@/components/StepIndicator';
import { Card } from '@/components/ui';
import { SetupWizardProvider, useSetupWizard } from '@/hooks/useSetupWizard';

const SETUP_STEP_LABELS = ['Welcome', 'Keypair', 'Connection', 'Upstream', 'Review'];

export function SetupLayout() {
  return (
    <SetupWizardProvider>
      <SetupLayoutContent />
    </SetupWizardProvider>
  );
}

function SetupLayoutContent() {
  const { currentStep, stepStatus } = useSetupWizard();
  const steps = SETUP_STEP_LABELS.map((label, index) => ({
    label,
    status:
      stepStatus[index] === 'complete' ? ('complete' as const) :
      stepStatus[index] === 'active' ? ('active' as const) :
      ('pending' as const),
  }));

  return (
    <div className="min-h-screen bg-brand-surface p-6">
      <div className="mx-auto w-full max-w-2xl py-12">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-semibold text-brand-indigo">AIM Node</h1>
          <p className="text-sm text-brand-text-secondary mt-1">Setup & Configuration</p>
        </div>
        <StepIndicator steps={steps} currentStep={currentStep} />
        <Card padding="lg">
          <Outlet />
        </Card>
      </div>
      <AllAIChat />
    </div>
  );
}
