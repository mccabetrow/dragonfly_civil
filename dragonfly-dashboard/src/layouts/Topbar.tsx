/**
 * Topbar - Financial Terminal Style Header
 *
 * Features:
 * - Dynamic breadcrumbs (e.g., Portfolio / Case #12345)
 * - Global Search Bar (Cmd+K style) integration
 * - Environment badge (PROD/DEV with color coding)
 * - Premium dark theme: bg-slate-950, border-slate-800
 */

import { type FC, useState, useEffect, useCallback, useRef } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Menu,
  Search,
  Command,
  RefreshCw,
  Bell,
  ChevronRight,
  X,
  Briefcase,
  User,
  Clock,
} from 'lucide-react';
import { cn } from '../lib/design-tokens';
import { useRefreshBus } from '../context/RefreshContext';
import { apiClient } from '../lib/apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface BreadcrumbItem {
  label: string;
  path?: string;
}

interface TopbarProps {
  onMobileMenuOpen: () => void;
  environment: string;
  sidebarCollapsed: boolean;
}

interface SearchResult {
  id: string;
  type: 'judgment' | 'plaintiff' | 'case';
  title: string;
  subtitle: string;
  path: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// ROUTE TO BREADCRUMB MAPPING
// ═══════════════════════════════════════════════════════════════════════════

const ROUTE_LABELS: Record<string, string> = {
  '/': 'Dashboard',
  '/dashboard': 'Dashboard',
  '/ceo/overview': 'CEO Overview',
  '/finance/portfolio': 'Portfolio',
  '/portfolio/explorer': 'Portfolio Explorer',
  '/overview': 'Overview',
  '/ops': 'Ops Console',
  '/ops/intake': 'Intake',
  '/ops/queue': 'Queue',
  '/ops/console': 'Command Center',
  '/intake': 'Intake Station',
  '/radar': 'Enforcement Radar',
  '/enforcement/engine': 'Enforcement Engine',
  '/collectability': 'Collectability',
  '/cases': 'Cases',
  '/settings': 'Settings',
  '/settings/ingestion': 'Data Ingestion',
  '/help': 'Help',
};

function buildBreadcrumbs(pathname: string): BreadcrumbItem[] {
  const segments = pathname.split('/').filter(Boolean);
  const crumbs: BreadcrumbItem[] = [];

  // Always start with root
  if (pathname !== '/') {
    crumbs.push({ label: 'Dashboard', path: '/' });
  }

  // Build path progressively
  let currentPath = '';
  segments.forEach((segment, index) => {
    currentPath += `/${segment}`;

    // Check if we have a label for this path
    const label = ROUTE_LABELS[currentPath];
    if (label) {
      // Last segment is current (no link)
      if (index === segments.length - 1) {
        crumbs.push({ label });
      } else {
        crumbs.push({ label, path: currentPath });
      }
    }
  });

  // If no crumbs built (unknown route), show generic
  if (crumbs.length === 0) {
    crumbs.push({ label: 'Dashboard', path: '/' });
    crumbs.push({ label: pathname.split('/').pop() || 'Page' });
  }

  return crumbs;
}

// ═══════════════════════════════════════════════════════════════════════════
// TOPBAR COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const Topbar: FC<TopbarProps> = ({ onMobileMenuOpen, environment, sidebarCollapsed }) => {
  const location = useLocation();
  const navigate = useNavigate();
  const { triggerRefresh, isRefreshing } = useRefreshBus();
  const [searchOpen, setSearchOpen] = useState(false);
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  const breadcrumbs = buildBreadcrumbs(location.pathname);
  const isProd = environment.toLowerCase() === 'prod' || environment.toLowerCase() === 'production';

  // Keyboard shortcut: Cmd/Ctrl+K to open search
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        setSearchOpen(true);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, []);

  const handleRefresh = useCallback(() => {
    setLastRefresh(new Date());
    triggerRefresh();
  }, [triggerRefresh]);

  const marginLeft = sidebarCollapsed ? 'md:ml-16' : 'md:ml-64';

  return (
    <>
      <header
        className={cn(
          'fixed top-0 right-0 left-0 z-30 h-14',
          'bg-slate-950/95 backdrop-blur-xl border-b border-slate-800',
          'transition-all duration-300',
          marginLeft
        )}
      >
        <div className="flex items-center justify-between h-full px-4">
          {/* Left: Mobile menu + Breadcrumbs */}
          <div className="flex items-center gap-4">
            {/* Mobile menu toggle */}
            <button
              type="button"
              onClick={onMobileMenuOpen}
              className="rounded-md p-2 text-slate-400 hover:bg-slate-800 hover:text-white md:hidden"
              aria-label="Open menu"
            >
              <Menu className="h-5 w-5" />
            </button>

            {/* Breadcrumbs */}
            <nav className="hidden items-center gap-1 text-sm md:flex" aria-label="Breadcrumb">
              {breadcrumbs.map((crumb, index) => (
                <span key={index} className="flex items-center gap-1">
                  {index > 0 && (
                    <ChevronRight className="h-3.5 w-3.5 text-slate-600" aria-hidden="true" />
                  )}
                  {crumb.path ? (
                    <NavLink
                      to={crumb.path}
                      className="text-slate-500 hover:text-slate-300 transition-colors font-mono text-[13px]"
                    >
                      {crumb.label}
                    </NavLink>
                  ) : (
                    <span className="text-white font-mono text-[13px] font-medium">
                      {crumb.label}
                    </span>
                  )}
                </span>
              ))}
            </nav>

            {/* Mobile: Current page title */}
            <h1 className="text-sm font-semibold text-white font-mono md:hidden">
              {breadcrumbs[breadcrumbs.length - 1]?.label || 'Dashboard'}
            </h1>
          </div>

          {/* Right: Actions */}
          <div className="flex items-center gap-2">
            {/* Global Search Button */}
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              className={cn(
                'hidden md:flex items-center gap-2 px-3 py-1.5 rounded-md',
                'bg-slate-800/50 border border-slate-700/50',
                'text-slate-400 hover:text-slate-200 hover:border-slate-600',
                'transition-all duration-150'
              )}
            >
              <Search className="h-3.5 w-3.5" />
              <span className="text-xs font-mono">Search judgments...</span>
              <kbd className="hidden lg:inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded bg-slate-700/50 text-[10px] font-mono text-slate-500">
                <Command className="h-2.5 w-2.5" />K
              </kbd>
            </button>

            {/* Mobile search */}
            <button
              type="button"
              onClick={() => setSearchOpen(true)}
              className="rounded-md p-2 text-slate-400 hover:bg-slate-800 hover:text-white md:hidden"
              aria-label="Search"
            >
              <Search className="h-4 w-4" />
            </button>

            {/* Separator */}
            <div className="hidden md:block h-5 w-px bg-slate-800" />

            {/* Last refresh indicator */}
            {lastRefresh && (
              <span className="hidden lg:flex items-center gap-1 text-[10px] text-slate-600 font-mono">
                <Clock className="h-3 w-3" />
                {lastRefresh.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}

            {/* Refresh button */}
            <button
              type="button"
              onClick={handleRefresh}
              disabled={isRefreshing}
              className={cn(
                'rounded-md p-2 text-slate-400 hover:bg-slate-800 hover:text-white',
                'transition-colors disabled:opacity-50'
              )}
              aria-label="Refresh data"
            >
              <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
            </button>

            {/* Notifications */}
            <button
              type="button"
              className="rounded-md p-2 text-slate-400 hover:bg-slate-800 hover:text-white relative"
              aria-label="Notifications"
            >
              <Bell className="h-4 w-4" />
              {/* Notification dot */}
              <span className="absolute top-1.5 right-1.5 h-1.5 w-1.5 rounded-full bg-emerald-400" />
            </button>

            {/* Environment Badge */}
            <EnvironmentBadge environment={environment} isProd={isProd} />

            {/* User Avatar */}
            <div className="ml-1 flex h-8 w-8 items-center justify-center rounded-md bg-slate-800 border border-slate-700 text-xs font-bold text-slate-300 font-mono">
              DC
            </div>
          </div>
        </div>
      </header>

      {/* Global Search Modal */}
      <GlobalSearchModal
        isOpen={searchOpen}
        onClose={() => setSearchOpen(false)}
        onNavigate={(path) => {
          navigate(path);
          setSearchOpen(false);
        }}
      />
    </>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// ENVIRONMENT BADGE
// ═══════════════════════════════════════════════════════════════════════════

interface EnvironmentBadgeProps {
  environment: string;
  isProd: boolean;
}

const EnvironmentBadge: FC<EnvironmentBadgeProps> = ({ environment, isProd }) => {
  return (
    <div
      className={cn(
        'hidden sm:flex items-center gap-1.5 px-2.5 py-1 rounded-md',
        'font-mono text-[11px] font-semibold uppercase tracking-wider',
        isProd
          ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
          : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
      )}
    >
      <span
        className={cn(
          'h-1.5 w-1.5 rounded-full',
          isProd ? 'bg-emerald-400 animate-pulse' : 'bg-amber-400'
        )}
      />
      {environment.toUpperCase()}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// GLOBAL SEARCH MODAL
// ═══════════════════════════════════════════════════════════════════════════

interface GlobalSearchModalProps {
  isOpen: boolean;
  onClose: () => void;
  onNavigate: (path: string) => void;
}

const GlobalSearchModal: FC<GlobalSearchModalProps> = ({ isOpen, onClose, onNavigate }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selectedIndex, setSelectedIndex] = useState(0);
  const [isSearching, setIsSearching] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Focus input when modal opens
  useEffect(() => {
    if (isOpen) {
      setQuery('');
      setResults([]);
      setSelectedIndex(0);
      setTimeout(() => inputRef.current?.focus(), 50);
    }
  }, [isOpen]);

  // Search debounce
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      return;
    }

    const timer = setTimeout(async () => {
      setIsSearching(true);
      try {
        // Search judgments via API
        const response = await apiClient.get<{ items: SearchResult[] }>(
          `/api/v1/search/judgments?q=${encodeURIComponent(query)}&limit=8`
        );
        setResults(response.items || []);
      } catch (err) {
        console.error('[GlobalSearch] Search error:', err);
        // Fallback: show quick nav options
        setResults([
          { id: 'nav-cases', type: 'case', title: 'Go to Cases', subtitle: 'Browse all judgments', path: '/cases' },
          { id: 'nav-ops', type: 'case', title: 'Go to Ops Console', subtitle: 'Call queue and tasks', path: '/ops' },
        ]);
      } finally {
        setIsSearching(false);
      }
    }, 300);

    return () => clearTimeout(timer);
  }, [query]);

  // Keyboard navigation
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        onClose();
      } else if (e.key === 'ArrowDown') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.min(prev + 1, results.length - 1));
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        setSelectedIndex((prev) => Math.max(prev - 1, 0));
      } else if (e.key === 'Enter' && results[selectedIndex]) {
        onNavigate(results[selectedIndex].path);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, results, selectedIndex, onClose, onNavigate]);

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <div className="fixed inset-0 z-[100] flex items-start justify-center pt-[15vh]">
        {/* Backdrop */}
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          className="absolute inset-0 bg-black/70 backdrop-blur-sm"
          onClick={onClose}
        />

        {/* Modal */}
        <motion.div
          initial={{ opacity: 0, scale: 0.95, y: -20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.95, y: -20 }}
          transition={{ type: 'spring', stiffness: 400, damping: 30 }}
          className={cn(
            'relative w-full max-w-xl mx-4',
            'bg-slate-900 border border-slate-700 rounded-xl shadow-2xl shadow-black/50',
            'overflow-hidden'
          )}
        >
          {/* Search Input */}
          <div className="flex items-center gap-3 px-4 py-3 border-b border-slate-800">
            <Search className="h-5 w-5 text-slate-500" />
            <input
              ref={inputRef}
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search judgments by case number, defendant, or amount..."
              className={cn(
                'flex-1 bg-transparent text-white placeholder-slate-500',
                'text-sm font-mono focus:outline-none'
              )}
            />
            {query && (
              <button
                type="button"
                onClick={() => setQuery('')}
                className="text-slate-500 hover:text-slate-300"
              >
                <X className="h-4 w-4" />
              </button>
            )}
            <kbd className="hidden sm:inline-flex items-center px-2 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-slate-500">
              ESC
            </kbd>
          </div>

          {/* Results */}
          <div className="max-h-80 overflow-y-auto">
            {isSearching && (
              <div className="flex items-center justify-center py-8">
                <RefreshCw className="h-5 w-5 text-slate-500 animate-spin" />
              </div>
            )}

            {!isSearching && query && results.length === 0 && (
              <div className="py-8 text-center">
                <p className="text-sm text-slate-500 font-mono">No results found</p>
                <p className="text-xs text-slate-600 mt-1">Try a different search term</p>
              </div>
            )}

            {!isSearching && results.length > 0 && (
              <div className="py-2">
                {results.map((result, index) => (
                  <button
                    key={result.id}
                    type="button"
                    onClick={() => onNavigate(result.path)}
                    onMouseEnter={() => setSelectedIndex(index)}
                    className={cn(
                      'w-full flex items-center gap-3 px-4 py-2.5 text-left',
                      'transition-colors',
                      index === selectedIndex
                        ? 'bg-slate-800/80'
                        : 'hover:bg-slate-800/50'
                    )}
                  >
                    <div
                      className={cn(
                        'flex h-8 w-8 items-center justify-center rounded-md',
                        'bg-slate-700/50'
                      )}
                    >
                      {result.type === 'judgment' && <Briefcase className="h-4 w-4 text-slate-400" />}
                      {result.type === 'plaintiff' && <User className="h-4 w-4 text-slate-400" />}
                      {result.type === 'case' && <Briefcase className="h-4 w-4 text-slate-400" />}
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-white font-mono truncate">{result.title}</p>
                      <p className="text-xs text-slate-500 truncate">{result.subtitle}</p>
                    </div>
                    {index === selectedIndex && (
                      <ChevronRight className="h-4 w-4 text-slate-500" />
                    )}
                  </button>
                ))}
              </div>
            )}

            {/* Quick actions when no query */}
            {!query && (
              <div className="py-2">
                <p className="px-4 py-2 text-[10px] font-semibold uppercase tracking-wider text-slate-600 font-mono">
                  Quick Actions
                </p>
                {[
                  { label: 'Go to Cases', path: '/cases', icon: Briefcase },
                  { label: 'Go to Ops Console', path: '/ops', icon: User },
                  { label: 'Go to Portfolio', path: '/finance/portfolio', icon: Briefcase },
                ].map((action) => (
                  <button
                    key={action.path}
                    type="button"
                    onClick={() => onNavigate(action.path)}
                    className={cn(
                      'w-full flex items-center gap-3 px-4 py-2.5 text-left',
                      'text-slate-400 hover:text-white hover:bg-slate-800/50',
                      'transition-colors'
                    )}
                  >
                    <action.icon className="h-4 w-4" />
                    <span className="text-sm font-mono">{action.label}</span>
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="flex items-center justify-between px-4 py-2.5 border-t border-slate-800 bg-slate-900/80">
            <div className="flex items-center gap-4">
              <span className="flex items-center gap-1 text-[10px] text-slate-600 font-mono">
                <kbd className="px-1 py-0.5 rounded bg-slate-800">↑↓</kbd> navigate
              </span>
              <span className="flex items-center gap-1 text-[10px] text-slate-600 font-mono">
                <kbd className="px-1.5 py-0.5 rounded bg-slate-800">↵</kbd> select
              </span>
            </div>
            <span className="text-[10px] text-slate-600 font-mono">
              Powered by Dragonfly Search
            </span>
          </div>
        </motion.div>
      </div>
    </AnimatePresence>
  );
};

export default Topbar;
