/**
 * AppShell - Financial Terminal Layout
 *
 * Premium dark theme layout with:
 * - Collapsible Sidebar (OPERATIONS, ANALYTICS, SYSTEM sections)
 * - Fixed Topbar with breadcrumbs, global search, environment badge
 * - Responsive mobile drawer
 * - System status indicator
 *
 * Visual tokens:
 * - Background: bg-slate-950
 * - Borders: border-slate-800
 * - Muted text: text-slate-400
 * - Active text: text-white
 * - Accent: text-emerald-400
 */

import { type FC, useState, useEffect, useCallback } from 'react';
import { Outlet, useLocation } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import ReleaseNotesModal, { useReleaseNotesModal } from '../components/ReleaseNotesModal';
import { cn } from '../lib/design-tokens';
import { useSystemHealth } from '../hooks/useSystemHealth';
import Sidebar from './Sidebar';
import Topbar from './Topbar';

// ═══════════════════════════════════════════════════════════════════════════
// PERSISTENCE
// ═══════════════════════════════════════════════════════════════════════════

const SIDEBAR_COLLAPSED_KEY = 'dragonfly:sidebar-collapsed';

function loadSidebarState(): boolean {
  try {
    const stored = localStorage.getItem(SIDEBAR_COLLAPSED_KEY);
    return stored === 'true';
  } catch {
    return false;
  }
}

function saveSidebarState(collapsed: boolean): void {
  try {
    localStorage.setItem(SIDEBAR_COLLAPSED_KEY, String(collapsed));
  } catch {
    // Ignore storage errors
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// APP SHELL COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const AppShell: FC = () => {
  const location = useLocation();
  const releaseNotes = useReleaseNotesModal();
  const { environment } = useSystemHealth();

  const [sidebarCollapsed, setSidebarCollapsed] = useState(loadSidebarState);
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

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

  // Enable dark mode by default
  useEffect(() => {
    document.documentElement.classList.add('dark');
  }, []);

  const handleSidebarToggle = useCallback(() => {
    setSidebarCollapsed((prev) => {
      const next = !prev;
      saveSidebarState(next);
      return next;
    });
  }, []);

  const handleMobileMenuClose = useCallback(() => {
    setMobileMenuOpen(false);
  }, []);

  const handleMobileMenuOpen = useCallback(() => {
    setMobileMenuOpen(true);
  }, []);

  // Calculate content margin based on sidebar state
  const contentMargin = sidebarCollapsed ? 'md:ml-16' : 'md:ml-64';

  return (
    <div className="min-h-screen bg-slate-950">
      {/* Release Notes Modal */}
      <ReleaseNotesModal isOpen={releaseNotes.isOpen} onClose={releaseNotes.close} />

      {/* Sidebar */}
      <Sidebar
        collapsed={sidebarCollapsed}
        onToggle={handleSidebarToggle}
        mobileOpen={mobileMenuOpen}
        onMobileClose={handleMobileMenuClose}
      />

      {/* Topbar */}
      <Topbar
        onMobileMenuOpen={handleMobileMenuOpen}
        environment={environment}
        sidebarCollapsed={sidebarCollapsed}
      />

      {/* Main Content Area */}
      <main
        className={cn(
          'min-h-screen pt-14 transition-all duration-300',
          contentMargin
        )}
      >
        {/* Content wrapper with subtle grid pattern */}
        <div className="min-h-[calc(100vh-3.5rem)] bg-gradient-to-b from-slate-950 to-slate-900">
          {/* Grid pattern overlay (optional fintech aesthetic) */}
          <div
            className="absolute inset-0 opacity-[0.02] pointer-events-none"
            style={{
              backgroundImage: `
                linear-gradient(to right, rgb(148 163 184 / 0.1) 1px, transparent 1px),
                linear-gradient(to bottom, rgb(148 163 184 / 0.1) 1px, transparent 1px)
              `,
              backgroundSize: '24px 24px',
            }}
          />

          {/* Page content */}
          <div className="relative mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
            <AnimatePresence mode="wait">
              <motion.div
                key={location.pathname}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -8 }}
                transition={{ duration: 0.15, ease: 'easeOut' }}
              >
                <Outlet />
              </motion.div>
            </AnimatePresence>
          </div>
        </div>
      </main>

      {/* Footer */}
      <footer
        className={cn(
          'border-t border-slate-800 bg-slate-950 px-4 py-4 sm:px-6',
          'transition-all duration-300',
          contentMargin
        )}
      >
        <div className="mx-auto flex max-w-7xl items-center justify-between">
          <p className="text-[11px] text-slate-600 font-mono">
            © {new Date().getFullYear()} Dragonfly Civil • Asset Recovery Platform
          </p>
          <div className="flex items-center gap-4">
            <button
              type="button"
              onClick={releaseNotes.open}
              className="text-[11px] text-slate-600 hover:text-emerald-400 transition-colors font-mono"
            >
              v1.2.0
            </button>
            <span className="text-slate-800">•</span>
            <a
              href="mailto:support@dragonflycivil.com"
              className="text-[11px] text-slate-600 hover:text-slate-400 transition-colors font-mono"
            >
              Support
            </a>
          </div>
        </div>
      </footer>
    </div>
  );
};

export default AppShell;
