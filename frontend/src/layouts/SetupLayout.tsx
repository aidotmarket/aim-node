import { Outlet } from 'react-router-dom';
import { Card } from '@/components/ui';

export function SetupLayout() {
  return (
    <div className="min-h-screen bg-brand-surface flex items-center justify-center p-6">
      <div className="w-full max-w-lg">
        <div className="text-center mb-8">
          <h1 className="text-2xl font-semibold text-brand-indigo">AIM Node</h1>
          <p className="text-sm text-brand-text-secondary mt-1">Setup & Configuration</p>
        </div>
        <Card padding="lg">
          <Outlet />
        </Card>
      </div>
    </div>
  );
}
