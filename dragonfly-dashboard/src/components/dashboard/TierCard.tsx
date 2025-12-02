/**
 * TierCard - Collectability tier summary card
 *
 * Displays tier information with:
 * - Clear tier badge (A/B/C)
 * - Case count and total value
 * - Progress indicator
 * - Description and action hints
 */

import { type FC } from 'react';
import { ChevronRight, ArrowUp, ArrowDown } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { Card } from '../ui/Card';
import { TierBadge } from '../ui/Badge';
import { Skeleton } from '../ui/Skeleton';
import { formatCurrency, formatNumber } from '../../lib/utils/formatters';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type Tier = 'A' | 'B' | 'C';

export interface TierCardProps {
  /** Tier level */
  tier: Tier;

  /** Number of cases in this tier */
  caseCount: number;

  /** Total judgment value in this tier */
  totalValue: number;

  /** Change in case count from previous period */
  countChange?: number;

  /** Click handler */
  onClick?: () => void;

  /** Whether data is loading */
  loading?: boolean;

  /** Additional CSS classes */
  className?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// TIER METADATA
// ═══════════════════════════════════════════════════════════════════════════

const TIER_METADATA: Record<Tier, { 
  title: string; 
  description: string;
  actionHint: string;
  priority: string;
}> = {
  A: {
    title: 'High Priority',
    description: 'Most likely to collect. Focus here first.',
    actionHint: 'Start outreach immediately',
    priority: 'Priority 1',
  },
  B: {
    title: 'Medium Priority',
    description: 'Good potential with some obstacles.',
    actionHint: 'Schedule for follow-up',
    priority: 'Priority 2',
  },
  C: {
    title: 'Lower Priority',
    description: 'Challenging cases requiring patience.',
    actionHint: 'Review quarterly',
    priority: 'Priority 3',
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const TierCard: FC<TierCardProps> = ({
  tier,
  caseCount,
  totalValue,
  countChange,
  onClick,
  loading = false,
  className,
}) => {
  const metadata = TIER_METADATA[tier];

  // Loading skeleton
  if (loading) {
    return (
      <Card className={cn('p-5', className)}>
        <div className="flex items-start justify-between">
          <Skeleton className="h-6 w-6 rounded-md" />
          <Skeleton className="h-4 w-20" />
        </div>
        <Skeleton className="mt-4 h-8 w-24" />
        <Skeleton className="mt-2 h-4 w-32" />
        <Skeleton className="mt-4 h-3 w-full" />
      </Card>
    );
  }

  // Get tier accent colors
  const accentStyles: Record<Tier, string> = {
    A: 'border-l-emerald-500 hover:border-l-emerald-600',
    B: 'border-l-amber-500 hover:border-l-amber-600',
    C: 'border-l-slate-400 hover:border-l-slate-500',
  };

  const bgGradients: Record<Tier, string> = {
    A: 'from-emerald-50/50 to-transparent',
    B: 'from-amber-50/50 to-transparent',
    C: 'from-slate-50/50 to-transparent',
  };

  return (
    <Card
      variant={onClick ? 'interactive' : 'default'}
      onClick={onClick}
      className={cn(
        'relative overflow-hidden border-l-4 p-5 transition-all',
        accentStyles[tier],
        className
      )}
    >
      {/* Background gradient */}
      <div
        className={cn(
          'pointer-events-none absolute inset-0 bg-gradient-to-r',
          bgGradients[tier]
        )}
        aria-hidden="true"
      />

      {/* Content */}
      <div className="relative">
        {/* Header */}
        <div className="flex items-start justify-between">
          <TierBadge tier={tier} />
          <span className="text-xs font-medium text-slate-500">
            {metadata.priority}
          </span>
        </div>

        {/* Title */}
        <h3 className="mt-3 text-lg font-semibold text-slate-900">
          {metadata.title}
        </h3>

        {/* Metrics */}
        <div className="mt-3 flex items-baseline gap-3">
          <span className="text-3xl font-bold tracking-tight text-slate-900">
            {formatNumber(caseCount)}
          </span>
          <span className="text-sm text-slate-500">
            {caseCount === 1 ? 'case' : 'cases'}
          </span>
          {countChange !== undefined && countChange !== 0 && (
            <span
              className={cn(
                'inline-flex items-center gap-0.5 text-xs font-medium',
                countChange > 0 ? 'text-emerald-600' : 'text-red-600'
              )}
            >
              {countChange > 0 ? (
                <ArrowUp className="h-3 w-3" />
              ) : (
                <ArrowDown className="h-3 w-3" />
              )}
              {Math.abs(countChange)}
            </span>
          )}
        </div>

        {/* Value */}
        <p className="mt-1 text-sm font-medium text-slate-600">
          {formatCurrency(totalValue)} total
        </p>

        {/* Description */}
        <p className="mt-3 text-xs leading-relaxed text-slate-500">
          {metadata.description}
        </p>

        {/* Action hint */}
        {onClick && (
          <div className="mt-4 flex items-center gap-1 text-xs font-semibold text-blue-600">
            <span>{metadata.actionHint}</span>
            <ChevronRight className="h-3.5 w-3.5" />
          </div>
        )}
      </div>
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// TIER SUMMARY ROW (Compact horizontal layout)
// ═══════════════════════════════════════════════════════════════════════════

interface TierSummaryRowProps {
  tiers: Array<{
    tier: Tier;
    caseCount: number;
    totalValue: number;
  }>;
  onTierClick?: (tier: Tier) => void;
  loading?: boolean;
  className?: string;
}

export const TierSummaryRow: FC<TierSummaryRowProps> = ({
  tiers,
  onTierClick,
  loading = false,
  className,
}) => {
  const total = tiers.reduce((sum, t) => sum + t.caseCount, 0);

  if (loading) {
    return (
      <div className={cn('flex gap-4', className)}>
        {[1, 2, 3].map((i) => (
          <div key={i} className="flex-1">
            <Skeleton className="h-20 w-full rounded-xl" />
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className={cn('grid grid-cols-3 gap-4', className)}>
      {tiers.map((tierData) => {
        const percentage = total > 0 ? (tierData.caseCount / total) * 100 : 0;

        return (
          <button
            key={tierData.tier}
            type="button"
            onClick={() => onTierClick?.(tierData.tier)}
            className={cn(
              'group relative overflow-hidden rounded-xl border border-slate-200 bg-white p-4 text-left transition-all',
              'hover:border-slate-300 hover:shadow-md',
              'focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2'
            )}
          >
            {/* Progress bar background */}
            <div
              className={cn(
                'absolute bottom-0 left-0 h-1 transition-all',
                tierData.tier === 'A' && 'bg-emerald-500',
                tierData.tier === 'B' && 'bg-amber-500',
                tierData.tier === 'C' && 'bg-slate-400'
              )}
              style={{ width: `${percentage}%` }}
              aria-hidden="true"
            />

            <div className="flex items-center justify-between">
              <TierBadge tier={tierData.tier} size="sm" />
              <span className="text-xs text-slate-500">
                {percentage.toFixed(0)}%
              </span>
            </div>

            <p className="mt-2 text-2xl font-bold text-slate-900">
              {formatNumber(tierData.caseCount)}
            </p>

            <p className="mt-0.5 text-xs text-slate-500">
              {formatCurrency(tierData.totalValue)}
            </p>
          </button>
        );
      })}
    </div>
  );
};

export default TierCard;
