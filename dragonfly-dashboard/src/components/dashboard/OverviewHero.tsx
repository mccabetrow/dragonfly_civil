/**
 * OverviewHero - Command center hero strip
 *
 * Shows at-a-glance snapshot:
 * - Total judgments with week-over-week trend
 * - 7-day mini trend chart (SVG)
 * - Refresh state integration
 */

import { type FC, useMemo } from 'react';
import { TrendingUp, TrendingDown, Minus, RefreshCw } from 'lucide-react';
import { cn } from '../../lib/design-tokens';
import { formatCurrency, formatNumber } from '../../lib/utils/formatters';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface OverviewHeroProps {
  /** Total active cases */
  totalCases: number;
  /** Total exposure amount */
  totalExposure: number;
  /** Week-over-week case change (percentage) */
  weekOverWeekChange?: number;
  /** 7-day trend data (most recent last) */
  trendData?: number[];
  /** Whether data is refreshing */
  isRefreshing?: boolean;
  /** Last updated timestamp */
  lastUpdated?: Date | null;
  /** Handler for refresh */
  onRefresh?: () => void;
  /** Loading state */
  loading?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// MINI CHART (SVG)
// ═══════════════════════════════════════════════════════════════════════════

interface MiniChartProps {
  data: number[];
  className?: string;
}

const MiniChart: FC<MiniChartProps> = ({ data, className }) => {
  const { path, areaPath } = useMemo(() => {
    if (!data || data.length < 2) {
      return { path: '', areaPath: '' };
    }

    const width = 120;
    const height = 40;
    const padding = 2;

    const max = Math.max(...data);
    const min = Math.min(...data);
    const range = max - min || 1;

    const points = data.map((value, index) => {
      const x = padding + (index / (data.length - 1)) * (width - padding * 2);
      const y = padding + (1 - (value - min) / range) * (height - padding * 2);
      return { x, y };
    });

    const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'} ${p.x} ${p.y}`).join(' ');
    const area = `${linePath} L ${points[points.length - 1].x} ${height} L ${points[0].x} ${height} Z`;

    return { path: linePath, areaPath: area };
  }, [data]);

  if (!data || data.length < 2) {
    return (
      <div className={cn('flex h-10 w-[120px] items-center justify-center text-xs text-slate-400', className)}>
        No trend data
      </div>
    );
  }

  const isPositive = data[data.length - 1] >= data[0];

  return (
    <svg 
      viewBox="0 0 120 40" 
      className={cn('h-10 w-[120px]', className)}
      aria-label="7-day trend chart"
    >
      {/* Area fill */}
      <path
        d={areaPath}
        fill={isPositive ? 'rgb(16 185 129 / 0.15)' : 'rgb(239 68 68 / 0.15)'}
      />
      {/* Line */}
      <path
        d={path}
        fill="none"
        stroke={isPositive ? 'rgb(16 185 129)' : 'rgb(239 68 68)'}
        strokeWidth={2}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* End dot */}
      <circle
        cx={120 - 2}
        cy={2 + (1 - (data[data.length - 1] - Math.min(...data)) / (Math.max(...data) - Math.min(...data) || 1)) * 36}
        r={3}
        fill={isPositive ? 'rgb(16 185 129)' : 'rgb(239 68 68)'}
      />
    </svg>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// HERO COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

export const OverviewHero: FC<OverviewHeroProps> = ({
  totalCases,
  totalExposure,
  weekOverWeekChange,
  trendData,
  isRefreshing = false,
  lastUpdated,
  onRefresh,
  loading = false,
}) => {
  // Determine trend direction
  const trend = weekOverWeekChange === undefined 
    ? 'neutral' 
    : weekOverWeekChange > 0 
      ? 'up' 
      : weekOverWeekChange < 0 
        ? 'down' 
        : 'neutral';

  const TrendIcon = trend === 'up' ? TrendingUp : trend === 'down' ? TrendingDown : Minus;

  return (
    <div 
      className={cn(
        'relative overflow-hidden rounded-2xl bg-gradient-to-br from-slate-900 via-slate-800 to-slate-900 p-6 shadow-lg',
        isRefreshing && 'animate-pulse'
      )}
    >
      {/* Background pattern */}
      <div className="pointer-events-none absolute inset-0 opacity-5">
        <svg className="h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
          <defs>
            <pattern id="hero-grid" width="10" height="10" patternUnits="userSpaceOnUse">
              <path d="M 10 0 L 0 0 0 10" fill="none" stroke="white" strokeWidth="0.5" />
            </pattern>
          </defs>
          <rect width="100" height="100" fill="url(#hero-grid)" />
        </svg>
      </div>

      <div className="relative flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        {/* Left: Snapshot metrics */}
        <div className="flex-1">
          <div className="flex items-center gap-2">
            <h2 className="text-sm font-medium text-slate-400">Today's Snapshot</h2>
            {isRefreshing && (
              <RefreshCw className="h-3.5 w-3.5 animate-spin text-slate-500" />
            )}
          </div>

          <div className="mt-3 flex items-baseline gap-4">
            {/* Total Cases */}
            <div>
              <p className={cn(
                'text-4xl font-bold tracking-tight text-white transition-opacity',
                loading && 'opacity-50'
              )}>
                {loading ? '—' : formatNumber(totalCases)}
              </p>
              <p className="mt-0.5 text-xs text-slate-400">Active judgments</p>
            </div>

            {/* Trend badge */}
            {weekOverWeekChange !== undefined && !loading && (
              <div 
                className={cn(
                  'flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium',
                  trend === 'up' && 'bg-emerald-500/20 text-emerald-400',
                  trend === 'down' && 'bg-red-500/20 text-red-400',
                  trend === 'neutral' && 'bg-slate-700 text-slate-400'
                )}
              >
                <TrendIcon className="h-3 w-3" />
                <span>
                  {weekOverWeekChange > 0 ? '+' : ''}
                  {weekOverWeekChange.toFixed(1)}% WoW
                </span>
              </div>
            )}
          </div>

          {/* Exposure */}
          <div className="mt-4 flex items-center gap-4 border-t border-slate-700/50 pt-4">
            <div>
              <p className={cn(
                'text-xl font-semibold text-white transition-opacity',
                loading && 'opacity-50'
              )}>
                {loading ? '—' : formatCurrency(totalExposure)}
              </p>
              <p className="text-xs text-slate-400">Total exposure</p>
            </div>
          </div>
        </div>

        {/* Right: Mini chart + refresh */}
        <div className="flex flex-col items-end gap-3">
          {/* 7-day trend chart */}
          <div className="rounded-xl bg-slate-800/50 p-3">
            <p className="mb-2 text-[10px] font-medium uppercase tracking-wider text-slate-500">
              7-Day Trend
            </p>
            {loading ? (
              <div className="h-10 w-[120px] animate-pulse rounded bg-slate-700" />
            ) : (
              <MiniChart data={trendData ?? []} />
            )}
          </div>

          {/* Refresh + timestamp */}
          <div className="flex items-center gap-2">
            {lastUpdated && (
              <span className="text-[11px] text-slate-500">
                {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </span>
            )}
            {onRefresh && (
              <button
                type="button"
                onClick={onRefresh}
                disabled={isRefreshing}
                className="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-700 hover:text-white disabled:opacity-50"
                aria-label="Refresh data"
              >
                <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default OverviewHero;
