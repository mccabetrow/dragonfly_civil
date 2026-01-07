/**
 * SourceIndicator - Data Source Status Badge
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Shows the current data source state from the circuit breaker.
 *
 * Behavior:
 * - PostgREST (healthy): Invisible or tiny green dot "Live"
 * - API (failover): Amber badge "🛡️ Direct DB Mode"
 *
 * Placement: Next to EnvironmentBadge in Topbar.tsx
 */

import { type FC } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Shield, Wifi } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { useDataSourceStatus } from '../../context/DataSourceContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface SourceIndicatorProps {
  /** Show green "Live" indicator when healthy (default: false - invisible when healthy) */
  showWhenHealthy?: boolean;
  /** Compact mode for tight spaces (default: false) */
  compact?: boolean;
  /** Custom className */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const SourceIndicator: FC<SourceIndicatorProps> = ({
  showWhenHealthy = false,
  compact = false,
  className,
}) => {
  const { activeSource, isInFailover, failoverTimeRemaining } = useDataSourceStatus();

  // ─────────────────────────────────────────────────────────────────────────
  // PostgREST (Healthy State)
  // ─────────────────────────────────────────────────────────────────────────
  if (activeSource === 'postgrest' && !isInFailover) {
    // Invisible when healthy (default) or show subtle "Live" indicator
    if (!showWhenHealthy) {
      return null;
    }

    return (
      <div
        className={cn(
          'flex items-center gap-1.5 px-2 py-1 rounded-md',
          'font-mono text-[10px] font-medium uppercase tracking-wider',
          'bg-emerald-500/5 text-emerald-400/70 border border-emerald-500/10',
          className
        )}
        title="Connected to Supabase PostgREST"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
        {!compact && <span>Live</span>}
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // API (Failover State)
  // ─────────────────────────────────────────────────────────────────────────
  
  // Format remaining time (e.g., "4:32" for 4 min 32 sec)
  const minutes = Math.floor(failoverTimeRemaining / 60);
  const seconds = failoverTimeRemaining % 60;
  const timeDisplay = `${minutes}:${seconds.toString().padStart(2, '0')}`;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0, scale: 0.9, x: 10 }}
        animate={{ opacity: 1, scale: 1, x: 0 }}
        exit={{ opacity: 0, scale: 0.9, x: 10 }}
        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
        className={cn(
          'flex items-center gap-1.5 px-2.5 py-1 rounded-md',
          'font-mono text-[10px] font-medium uppercase tracking-wider',
          'bg-amber-500/10 text-amber-400 border border-amber-500/20',
          'cursor-help',
          className
        )}
        title={`Failover active - returning to PostgREST in ${timeDisplay}`}
      >
        <Shield className="h-3 w-3" />
        {compact ? (
          <span>Backup</span>
        ) : (
          <>
            <span>Direct DB</span>
            <span className="text-amber-400/60">({timeDisplay})</span>
          </>
        )}
      </motion.div>
    </AnimatePresence>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// SAFE VERSION (No Context Required)
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Safe version that won't crash if DataSourceProvider is missing.
 * Useful during migration when not all pages are wrapped.
 */
export const SourceIndicatorSafe: FC<SourceIndicatorProps> = (props) => {
  try {
    return <SourceIndicator {...props} />;
  } catch {
    // Context not available - return null silently
    return null;
  }
};

// ═══════════════════════════════════════════════════════════════════════════
// FOOTER VARIANT
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Footer-style indicator for bottom bars.
 * More subtle, horizontal text layout.
 */
export const SourceIndicatorFooter: FC<{ className?: string }> = ({ className }) => {
  const { activeSource, isInFailover, failoverTimeRemaining } = useDataSourceStatus();

  if (activeSource === 'postgrest' && !isInFailover) {
    return (
      <span className={cn('text-[10px] text-slate-600 font-mono', className)}>
        <Wifi className="h-3 w-3 inline mr-1 text-emerald-500/50" />
        Supabase
      </span>
    );
  }

  const minutes = Math.floor(failoverTimeRemaining / 60);
  const seconds = failoverTimeRemaining % 60;
  const timeDisplay = `${minutes}:${seconds.toString().padStart(2, '0')}`;

  return (
    <motion.span
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      className={cn('text-[10px] text-amber-400/80 font-mono', className)}
    >
      <Shield className="h-3 w-3 inline mr-1" />
      Direct DB ({timeDisplay})
    </motion.span>
  );
};

export default SourceIndicator;
