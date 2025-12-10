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
  Moon,
} from 'lucide-react';
import ReleaseNotesModal, { useReleaseNotesModal } from '../components/ReleaseNotesModal';
import SystemDiagnostic from '../components/SystemDiagnostic';
import { cn } from '../lib/design-tokens';
import { Button, IconButton } from '../components/ui/Button';
import { useRefreshBus } from '../context/RefreshContext';
import { useOpsAlerts } from '../hooks/useOpsAlerts';

// ═══════════════════════════════════════════════════════════════════════════
// NAVIGATION CONFIG
// ═══════════════════════════════════════════════════════════════════════════

interface NavigationItem {
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
  description: string;
  alertKey?: string; // Optional key for dynamic alert status
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
    alertKey: 'ops', // Shows red dot when system is Critical
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
  const { isCritical: opsAlertCritical } = useOpsAlerts(60000); // Poll every 60s
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

  // Enable dark mode by default (premium fintech theme)
  useEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

  return (
    <div className="min-h-screen bg-dragonfly-navy-900 bg-mesh-dark">
      <ReleaseNotesModal isOpen={releaseNotes.isOpen} onClose={releaseNotes.close} />

      {/* Mobile menu overlay */}
      {mobileMenuOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
          onClick={() => setMobileMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* SIDEBAR (Desktop) - Premium Dark Theme */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 w-72 transform transition-transform duration-300 ease-out',
          'bg-dragonfly-navy-950/95 backdrop-blur-xl border-r border-white/5',
          'md:translate-x-0',
          mobileMenuOpen ? 'translate-x-0' : '-translate-x-full'
        )}
      >
        <div className="flex h-full flex-col">
          {/* Logo & brand - Premium styling */}
          <div className="flex items-center justify-between px-5 py-5">
            <div className="flex items-center gap-3">
              <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-cyan-400 to-cyan-600 text-base font-bold text-dragonfly-navy-950 shadow-lg shadow-cyan-500/25">
                <span className="relative z-10">DF</span>
                <div className="absolute inset-0 rounded-xl bg-gradient-to-br from-cyan-400 to-cyan-600 opacity-50 blur-sm" />
              </div>
              <div>
                <p className="text-sm font-semibold text-white tracking-tight">Dragonfly Civil</p>
                <p className="text-[11px] text-slate-500 font-medium">Asset Recovery Platform</p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setMobileMenuOpen(false)}
              className="rounded-lg p-1.5 text-slate-500 hover:bg-white/5 hover:text-white md:hidden"
              aria-label="Close menu"
            >
              <X className="h-5 w-5" />
            </button>
          </div>

          {/* Main navigation */}
          <nav className="flex-1 space-y-1 px-3 py-4 overflow-y-auto">
            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600">
              Main
            </p>
            {MAIN_NAVIGATION.map((item) => (
              <NavItem
                key={item.path}
                item={item}
                showAlert={item.alertKey === 'ops' && opsAlertCritical}
              />
            ))}

            <div className="my-4 border-t border-white/5" />

            <p className="mb-2 px-3 text-[10px] font-semibold uppercase tracking-widest text-slate-600">
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

          {/* Help card - Premium glass styling */}
          <div className="mx-3 mb-4 rounded-xl border border-white/5 bg-gradient-to-br from-white/[0.03] to-transparent p-4 backdrop-blur-sm">
            <p className="text-sm font-semibold text-white">Need help?</p>
            <p className="mt-1 text-xs leading-relaxed text-slate-500">
              Check the Help page or email support@dragonflycivil.com
            </p>
            <NavLink
              to="/help"
              className="mt-3 inline-flex items-center gap-1.5 text-xs font-semibold text-cyan-400 transition hover:text-cyan-300"
            >
              Open help guide
              <ChevronRight className="h-3.5 w-3.5" />
            </NavLink>
          </div>

          {/* Version - Premium accent */}
          <div className="border-t border-white/5 px-6 py-3">
            <button
              type="button"
              onClick={releaseNotes.open}
              className="flex items-center gap-2 text-xs text-cyan-400 transition hover:text-cyan-300"
            >
              <Sparkles className="h-3.5 w-3.5" />
              <span>v1.2.0 — Securitization</span>
            </button>
          </div>
        </div>
      </aside>

      {/* ═══════════════════════════════════════════════════════════════════ */}
      {/* MAIN CONTENT AREA - Premium Dark Theme */}
      {/* ═══════════════════════════════════════════════════════════════════ */}
      <div className="md:pl-72">
        {/* Header - Frosted glass effect */}
        <header className="sticky top-0 z-30 border-b border-white/5 bg-dragonfly-navy-900/80 backdrop-blur-xl">
          <div className="flex items-center justify-between px-4 py-3 sm:px-6">
            {/* Left: Mobile menu + Breadcrumbs */}
            <div className="flex items-center gap-3">
              <button
                type="button"
                onClick={() => setMobileMenuOpen(true)}
                className="rounded-lg p-2 text-slate-400 hover:bg-white/5 hover:text-white md:hidden"
                aria-label="Open menu"
              >
                <Menu className="h-5 w-5" />
              </button>

              {/* Breadcrumbs */}
              <nav className="hidden items-center gap-1.5 text-sm md:flex" aria-label="Breadcrumb">
                {breadcrumbs.map((crumb, index) => (
                  <span key={crumb.path} className="flex items-center gap-1.5">
                    {index > 0 && (
                      <ChevronRight className="h-4 w-4 text-slate-600" aria-hidden="true" />
                    )}
                    {index === breadcrumbs.length - 1 ? (
                      <span className="font-medium text-white">{crumb.label}</span>
                    ) : (
                      <NavLink
                        to={crumb.path}
                        className="text-slate-400 transition hover:text-white"
                      >
                        {crumb.label}
                      </NavLink>
                    )}
                  </span>
                ))}
              </nav>

              {/* Mobile: Page title */}
              <h1 className="text-lg font-semibold text-white md:hidden">
                {currentPage.label}
              </h1>
            </div>

            {/* Right: Actions */}
            <div className="flex items-center gap-2">
              {/* Last refresh indicator */}
              {lastRefresh && (
                <span className="hidden text-xs text-slate-500 lg:inline">
                  Updated {lastRefresh.toLocaleTimeString()}
                </span>
              )}

              {/* Theme toggle */}
              <IconButton
                variant="ghost"
                size="sm"
                aria-label="Toggle theme"
                className="text-slate-400 hover:text-white hover:bg-white/5"
              >
                <Moon className="h-4 w-4" />
              </IconButton>

              {/* Refresh button */}
              <IconButton
                variant="ghost"
                size="sm"
                onClick={handleRefresh}
                disabled={isRefreshing}
                aria-label="Refresh data"
                className="text-slate-400 hover:text-white hover:bg-white/5"
              >
                <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
              </IconButton>

              {/* Notifications (placeholder) */}
              <IconButton
                variant="ghost"
                size="sm"
                aria-label="Notifications"
                className="text-slate-400 hover:text-white hover:bg-white/5"
              >
                <Bell className="h-4 w-4" />
              </IconButton>

              {/* What's new */}
              <Button
                variant="ghost"
                size="sm"
                onClick={releaseNotes.open}
                className="hidden text-slate-400 hover:text-white hover:bg-white/5 sm:inline-flex"
                leftIcon={<Sparkles className="h-4 w-4" />}
              >
                What's new
              </Button>

              {/* User avatar - Premium cyan accent */}
              <div className="ml-2 flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-cyan-400 to-cyan-600 text-xs font-bold text-dragonfly-navy-950 shadow-lg shadow-cyan-500/20">
                DC
              </div>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="min-h-[calc(100vh-4rem)]">
          <div className="mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
            <Outlet />
          </div>
        </main>

        {/* Footer - Premium dark styling */}
        <footer className="border-t border-white/5 bg-dragonfly-navy-950/50 px-4 py-4 sm:px-6">
          <div className="mx-auto flex max-w-7xl items-center justify-between">
            <p className="text-xs text-slate-600">
              © {new Date().getFullYear()} Dragonfly Civil. All rights reserved.
            </p>
            <div className="flex items-center gap-4">
              <NavLink
                to="/help"
                className="text-xs text-slate-500 transition hover:text-cyan-400"
              >
                Help
              </NavLink>
              <a
                href="mailto:support@dragonflycivil.com"
                className="text-xs text-slate-500 transition hover:text-cyan-400"
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
  showAlert?: boolean; // Show red dot indicator
}

const NavItem: FC<NavItemProps> = ({ item, showAlert = false }) => {
  const Icon = item.icon;

  return (
    <NavLink
      to={item.path}
      className={({ isActive }) =>
        cn(
          'group flex items-center gap-3 rounded-xl px-3 py-2.5 text-sm font-medium transition-all duration-200',
          isActive
            ? 'bg-gradient-to-r from-cyan-500/10 to-transparent text-white border border-cyan-500/20'
            : 'text-slate-400 hover:bg-white/5 hover:text-white border border-transparent'
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={cn(
              'relative flex h-7 w-7 items-center justify-center rounded-lg transition-all duration-200',
              isActive
                ? 'bg-cyan-500/20 text-cyan-400 shadow-glow-cyan'
                : 'bg-white/5 text-slate-500 group-hover:bg-white/10 group-hover:text-slate-300'
            )}
          >
            <Icon className="h-4 w-4" />
            {/* Alert indicator (red dot) */}
            {showAlert && (
              <span
                className="absolute -top-0.5 -right-0.5 h-2.5 w-2.5 rounded-full bg-red-500 ring-2 ring-dragonfly-navy-950 animate-pulse"
                aria-label="System alert"
              />
            )}
          </span>
          <div className="flex-1 min-w-0">
            <span className="block truncate">{item.label}</span>
            <span
              className={cn(
                'block text-[11px] font-normal leading-tight truncate',
                isActive ? 'text-slate-500' : 'text-slate-600'
              )}
            >
              {item.description}
            </span>
          </div>
          {isActive && (
            <span className="h-2 w-2 rounded-full bg-cyan-400 shadow-glow-cyan animate-pulse-slow" aria-hidden="true" />
          )}
        </>
      )}
    </NavLink>
  );
};

export default AppShellNew;
