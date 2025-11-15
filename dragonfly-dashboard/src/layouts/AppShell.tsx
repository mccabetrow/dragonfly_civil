import React from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';

interface NavigationItem {
  label: string;
  path: string;
}

export const NAVIGATION_ITEMS: NavigationItem[] = [
  { label: 'Overview', path: '/overview' },
  { label: 'Collectability', path: '/collectability' },
  { label: 'Cases', path: '/cases' },
  { label: 'Settings', path: '/settings' },
  { label: 'Help', path: '/help' },
];

const AppShell: React.FC = () => {
  const location = useLocation();
  const activeNav =
    NAVIGATION_ITEMS.find((item) => location.pathname.startsWith(item.path)) ?? NAVIGATION_ITEMS[0];

  return (
    <div className="min-h-screen bg-slate-50 text-slate-900">
      <div className="flex min-h-screen">
        <aside className="hidden w-64 flex-shrink-0 flex-col gap-10 bg-slate-900 px-6 py-8 text-slate-100 md:flex">
          <div className="flex items-center gap-3">
            <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-blue-600 text-lg font-semibold text-white">
              DF
            </div>
            <div>
              <p className="text-sm font-semibold text-white">Dragonfly Civil</p>
              <p className="text-xs text-slate-400">Operations Console</p>
            </div>
          </div>
          <nav className="flex flex-1 flex-col gap-1 text-sm font-medium">
            {NAVIGATION_ITEMS.map((item) => (
              <NavLink
                key={item.path}
                to={item.path}
                className={() =>
                  'group flex items-center gap-3 rounded-xl px-4 py-2 text-slate-300 transition duration-150 hover:bg-slate-800/60 hover:text-white aria-[current=page]:bg-slate-800/80 aria-[current=page]:text-white aria-[current=page]:shadow-inner aria-[current=page]:ring-1 aria-[current=page]:ring-inset aria-[current=page]:ring-slate-600'
                }
              >
                <span
                  className="flex h-2 w-2 rounded-full bg-slate-500 transition group-hover:bg-blue-400 aria-[current=page]:bg-blue-400"
                  aria-hidden
                />
                <span className="font-semibold">{item.label}</span>
              </NavLink>
            ))}
          </nav>
          <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-4 text-xs text-slate-300">
            <p className="font-semibold text-white">Need help?</p>
            <p className="mt-1 leading-relaxed text-slate-400">
              Reach the ops team on Slack #dragonfly or email support@dragonflycivil.com. You can also review the guided
              console tour under Help.
            </p>
            <NavLink
              to="/help"
              className="mt-3 inline-flex items-center gap-1 rounded-lg border border-slate-600/60 px-3 py-1 text-[11px] font-semibold uppercase tracking-wide text-slate-200 transition hover:bg-slate-700/50 hover:text-white"
            >
              Open help
              <span aria-hidden="true">→</span>
            </NavLink>
          </div>
        </aside>
        <div className="flex flex-1 flex-col">
          <header className="flex items-center justify-between border-b border-slate-200 bg-white/90 px-4 py-4 shadow-sm backdrop-blur sm:px-6">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">Dashboard</p>
              <h1 className="text-2xl font-semibold text-slate-900">{activeNav.label}</h1>
            </div>
            <div className="flex items-center gap-3">
              <NavLink
                to="/help"
                className="hidden rounded-full border border-slate-200 px-3 py-1.5 text-sm font-semibold text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500 sm:inline-flex"
              >
                Help
              </NavLink>
              <span className="hidden text-sm font-medium text-slate-500 sm:inline">Dragonfly Civil</span>
              <span className="flex h-10 w-10 items-center justify-center rounded-full bg-blue-600 text-sm font-semibold text-white shadow">
                DC
              </span>
            </div>
          </header>
          <main className="flex-1 overflow-y-auto">
            <div className="mx-auto w-full max-w-6xl px-4 py-8 sm:px-6 lg:px-8">
              <Outlet />
            </div>
          </main>
        </div>
      </div>
    </div>
  );
};

export default AppShell;
