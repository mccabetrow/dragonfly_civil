/**
 * TierDistributionBar - Clickable tier distribution visualization
 *
 * Horizontal segmented bar showing case distribution by tier.
 * Each segment is clickable to navigate to /collectability with that tier filter.
 */

import { type FC } from 'react';
import { useNavigate } from 'react-router-dom';
import { cn } from '../../lib/design-tokens';
import { formatNumber, formatCurrency } from '../../lib/utils/formatters';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type Tier = 'A' | 'B' | 'C';

export interface TierSegment {
  tier: Tier;
  caseCount: number;
  totalValue: number;
}

export interface TierDistributionBarProps {
  /** Segments to display */
  segments: TierSegment[];
  /** Whether data is loading */
  loading?: boolean;
  /** Handler for segment click (overrides default navigation) */
  onSegmentClick?: (tier: Tier) => void;
  /** Additional CSS classes */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// TIER STYLING
// ═══════════════════════════════════════════════════════════════════════════

const TIER_STYLES: Record<Tier, { bg: string; bgHover: string; text: string; label: string }> = {
  A: {
    bg: 'bg-emerald-500',
    bgHover: 'hover:bg-emerald-600',
    text: 'text-emerald-700',
    label: 'High Priority',
  },
  B: {
    bg: 'bg-amber-400',
    bgHover: 'hover:bg-amber-500',
    text: 'text-amber-700',
    label: 'Medium',
  },
  C: {
    bg: 'bg-slate-300',
    bgHover: 'hover:bg-slate-400',
    text: 'text-slate-600',
    label: 'Lower',
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const TierDistributionBar: FC<TierDistributionBarProps> = ({
  segments,
  loading = false,
  onSegmentClick,
  className,
}) => {
  const navigate = useNavigate();

  // Calculate totals
  const total = segments.reduce((sum, s) => sum + s.caseCount, 0);
  const totalValue = segments.reduce((sum, s) => sum + s.totalValue, 0);

  // Handle segment click
  const handleClick = (tier: Tier) => {
    if (onSegmentClick) {
      onSegmentClick(tier);
    } else {
      navigate(`/collectability?tier=${tier}`);
    }
  };

  if (loading) {
    return (
      <div className={cn('animate-pulse', className)}>
        <div className="mb-3 flex items-center justify-between">
          <div className="h-4 w-32 rounded bg-slate-200" />
          <div className="h-4 w-24 rounded bg-slate-200" />
        </div>
        <div className="flex h-8 overflow-hidden rounded-full bg-slate-100">
          <div className="h-full w-1/3 bg-slate-200" />
          <div className="h-full w-1/3 bg-slate-150" />
          <div className="h-full w-1/3 bg-slate-100" />
        </div>
      </div>
    );
  }

  if (total === 0) {
    return (
      <div className={cn('text-center py-4', className)}>
        <p className="text-sm text-slate-500">No cases to display</p>
      </div>
    );
  }

  return (
    <div className={className}>
      {/* Header */}
      <div className="mb-3 flex items-center justify-between">
        <p className="text-sm font-medium text-slate-700">
          Portfolio Distribution
        </p>
        <p className="text-sm text-slate-500">
          {formatNumber(total)} cases · {formatCurrency(totalValue)}
        </p>
      </div>

      {/* Bar */}
      <div className="flex h-8 overflow-hidden rounded-full bg-slate-100 shadow-inner">
        {segments.map((segment) => {
          const percentage = (segment.caseCount / total) * 100;
          if (percentage === 0) return null;

          const style = TIER_STYLES[segment.tier];

          return (
            <button
              key={segment.tier}
              type="button"
              onClick={() => handleClick(segment.tier)}
              className={cn(
                'group relative flex items-center justify-center transition-all duration-200',
                style.bg,
                style.bgHover,
                'focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-white/50',
                'active:scale-[0.99]'
              )}
              style={{ width: `${percentage}%` }}
              aria-label={`Tier ${segment.tier}: ${segment.caseCount} cases (${percentage.toFixed(0)}%)`}
            >
              {/* Segment label - only show if wide enough */}
              {percentage >= 15 && (
                <span className="text-xs font-bold text-white/90 drop-shadow-sm">
                  {segment.tier}
                </span>
              )}

              {/* Hover tooltip */}
              <div 
                className={cn(
                  'pointer-events-none absolute -top-16 left-1/2 -translate-x-1/2 opacity-0 transition-opacity',
                  'rounded-lg bg-slate-900 px-3 py-2 text-left shadow-lg',
                  'group-hover:opacity-100 group-focus:opacity-100'
                )}
              >
                <div className="whitespace-nowrap text-[11px] font-medium text-white">
                  Tier {segment.tier}: {style.label}
                </div>
                <div className="whitespace-nowrap text-[11px] text-slate-300">
                  {formatNumber(segment.caseCount)} cases · {formatCurrency(segment.totalValue)}
                </div>
                {/* Arrow */}
                <div className="absolute left-1/2 top-full -translate-x-1/2 border-4 border-transparent border-t-slate-900" />
              </div>
            </button>
          );
        })}
      </div>

      {/* Legend */}
      <div className="mt-3 flex flex-wrap items-center gap-4">
        {segments.map((segment) => {
          const percentage = total > 0 ? (segment.caseCount / total) * 100 : 0;
          const style = TIER_STYLES[segment.tier];

          return (
            <button
              key={segment.tier}
              type="button"
              onClick={() => handleClick(segment.tier)}
              className="group flex items-center gap-2 rounded-lg px-2 py-1 transition hover:bg-slate-50"
            >
              <span className={cn('h-2.5 w-2.5 rounded-full', style.bg)} />
              <span className="text-xs font-medium text-slate-600 group-hover:text-slate-900">
                Tier {segment.tier}
              </span>
              <span className="text-xs text-slate-400">
                {formatNumber(segment.caseCount)} ({percentage.toFixed(0)}%)
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
};

export default TierDistributionBar;
