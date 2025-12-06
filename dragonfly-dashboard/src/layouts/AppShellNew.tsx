import { type FC, useState, useEffect } from 'react';
import { NavLink, Outlet, useLocation } from 'react-router-dom';
import {
  LayoutDashboard,
  Target,
  Briefcase,
  Settings,
  HelpCircle,
  Menu,
  X,
  RefreshCw,
  Sparkles,
  Bell,
  ChevronRight,
  Headphones,
  TrendingUp,
  Terminal,
  PieChart,
} from 'lucide-react';
import ReleaseNotesModal, { useReleaseNotesModal } from '../components/ReleaseNotesModal';
import SystemDiagnostic from '../components/SystemDiagnostic';
import { cn } from '../lib/design-tokens';
import { Button, IconButton } from '../components/ui/Button';
import { useRefreshBus } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// NAVIGATION CONFIG
// ═══════════════════════════════════════════════════════════════════════════

interface NavigationItem {
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
  description: string;
}

const MAIN_NAVIGATION: NavigationItem[] = [
  {
    label: 'CEO Overview',
    path: '/ceo/overview',
    icon: TrendingUp,
    description: 'Executive portfolio summary',
  },
  {
    label: 'Portfolio',
    path: '/finance/portfolio',
    icon: PieChart,
    description: 'AUM & financial metrics',
  },
  {
    label: 'Overview',
    path: '/overview',
    icon: LayoutDashboard,
    description: 'Daily snapshot and key metrics',
  },
  {
    label: 'Ops Console',
    path: '/ops',
    icon: Headphones,
    description: 'Call queue and daily tasks',
  },
  {
    label: 'Command Center',
    path: '/ops/console',
    icon: Terminal,
    description: 'Intake & system health mission control',
  },
  {
    label: 'Radar',
    path: '/radar',
    icon: Target,
    description: 'Enforcement radar & buy candidates',
  },
  {
    label: 'Collectability',
    path: '/collectability',
    icon: Sparkles,
    description: 'Tier-based case prioritization',
  },
  {
    label: 'Cases',
    path: '/cases',
    icon: Briefcase,
    description: 'Browse and manage all judgments',
  },
];

const SECONDARY_NAVIGATION: NavigationItem[] = [
  {
    label: 'Settings',
    path: '/settings',
    icon: Settings,
    description: 'Team preferences and integrations',
  },
  {
    label: 'Help',
    path: '/help',
    icon: HelpCircle,
    description: 'Guides, tips, and support',
  },
];

// ═══════════════════════════════════════════════════════════════════════════
// APP SHELL
// ═══════════════════════════════════════════════════════════════════════════

const AppShellNew: FC = () => {
  const location = useLocation();
  const releaseNotes = useReleaseNotesModal();
  const { triggerRefresh, isRefreshing } = useRefreshBus();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // Close mobile menu on route change
  useEffect(() => {
    setMobileMenuOpen(false);
  }, [location.pathname]);

  // Prevent body scroll when mobile menu is open
  useEffect(() => {
    if (mobileMenuOpen) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => {
      document.body.style.overflow = '';
    };
  }, [mobileMenuOpen]);

  // Find current page info
  const allNavItems = [...MAIN_NAVIGATION, ...SECONDARY_NAVIGATION];
  const currentPage = allNavItems.find((item) =>
    location.pathname.startsWith(item.path)
  ) ?? MAIN_NAVIGATION[0];

  // Build breadcrumbs
  const breadcrumbs = [
    { label: 'Dashboard', path: '/' },
    { label: currentPage.label, path: currentPage.path },
  ];

  const handleRefresh = () => {
    setLastRefresh(new Date());
    triggerRefresh();
  };

  return (
    <div className="min-h-screen bg-slate-50">
      <ReleaseNotesModal isOpen={releaseNotes.isOpen} onClose={releaseNotes.close} />

      {/* Mobile menu overlay */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-40 bg-slate-900/50 backdrop-blur-sm md:hidden"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* SIDEBAR (Desktop) */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-72 transform bg-slate-900 transition-transform duration-300 ease-out',
          'md:translate-x-0',
          mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-full flex-col">
          {/* Logo & brand */}
          <div className="flex items-center justify-between px-5 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-indigo-500 to-indigo-600 text-base font-bold text-white shadow-lg shadow-indigo-500/30">
                DF
              </div>
              <div>
                <p className="text-sm font-semibold text-white">Dragonfly Civil</p>
                <p className="text-[11px] text-slate-400">Operations Console</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(false)}
              className="rounded-lg p-1.5 text-slate-400 hover:bg-slate-800 hover:text-white md:hidden"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Main navigation */}
          <nav className="flex-1 space-y-1 px-3 py-4">
            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              Main
            </p>
            {MAIN_NAVIGATION.map((item) => (
              <NavItem key={item.path} item={item} />
            ))}

            <div className="my-4 border-t border-slate-800" />

            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
              System
            </p>
            {SECONDARY_NAVIGATION.map((item) => (
              <NavItem key={item.path} item={item} />
            ))}
          </nav>

          {/* System diagnostic badge */}
          <div className="mx-3 mb-3">
            <SystemDiagnostic />
          </div>

          {/* Help card */}
          <div className="mx-3 mb-4 rounded-xl border border-slate-700/60 bg-gradient-to-br from-slate-800/80 to-slate-800/40 p-4">
            <p className="text-sm font-semibold text-white">Need help?</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-400">
              Check the Help page or email support@dragonflycivil.com
            </p>
            <NavLink
              to="/help"
              className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-indigo-400 transition hover:text-indigo-300"
            >
              Open help guide
              <ChevronRight className="h-3.5 w-3.5" />
            </NavLink>
          </div>

          {/* Version */}
          <div className="border-t border-slate-800 px-6 py-3">
            <button
              type="button"
              onClick={releaseNotes.open}
              className="flex items-center gap-2 text-xs text-emerald-400 transition hover:text-emerald-300"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>v1.2.0 — Securitization</span>
            </button>
          </div>
        </div>
      </aside>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MAIN CONTENT AREA */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <div className="md:pl-72">
        {/* Header */}
        <header className="sticky top-0 z-30 border-b border-slate-200/80 bg-white/98 shadow-[0_1px_2px_0_rgb(0_0_0/0.03)] backdrop-blur-sm">
          <div className="flex items-center justify-between px-4 py-2.5 sm:px-6">
            {/* Left: Mobile menu + Breadcrumbs */}
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setMobileMenuOpen(true)}
                className="rounded-lg p-2 text-slate-500 hover:bg-slate-100 hover:text-slate-700 md:hidden"
                aria-label="Open menu"
              >
                <Menu className="h-5 w-5" />
              </button>

              {/* Breadcrumbs */}
              <nav className="hidden items-center gap-1.5 text-sm md:flex" aria-label="Breadcrumb">
                {breadcrumbs.map((crumb, index) => (
                  <span key={crumb.path} className="flex items-center gap-1.5">
                    {index > 0 && (
                      <ChevronRight className="h-4 w-4 text-slate-300" aria-hidden="true" />
                    )}
                    {index === breadcrumbs.length - 1 ? (
                      <span className="font-medium text-slate-900">{crumb.label}</span>
                    ) : (
                      <NavLink
                        to={crumb.path}
                        className="text-slate-500 transition hover:text-slate-700"
                      >
                        {crumb.label}
                      </NavLink>
                    )}
                  </span>
                ))}
              </nav>

              {/* Mobile: Page title */}
              <h1 className="text-lg font-semibold text-slate-900 md:hidden">
                {currentPage.label}
              </h1>
            </div>

            {/* Right: Actions */}
            <div className="flex items-center gap-2">
              {/* Last refresh indicator */}
              {lastRefresh && (
                <span className="hidden text-xs text-slate-400 lg:inline">
                  Updated {lastRefresh.toLocaleTimeString()}
                </span>
              )}

              {/* Refresh button */}
              <IconButton
                variant="ghost"
                size="sm"
                onClick={handleRefresh}
                disabled={isRefreshing}
                aria-label="Refresh data"
              >
                <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
              </IconButton>

              {/* Notifications (placeholder) */}
              <IconButton
                variant="ghost"
                size="sm"
                aria-label="Notifications"
              >
                <Bell className="h-4 w-4" />
              </IconButton>

              {/* What's new */}
              <Button
                variant="ghost"
                size="sm"
                onClick={releaseNotes.open}
                className="hidden sm:inline-flex"
                leftIcon={<Sparkles className="h-4 w-4" />}
              >
                What's new
              </Button>

              {/* User avatar */}
              <div className="ml-2 flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-indigo-500 to-indigo-600 text-xs font-semibold text-white shadow-sm">
                DC
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="min-h-[calc(100vh-4rem)]">
          <div className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">
            <Outlet />
          </div>
        </main>

        {/* Footer */}
        <footer className="border-t border-slate-200 bg-white px-4 py-4 sm:px-6">
          <div className="mx-auto flex max-w-6xl items-center justify-between">
            <p className="text-xs text-slate-400">
              © {new Date().getFullYear()} Dragonfly Civil. All rights reserved.
            </p>
            <div className="flex items-center gap-4">
              <NavLink
                to="/help"
                className="text-xs text-slate-400 transition hover:text-slate-600"
              >
                Help
              </NavLink>
              <a
                href="mailto:support@dragonflycivil.com"
                className="text-xs text-slate-400 transition hover:text-slate-600"
              >
                Support
              </a>
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// NAV ITEM COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface NavItemProps {
  item: NavigationItem;
}

const NavItem: FC<NavItemProps> = ({ item }) => {
  const Icon = item.icon;

  return (
    <NavLink
      to={item.path}
      className={({ isActive }) =>
        cn(
          'group flex items-center gap-3 rounded-xl px-3 py-2 text-sm font-medium transition-all duration-150',
          isActive
            ? 'bg-slate-800 text-white shadow-sm'
            : 'text-slate-400 hover:bg-slate-800/60 hover:text-white'
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={cn(
              'flex h-7 w-7 items-center justify-center rounded-lg transition-colors',
              isActive
                ? 'bg-indigo-500/20 text-indigo-400'
                : 'bg-slate-800 text-slate-500 group-hover:bg-slate-700 group-hover:text-slate-300'
            )}
          >
            <Icon className="h-4 w-4" />
          </span>
          <div className="flex-1">
            <span className="block">{item.label}</span>
            <span
              className={cn(
                'block text-[11px] font-normal leading-tight',
                isActive ? 'text-slate-400' : 'text-slate-500'
              )}
            >
              {item.description}
            </span>
          </div>
          {isActive && (
            <span className="h-1.5 w-1.5 rounded-full bg-indigo-400" aria-hidden="true" />
          )}
        </>
      )}
    </NavLink>
  );
};

export default AppShellNew;
