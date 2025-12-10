/**
 * Sidebar - Financial Terminal Style Navigation
 *
 * Features:
 * - Collapsible (Ctrl+B or button toggle)
 * - Sectioned navigation (OPERATIONS, ANALYTICS, SYSTEM)
 * - Live System Status indicator (polls /api/health)
 * - Premium dark theme: bg-slate-950, border-slate-800
 */

import { type FC, useEffect } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  LayoutDashboard,
  Target,
  Briefcase,
  Settings,
  HelpCircle,
  ChevronLeft,
  ChevronRight,
  Headphones,
  TrendingUp,
  Terminal,
  PieChart,
  Activity,
  Radar,
  Database,
  Shield,
  Circle,
  Zap,
} from 'lucide-react';
import { cn } from '../lib/design-tokens';
import { useSystemHealth } from '../hooks/useSystemHealth';
import { useOpsAlerts } from '../hooks/useOpsAlerts';

// ═══════════════════════════════════════════════════════════════════════════
// NAVIGATION CONFIG
// ═══════════════════════════════════════════════════════════════════════════

interface NavigationItem {
  label: string;
  path: string;
  icon: typeof LayoutDashboard;
  shortLabel?: string; // For collapsed state
  alertKey?: string; // Key for dynamic alert indicator (e.g., 'ops' for Critical status)
}

interface NavigationSection {
  title: string;
  items: NavigationItem[];
}

const NAVIGATION_SECTIONS: NavigationSection[] = [
  {
    title: 'OPERATIONS',
    items: [
      { label: 'Ops Console', path: '/ops', icon: Headphones, shortLabel: 'OPS', alertKey: 'ops' },
      { label: 'Command Center', path: '/ops/console', icon: Terminal, shortLabel: 'CMD' },
      { label: 'Intake Station', path: '/intake', icon: Database, shortLabel: 'IN' },
      { label: 'Cases', path: '/cases', icon: Briefcase, shortLabel: 'CSE' },
    ],
  },
  {
    title: 'ANALYTICS',
    items: [
      { label: 'CEO Overview', path: '/ceo/overview', icon: TrendingUp, shortLabel: 'CEO' },
      { label: 'Portfolio', path: '/finance/portfolio', icon: PieChart, shortLabel: 'PRT' },
      { label: 'Radar', path: '/radar', icon: Radar, shortLabel: 'RDR' },
      { label: 'Collectability', path: '/collectability', icon: Target, shortLabel: 'CLT' },
      { label: 'Explorer', path: '/portfolio/explorer', icon: Activity, shortLabel: 'EXP' },
    ],
  },
  {
    title: 'SYSTEM',
    items: [
      { label: 'Settings', path: '/settings', icon: Settings, shortLabel: 'SET' },
      { label: 'Help', path: '/help', icon: HelpCircle, shortLabel: 'HLP' },
    ],
  },
];

// ═══════════════════════════════════════════════════════════════════════════
// SIDEBAR COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface SidebarProps {
  collapsed: boolean;
  onToggle: () => void;
  mobileOpen: boolean;
  onMobileClose: () => void;
}

const Sidebar: FC<SidebarProps> = ({ collapsed, onToggle, mobileOpen, onMobileClose }) => {
  const location = useLocation();
  const { status, environment, isOnline, latencyMs } = useSystemHealth();
  const { isCritical: opsAlertCritical, loading: opsAlertLoading } = useOpsAlerts(60000);

  // Close mobile menu on route change
  useEffect(() => {
    onMobileClose();
  }, [location.pathname, onMobileClose]);

  // Keyboard shortcut: Ctrl+B to toggle
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === 'b') {
        e.preventDefault();
        onToggle();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onToggle]);

  const sidebarWidth = collapsed ? 'w-16' : 'w-64';

  return (
    <>
      {/* Mobile overlay */}
      <AnimatePresence>
        {mobileOpen && (
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 z-40 bg-black/60 backdrop-blur-sm md:hidden"
            onClick={onMobileClose}
            aria-hidden="true"
          />
        )}
      </AnimatePresence>

      {/* Sidebar */}
      <aside
        className={cn(
          'fixed inset-y-0 left-0 z-50 flex flex-col transition-all duration-300 ease-out',
          'bg-slate-950 border-r border-slate-800',
          sidebarWidth,
          // Mobile: slide in/out
          'md:translate-x-0',
          mobileOpen ? 'translate-x-0' : '-translate-x-full md:translate-x-0'
        )}
      >
        {/* Logo & Toggle */}
        <div
          className={cn(
            'flex items-center border-b border-slate-800 h-14',
            collapsed ? 'justify-center px-2' : 'justify-between px-4'
          )}
        >
          {!collapsed && (
            <div className="flex items-center gap-2.5">
              <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-400">
                <Zap className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-bold text-white tracking-tight font-mono">DRAGONFLY</p>
                <p className="text-[10px] text-slate-500 font-mono tracking-wider">CIVIL v1.2</p>
              </div>
            </div>
          )}

          {collapsed && (
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-emerald-500/20 text-emerald-400">
              <Zap className="h-4 w-4" />
            </div>
          )}

          <button
            type="button"
            onClick={onToggle}
            className={cn(
              'hidden md:flex items-center justify-center rounded-md p-1.5',
              'text-slate-500 hover:text-white hover:bg-slate-800 transition-colors',
              collapsed && 'absolute -right-3 top-4 bg-slate-900 border border-slate-800 shadow-lg z-10'
            )}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4" />
            ) : (
              <ChevronLeft className="h-4 w-4" />
            )}
          </button>
        </div>

        {/* Navigation */}
        <nav className="flex-1 overflow-y-auto py-4 scrollbar-thin scrollbar-thumb-slate-700 scrollbar-track-transparent">
          {NAVIGATION_SECTIONS.map((section, sectionIndex) => (
            <div key={section.title} className={cn(sectionIndex > 0 && 'mt-6')}>
              {/* Section header */}
              {!collapsed && (
                <p className="mb-2 px-4 text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-600 font-mono">
                  {section.title}
                </p>
              )}

              {/* Section items */}
              <div className="space-y-0.5 px-2">
                {section.items.map((item) => (
                  <NavItem
                    key={item.path}
                    item={item}
                    collapsed={collapsed}
                    isActive={location.pathname === item.path || location.pathname.startsWith(item.path + '/')}
                    showAlert={item.alertKey === 'ops' && opsAlertCritical}
                    alertLoading={item.alertKey === 'ops' && opsAlertLoading}
                  />
                ))}
              </div>
            </div>
          ))}
        </nav>

        {/* System Status Indicator */}
        <div className="border-t border-slate-800 p-3">
          <SystemStatusIndicator
            collapsed={collapsed}
            isOnline={isOnline}
            environment={environment}
            latencyMs={latencyMs}
            status={status}
          />
        </div>
      </aside>
    </>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// NAV ITEM
// ═══════════════════════════════════════════════════════════════════════════

interface NavItemProps {
  item: NavigationItem;
  collapsed: boolean;
  isActive: boolean;
  showAlert?: boolean; // Show red dot indicator when system is Critical
  alertLoading?: boolean; // Show skeleton pulse while loading alert status
}

const NavItem: FC<NavItemProps> = ({ item, collapsed, isActive, showAlert = false, alertLoading = false }) => {
  const Icon = item.icon;

  return (
    <NavLink
      to={item.path}
      className={cn(
        'group flex items-center gap-3 rounded-md px-2.5 py-2 text-sm font-medium transition-all duration-150',
        'relative',
        isActive
          ? 'bg-slate-800/80 text-white'
          : 'text-slate-400 hover:bg-slate-800/50 hover:text-slate-200',
        collapsed && 'justify-center px-0'
      )}
      title={collapsed ? item.label : undefined}
    >
      {/* Active indicator bar */}
      {isActive && (
        <motion.div
          layoutId="sidebar-active-indicator"
          className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-5 bg-emerald-400 rounded-r-full"
          transition={{ type: 'spring', stiffness: 350, damping: 30 }}
        />
      )}

      {/* Icon with alert indicator */}
      <span className="relative">
        <Icon
          className={cn(
            'h-4 w-4 flex-shrink-0 transition-colors',
            isActive ? 'text-emerald-400' : 'text-slate-500 group-hover:text-slate-300'
          )}
        />
        {/* Alert indicator (red dot) */}
        {showAlert && (
          <span
            className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-red-500 ring-1 ring-slate-950 animate-pulse"
            aria-label="System critical alert"
          />
        )}
        {/* Loading skeleton for alert */}
        {alertLoading && !showAlert && (
          <span className="absolute -top-0.5 -right-0.5 h-2 w-2 rounded-full bg-slate-600 animate-pulse" />
        )}
      </span>

      {!collapsed && (
        <span className="truncate font-mono text-[13px]">{item.label}</span>
      )}

      {collapsed && item.shortLabel && (
        <span className="sr-only">{item.label}</span>
      )}
    </NavLink>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// SYSTEM STATUS INDICATOR
// ═══════════════════════════════════════════════════════════════════════════

interface SystemStatusIndicatorProps {
  collapsed: boolean;
  isOnline: boolean;
  environment: string;
  latencyMs: number | null;
  status: 'loading' | 'online' | 'offline';
}

const SystemStatusIndicator: FC<SystemStatusIndicatorProps> = ({
  collapsed,
  isOnline,
  environment,
  latencyMs,
  status,
}) => {
  const statusColor = status === 'loading'
    ? 'text-slate-500'
    : isOnline
      ? 'text-emerald-400'
      : 'text-red-400';

  const dotColor = status === 'loading'
    ? 'bg-slate-500'
    : isOnline
      ? 'bg-emerald-400'
      : 'bg-red-400';

  if (collapsed) {
    return (
      <div className="flex justify-center" title={`System ${isOnline ? 'Online' : 'Offline'}`}>
        <div className={cn('h-2 w-2 rounded-full animate-pulse', dotColor)} />
      </div>
    );
  }

  return (
    <div className="flex items-center gap-3 px-1">
      <div className="relative">
        <Circle className={cn('h-3 w-3 fill-current', statusColor)} />
        {isOnline && (
          <span className="absolute inset-0 rounded-full bg-emerald-400/30 animate-ping" />
        )}
      </div>
      <div className="flex-1 min-w-0">
        <p className={cn('text-xs font-mono font-medium', statusColor)}>
          {status === 'loading' ? 'CONNECTING...' : isOnline ? 'SYSTEM ONLINE' : 'OFFLINE'}
        </p>
        {isOnline && (
          <p className="text-[10px] text-slate-600 font-mono">
            {environment.toUpperCase()} • {latencyMs ? `${latencyMs}ms` : '–'}
          </p>
        )}
      </div>
      {isOnline && (
        <Shield className="h-3.5 w-3.5 text-emerald-500/50" />
      )}
    </div>
  );
};

export default Sidebar;
