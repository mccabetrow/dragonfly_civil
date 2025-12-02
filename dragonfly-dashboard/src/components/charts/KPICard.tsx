/**
 * KPICard - Tremor-style KPI metric card
 *
 * Displays a key performance indicator with:
 * - Title and value
 * - Optional trend indicator (up/down/neutral)
 * - Optional subtitle for context
 * - Skeleton loading state
 */
import { type FC, type ReactNode } from 'react';
import { TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { cn } from '../../lib/design-tokens';

export interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  trend?: {
    value: number;
    label?: string;
  };
  icon?: ReactNode;
  loading?: boolean;
  className?: string;
  valueClassName?: string;
}

export const KPICard: FC<KPICardProps> = ({
  title,
  value,
  subtitle,
  trend,
  icon,
  loading = false,
  className,
  valueClassName,
}) => {
  const trendDirection = trend
    ? trend.value > 0
      ? 'up'
      : trend.value < 0
        ? 'down'
        : 'neutral'
    : null;

  const trendColorClass =
    trendDirection === 'up'
      ? 'text-emerald-600 bg-emerald-50'
      : trendDirection === 'down'
        ? 'text-rose-600 bg-rose-50'
        : 'text-slate-500 bg-slate-50';

  const TrendIcon =
    trendDirection === 'up'
      ? TrendingUp
      : trendDirection === 'down'
        ? TrendingDown
        : Minus;

  return (
    <div
      className={cn(
        'relative overflow-hidden rounded-xl border border-slate-200 bg-white p-5 shadow-sm transition-shadow hover:shadow-md',
        className
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex items-center gap-2">
          {icon && (
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-indigo-50 text-indigo-600">
              {icon}
            </div>
          )}
          <p className="text-sm font-medium text-slate-500">{title}</p>
        </div>

        {trend && (
          <div
            className={cn(
              'flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold',
              trendColorClass
            )}
          >
            <TrendIcon className="h-3 w-3" />
            <span>{Math.abs(trend.value).toFixed(1)}%</span>
          </div>
        )}
      </div>

      {/* Value */}
      <div className="mt-3">
        {loading ? (
          <div className="h-9 w-32 animate-pulse rounded-lg bg-slate-100" />
        ) : (
          <p
            className={cn(
              'font-mono text-3xl font-semibold tracking-tight text-slate-900',
              valueClassName
            )}
          >
            {typeof value === 'number' ? value.toLocaleString() : value}
          </p>
        )}
      </div>

      {/* Subtitle / Trend Label */}
      {(subtitle || trend?.label) && (
        <p className="mt-1.5 text-sm text-slate-500">
          {trend?.label ?? subtitle}
        </p>
      )}

      {/* Decorative gradient border on left */}
      <div className="absolute left-0 top-0 h-full w-1 bg-gradient-to-b from-indigo-500 to-violet-500" />
    </div>
  );
};

export default KPICard;
