import { useState } from 'react';
import { NavLink, Outlet } from 'react-router-dom';
import {
  LayoutDashboard,
  Wrench,
  DollarSign,
  Radio,
  ScrollText,
  Settings,
  Menu,
  X,
} from 'lucide-react';
import { AllAIChat } from '@/components/AllAIChat';
import { StatusBadge } from '@/components/ui';
import { useNodeStore } from '@/store/nodeStore';

const navItems = [
  { to: '/dashboard', label: 'Dashboard', icon: LayoutDashboard },
  { to: '/tools', label: 'Tools', icon: Wrench },
  { to: '/earnings', label: 'Earnings', icon: DollarSign },
  { to: '/sessions', label: 'Sessions', icon: Radio },
  { to: '/logs', label: 'Logs', icon: ScrollText },
  { to: '/settings', label: 'Settings', icon: Settings },
];

export function AppLayout() {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const healthStatus = useNodeStore((state) => state.healthStatus);

  return (
    <div className="flex h-screen bg-brand-surface">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 bg-black/30 z-20 lg:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar */}
      <aside
        className={`fixed lg:static inset-y-0 left-0 z-30 w-64 bg-white border-r border-[#E8E8E8] flex flex-col transition-transform lg:translate-x-0 ${
          sidebarOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
      >
        <div className="flex items-center gap-3 px-5 h-16 border-b border-[#E8E8E8]">
          <span className="text-lg font-semibold text-brand-indigo">AIM Node</span>
          <StatusBadge status={healthStatus} />
        </div>
        <nav className="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
          {navItems.map(({ to, label, icon: Icon }) => (
            <NavLink
              key={to}
              to={to}
              onClick={() => setSidebarOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2 rounded-brand text-sm font-medium transition-colors ${
                  isActive
                    ? 'bg-brand-indigo/10 text-brand-indigo'
                    : 'text-brand-text-secondary hover:bg-brand-surface'
                }`
              }
            >
              <Icon size={18} />
              {label}
            </NavLink>
          ))}
        </nav>
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Top bar */}
        <header className="h-16 bg-white border-b border-[#E8E8E8] flex items-center px-5 gap-4">
          <button
            onClick={() => setSidebarOpen(true)}
            className="lg:hidden text-brand-text-secondary hover:text-brand-text"
            aria-label="Open sidebar"
          >
            <Menu size={20} />
          </button>
          <button
            onClick={() => setSidebarOpen(false)}
            className={`lg:hidden text-brand-text-secondary hover:text-brand-text ${sidebarOpen ? '' : 'hidden'}`}
            aria-label="Close sidebar"
          >
            <X size={20} />
          </button>
          <div className="flex-1" />
        </header>

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-6">
          <Outlet />
        </main>
      </div>
      <AllAIChat />
    </div>
  );
}
