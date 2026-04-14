import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AppLayout } from '@/layouts/AppLayout';
import { SetupLayout } from '@/layouts/SetupLayout';
import { Spinner } from '@/components/ui';
import { useNodeStore } from '@/store/nodeStore';
import { DashboardPlaceholder } from '@/pages/placeholders/DashboardPlaceholder';
import { ToolsPlaceholder } from '@/pages/placeholders/ToolsPlaceholder';
import { ToolDetailPlaceholder } from '@/pages/placeholders/ToolDetailPlaceholder';
import { EarningsPlaceholder } from '@/pages/placeholders/EarningsPlaceholder';
import { SessionsPlaceholder } from '@/pages/placeholders/SessionsPlaceholder';
import { SessionDetailPlaceholder } from '@/pages/placeholders/SessionDetailPlaceholder';
import { LogsPlaceholder } from '@/pages/placeholders/LogsPlaceholder';
import { SettingsPlaceholder } from '@/pages/placeholders/SettingsPlaceholder';
import { UnlockPlaceholder } from '@/pages/placeholders/UnlockPlaceholder';
import { NotFound } from '@/pages/NotFound';
import { WelcomeStep } from '@/pages/setup/WelcomeStep';
import { KeypairStep } from '@/pages/setup/KeypairStep';
import { ConnectionStep } from '@/pages/setup/ConnectionStep';
import { UpstreamStep } from '@/pages/setup/UpstreamStep';
import { ReviewStep } from '@/pages/setup/ReviewStep';

export function RootRedirect() {
  const loading = useNodeStore((state) => state.loading);
  const locked = useNodeStore((state) => state.locked);
  const setupComplete = useNodeStore((state) => state.setupComplete);

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
      { index: true, element: <Navigate to="/setup/welcome" replace /> },
      { path: 'welcome', element: <WelcomeStep /> },
      { path: 'keypair', element: <KeypairStep /> },
      { path: 'connection', element: <ConnectionStep /> },
      { path: 'upstream', element: <UpstreamStep /> },
      { path: 'review', element: <ReviewStep /> },
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
