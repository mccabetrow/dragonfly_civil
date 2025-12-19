/**
 * FreshnessBadge - Trust cue showing data recency
 *
 * Displays timestamps in user-friendly formats:
 * - "Updated 2m ago" (compact)
 * - "Snapshot as of: 14:32:15 UTC" (full)
 */

import { type FC, useMemo } from 'react';
import { Clock, CheckCircle2, AlertCircle } from 'lucide-react';
import { cn } from '../../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface FreshnessBadgeProps {
  /** ISO timestamp or Date object */
  timestamp: string | Date | null | undefined;
  /** Display variant */
  variant?: 'compact' | 'full' | 'inline';
  /** Staleness threshold in seconds (default: 5 minutes) */
  staleThresholdSec?: number;
  /** Custom prefix text */
  prefix?: string;
  /** Additional CSS classes */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function parseTimestamp(ts: string | Date | null | undefined): Date | null {
  if (!ts) return null;
  if (ts instanceof Date) return ts;
  const parsed = new Date(ts);
  return isNaN(parsed.getTime()) ? null : parsed;
}

function formatTimeAgo(date: Date): string {
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffSec = Math.floor(diffMs / 1000);

  if (diffSec < 5) return 'just now';
  if (diffSec < 60) return `${diffSec}s ago`;

  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `${diffMin}m ago`;

  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `${diffHrs}h ago`;

  const diffDays = Math.floor(diffHrs / 24);
  return `${diffDays}d ago`;
}

function formatUtcTime(date: Date): string {
  return date.toISOString().slice(11, 19) + ' UTC';
}

function formatFullTimestamp(date: Date): string {
  return date.toISOString().replace('T', ' ').slice(0, 19) + ' UTC';
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const FreshnessBadge: FC<FreshnessBadgeProps> = ({
  timestamp,
  variant = 'compact',
  staleThresholdSec = 300, // 5 minutes
  prefix,
  className,
}) => {
  const parsed = useMemo(() => parseTimestamp(timestamp), [timestamp]);

  const { display, isStale } = useMemo(() => {
    if (!parsed) {
      return { display: '—', isStale: false };
    }

    const now = new Date();
    const ageSec = Math.floor((now.getTime() - parsed.getTime()) / 1000);
    const stale = ageSec > staleThresholdSec;

    switch (variant) {
      case 'full':
        return { display: formatUtcTime(parsed), isStale: stale };
      case 'inline':
        return { display: formatFullTimestamp(parsed), isStale: stale };
      case 'compact':
      default:
        return { display: formatTimeAgo(parsed), isStale: stale };
    }
  }, [parsed, variant, staleThresholdSec]);

  if (!parsed) {
    return null;
  }

  // Compact variant (for StatCard footers)
  if (variant === 'compact') {
    return (
      <span
        className={cn(
          'inline-flex items-center gap-1 text-[10px] font-medium uppercase tracking-wide',
          isStale ? 'text-amber-600' : 'text-slate-400',
          className
        )}
        title={formatFullTimestamp(parsed)}
      >
        {isStale ? (
          <AlertCircle className="h-3 w-3" aria-hidden="true" />
        ) : (
          <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
        )}
        {prefix ?? 'Updated'} {display}
      </span>
    );
  }

  // Full variant (for page header)
  if (variant === 'full') {
    return (
      <div
        className={cn(
          'inline-flex items-center gap-2 rounded-full border px-3 py-1.5',
          isStale
            ? 'border-amber-200 bg-amber-50 text-amber-700'
            : 'border-white/20 bg-white/10 text-white/80',
          className
        )}
        title={formatFullTimestamp(parsed)}
      >
        <Clock className="h-3.5 w-3.5" aria-hidden="true" />
        <span className="text-xs font-semibold uppercase tracking-wide">
          {prefix ?? 'Snapshot as of:'} {display}
        </span>
      </div>
    );
  }

  // Inline variant (for tooltips, tables)
  return (
    <span
      className={cn(
        'text-xs text-slate-500',
        isStale && 'text-amber-600',
        className
      )}
      title={formatFullTimestamp(parsed)}
    >
      {display}
    </span>
  );
};

export default FreshnessBadge;
