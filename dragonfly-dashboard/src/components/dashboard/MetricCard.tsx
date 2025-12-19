/**
 * MetricCard - Dashboard metric display with trend indicators
 *
 * Enterprise-grade metric card with:
 * - Clear visual hierarchy
 * - Trend indicators with color coding
 * - Loading skeleton support
 * - Tooltip explanations
 * - Responsive sizing
 * - Actionable error states
 * - Freshness timestamps
 */

import { type FC, type ReactNode } from 'react';
import { TrendingUp, TrendingDown, Minus, HelpCircle, RefreshCw, AlertTriangle, AlertCircle, Info } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { Card } from '../ui/Card';
import { Skeleton } from '../ui/Skeleton';
import { FreshnessBadge } from '../ui/FreshnessBadge';
import { formatNumber, formatCurrency, formatPercent } from '../../lib/utils/formatters';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface MetricCardErrorInfo {
  /** Error title (e.g., "API Unreachable") */
  title: string;
  /** Actionable hint */
  actionHint?: string;
  /** Severity level */
  severity?: 'error' | 'warning' | 'info';
  /** Error code for debugging */
  code?: string | null;
}

export interface MetricCardProps {
  /** Label shown above the value */
  label: string;

  /** Main value to display */
  value: number | string | null | undefined;

  /** Optional previous value for trend calculation */
  previousValue?: number;

  /** How to format the value */
  format?: 'number' | 'currency' | 'percent' | 'none';

  /** Icon to display (optional) */
  icon?: ReactNode;

  /** Additional description or context */
  description?: string;

  /** Tooltip text explaining the metric */
  tooltip?: string;

  /** Whether data is loading */
  loading?: boolean;

  /** Card size variant */
  size?: 'sm' | 'md' | 'lg';

  /** Custom trend label (overrides automatic calculation) */
  trendLabel?: string;

  /** Force trend direction (overrides automatic calculation) */
  trendDirection?: 'up' | 'down' | 'neutral';

  /** Whether "up" is good (default true for most metrics) */
  upIsGood?: boolean;

  /** Additional CSS classes */
  className?: string;

  /** Click handler */
  onClick?: () => void;

  /** ISO timestamp for freshness display (e.g., "Updated 2m ago") */
  lastUpdated?: string | Date | null;

  /** Actionable error info (replaces generic "Unable to load") */
  errorInfo?: MetricCardErrorInfo | null;

  /** Retry callback when error is shown */
  onRetry?: () => void | Promise<void>;
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function formatValue(
  value: number | string | null | undefined,
  format: MetricCardProps['format']
): string {
  if (value === null || value === undefined) return '—';
  if (typeof value === 'string') return value;

  switch (format) {
    case 'currency':
      return formatCurrency(value);
    case 'percent':
      return formatPercent(value);
    case 'number':
      return formatNumber(value);
    case 'none':
    default:
      return String(value);
  }
}

function calculateTrend(
  current: number | string | null | undefined,
  previous: number | undefined
): { direction: 'up' | 'down' | 'neutral'; percentage: number | null } {
  if (typeof current !== 'number' || !previous || previous === 0) {
    return { direction: 'neutral', percentage: null };
  }

  const change = ((current - previous) / previous) * 100;

  if (Math.abs(change) < 0.5) {
    return { direction: 'neutral', percentage: 0 };
  }

  return {
    direction: change > 0 ? 'up' : 'down',
    percentage: Math.abs(change),
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// SIZE CONFIGS
// ═══════════════════════════════════════════════════════════════════════════

const sizeConfig = {
  sm: {
    padding: 'p-4',
    labelSize: 'text-xs',
    valueSize: 'text-xl',
    iconSize: 'h-4 w-4',
    trendSize: 'text-[10px]',
  },
  md: {
    padding: 'p-5',
    labelSize: 'text-sm',
    valueSize: 'text-2xl',
    iconSize: 'h-5 w-5',
    trendSize: 'text-xs',
  },
  lg: {
    padding: 'p-6',
    labelSize: 'text-sm',
    valueSize: 'text-3xl',
    iconSize: 'h-6 w-6',
    trendSize: 'text-sm',
  },
};

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const MetricCard: FC<MetricCardProps> = ({
  label,
  value,
  previousValue,
  format = 'number',
  icon,
  description,
  tooltip,
  loading = false,
  size = 'md',
  trendLabel,
  trendDirection,
  upIsGood = true,
  className,
  onClick,
  lastUpdated,
  errorInfo,
  onRetry,
}) => {
  const config = sizeConfig[size];

  // Calculate or use provided trend
  const calculatedTrend = calculateTrend(value, previousValue);
  const direction = trendDirection ?? calculatedTrend.direction;
  const percentage = calculatedTrend.percentage;

  // Determine trend color
  const getTrendColor = () => {
    if (direction === 'neutral') return 'text-slate-500';
    const isPositive = direction === 'up' ? upIsGood : !upIsGood;
    return isPositive ? 'text-emerald-600' : 'text-red-600';
  };

  const TrendIcon =
    direction === 'up' ? TrendingUp : direction === 'down' ? TrendingDown : Minus;

  // Loading state
  if (loading) {
    return (
      <Card className={cn(config.padding, className)}>
        <div className="space-y-3">
          <Skeleton className="h-4 w-24" />
          <Skeleton className="h-8 w-32" />
          <Skeleton className="h-3 w-16" />
        </div>
      </Card>
    );
  }

  // Error state - actionable feedback
  if (errorInfo) {
    const severityStyles = {
      error: {
        border: 'border-rose-200',
        bg: 'bg-rose-50/50',
        iconBg: 'bg-rose-100',
        iconColor: 'text-rose-600',
        titleColor: 'text-rose-900',
        textColor: 'text-rose-700',
        buttonClass: 'border-rose-200 text-rose-700 hover:bg-rose-100',
        Icon: AlertCircle,
      },
      warning: {
        border: 'border-amber-200',
        bg: 'bg-amber-50/50',
        iconBg: 'bg-amber-100',
        iconColor: 'text-amber-600',
        titleColor: 'text-amber-900',
        textColor: 'text-amber-700',
        buttonClass: 'border-amber-200 text-amber-700 hover:bg-amber-100',
        Icon: AlertTriangle,
      },
      info: {
        border: 'border-sky-200',
        bg: 'bg-sky-50/50',
        iconBg: 'bg-sky-100',
        iconColor: 'text-sky-600',
        titleColor: 'text-sky-900',
        textColor: 'text-sky-700',
        buttonClass: 'border-sky-200 text-sky-700 hover:bg-sky-100',
        Icon: Info,
      },
    };

    const severity = errorInfo.severity ?? 'error';
    const styles = severityStyles[severity];
    const ErrorIcon = styles.Icon;

    return (
      <Card className={cn(config.padding, styles.border, styles.bg, className)}>
        <div className="flex items-start gap-3">
          <span className={cn('rounded-lg p-1.5', styles.iconBg, styles.iconColor)}>
            <ErrorIcon className="h-4 w-4" aria-hidden="true" />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2">
              <p className={cn('text-xs font-semibold uppercase tracking-wide', styles.titleColor)}>
                {label}
              </p>
              {errorInfo.code && (
                <code className="rounded bg-white/50 px-1 py-0.5 font-mono text-[9px] opacity-60">
                  {errorInfo.code}
                </code>
              )}
            </div>
            <p className={cn('mt-1 text-sm font-medium', styles.titleColor)}>
              {errorInfo.title}
            </p>
            {errorInfo.actionHint && (
              <p className={cn('mt-0.5 text-xs', styles.textColor)}>
                {errorInfo.actionHint}
              </p>
            )}
            {onRetry && (
              <button
                type="button"
                onClick={() => onRetry()}
                className={cn(
                  'mt-2 inline-flex items-center gap-1.5 rounded-full border bg-white/80 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-wide transition',
                  styles.buttonClass
                )}
              >
                <RefreshCw className="h-3 w-3" aria-hidden="true" />
                Retry
              </button>
            )}
          </div>
        </div>
      </Card>
    );
  }

  return (
    <Card
      variant={onClick ? 'interactive' : 'default'}
      className={cn(config.padding, className)}
      onClick={onClick}
    >
      {/* Header: Label + Icon */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-1.5">
          <span
            className={cn(
              config.labelSize,
              'font-medium uppercase tracking-wide text-slate-500'
            )}
          >
            {label}
          </span>
          {tooltip && (
            <button
              type="button"
              className="text-slate-400 transition hover:text-slate-600"
              title={tooltip}
              aria-label={`Info about ${label}`}
            >
              <HelpCircle className="h-3.5 w-3.5" />
            </button>
          )}
        </div>
        {icon && (
          <span
            className={cn(
              'flex items-center justify-center rounded-lg bg-slate-100 p-2 text-slate-500'
            )}
          >
            {icon}
          </span>
        )}
      </div>

      {/* Value */}
      <p
        className={cn(
          config.valueSize,
          'mt-2 font-bold tracking-tight text-slate-900'
        )}
      >
        {formatValue(value, format)}
      </p>

      {/* Trend or Description */}
      <div className="mt-2 flex items-center justify-between">
        {(trendLabel || percentage !== null) && (
          <span
            className={cn(
              config.trendSize,
              'flex items-center gap-1 font-medium',
              getTrendColor()
            )}
          >
            <TrendIcon className="h-3.5 w-3.5" />
            {trendLabel ?? (percentage !== null ? `${percentage.toFixed(1)}%` : '')}
          </span>
        )}
        {description && (
          <span className={cn(config.trendSize, 'text-slate-500')}>
            {description}
          </span>
        )}
      </div>

      {/* Freshness timestamp */}
      {lastUpdated && (
        <div className="mt-3 border-t border-slate-100 pt-2">
          <FreshnessBadge timestamp={lastUpdated} variant="compact" />
        </div>
      )}
    </Card>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// METRIC CARD GRID
// ═══════════════════════════════════════════════════════════════════════════

interface MetricCardGridProps {
  children: ReactNode;
  columns?: 2 | 3 | 4;
  className?: string;
}

export const MetricCardGrid: FC<MetricCardGridProps> = ({
  children,
  columns = 3,
  className,
}) => {
  const gridCols = {
    2: 'grid-cols-1 sm:grid-cols-2',
    3: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-3',
    4: 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4',
  };

  return (
    <div className={cn('grid gap-4', gridCols[columns], className)}>
      {children}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// QUICK STAT (Compact Inline Metric)
// ═══════════════════════════════════════════════════════════════════════════

interface QuickStatProps {
  label: string;
  value: string | number;
  icon?: ReactNode;
  tone?: 'neutral' | 'success' | 'warning' | 'error';
  className?: string;
}

export const QuickStat: FC<QuickStatProps> = ({
  label,
  value,
  icon,
  tone = 'neutral',
  className,
}) => {
  const toneStyles = {
    neutral: 'bg-slate-100 text-slate-700',
    success: 'bg-emerald-50 text-emerald-700',
    warning: 'bg-amber-50 text-amber-700',
    error: 'bg-red-50 text-red-700',
  };

  return (
    <div
      className={cn(
        'inline-flex items-center gap-2 rounded-lg px-3 py-2',
        toneStyles[tone],
        className
      )}
    >
      {icon && <span className="opacity-70">{icon}</span>}
      <span className="text-xs font-medium">{label}:</span>
      <span className="text-sm font-semibold">{value}</span>
    </div>
  );
};

export default MetricCard;
