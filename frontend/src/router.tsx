import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppLayout } from '@/layouts/AppLayout';
import { SetupLayout } from '@/layouts/SetupLayout';
import { useNodeState } from '@/hooks/useNodeState';
import { Spinner } from '@/components/ui';
import { DashboardPlaceholder } from '@/pages/placeholders/DashboardPlaceholder';
import { ToolsPlaceholder } from '@/pages/placeholders/ToolsPlaceholder';
import { ToolDetailPlaceholder } from '@/pages/placeholders/ToolDetailPlaceholder';
import { EarningsPlaceholder } from '@/pages/placeholders/EarningsPlaceholder';
import { SessionsPlaceholder } from '@/pages/placeholders/SessionsPlaceholder';
import { SessionDetailPlaceholder } from '@/pages/placeholders/SessionDetailPlaceholder';
import { LogsPlaceholder } from '@/pages/placeholders/LogsPlaceholder';
import { SettingsPlaceholder } from '@/pages/placeholders/SettingsPlaceholder';
import { SetupPlaceholder } from '@/pages/placeholders/SetupPlaceholder';
import { UnlockPlaceholder } from '@/pages/placeholders/UnlockPlaceholder';
import { NotFound } from '@/pages/NotFound';

export function RootRedirect() {
  const { loading, locked, setupComplete } = useNodeState();

  if (loading) {
    return (
      <div className="min-h-screen bg-brand-surface flex items-center justify-center">
        <Spinner size="lg" />
      </div>
    );
  }

  if (locked) return <Navigate to="/setup/unlock" replace />;
  if (!setupComplete) return <Navigate to="/setup" replace />;
  return <Navigate to="/dashboard" replace />;
}

export const router = createBrowserRouter([
  { path: '/', element: <RootRedirect /> },
  {
    path: '/setup',
    element: <SetupLayout />,
    children: [
      { index: true, element: <SetupPlaceholder /> },
      { path: 'unlock', element: <UnlockPlaceholder /> },
    ],
  },
  {
    path: '/',
    element: <AppLayout />,
    children: [
      { path: 'dashboard', element: <DashboardPlaceholder /> },
      { path: 'tools', element: <ToolsPlaceholder /> },
      { path: 'tools/:id', element: <ToolDetailPlaceholder /> },
      { path: 'earnings', element: <EarningsPlaceholder /> },
      { path: 'sessions', element: <SessionsPlaceholder /> },
      { path: 'sessions/:id', element: <SessionDetailPlaceholder /> },
      { path: 'logs', element: <LogsPlaceholder /> },
      { path: 'settings', element: <SettingsPlaceholder /> },
    ],
  },
  { path: '*', element: <NotFound /> },
]);
