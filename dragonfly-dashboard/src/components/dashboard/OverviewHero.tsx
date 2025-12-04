/**
 * OverviewHero - Command center hero strip with Tremor components
 *
 * Shows at-a-glance snapshot:
 * - Total judgments with week-over-week trend using Tremor BadgeDelta
 * - 7-day sparkline using Tremor SparkAreaChart
 * - Category breakdown bar using Tremor CategoryBar
 * - Recovery progress using Tremor ProgressBar
 *
 * Dragonfly Theme:
 * - Deep blue (#0f172a) primary
 * - Emerald accents (#10b981)
 * - Steel gray backgrounds (#f1f5f9)
 */

import { type FC, useMemo } from 'react';
import {
  Card,
  Metric,
  Text,
  Flex,
  BadgeDelta,
  SparkAreaChart,
  CategoryBar,
  Legend,
  ProgressBar,
} from '@tremor/react';
import { RefreshCw, Zap, Shield, TrendingUp } from 'lucide-react';
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
  /** Tier distribution (A, B, C counts) */
  tierDistribution?: { tierA: number; tierB: number; tierC: number };
  /** Recovery rate (0-100) */
  recoveryRate?: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// SPARKLINE DATA TRANSFORM
// ═══════════════════════════════════════════════════════════════════════════

interface SparklinePoint {
  day: string;
  value: number;
}

function transformTrendData(data: number[] | undefined): SparklinePoint[] {
  if (!data || data.length === 0) {
    return [];
  }
  return data.map((value, index) => ({
    day: `Day ${index + 1}`,
    value,
  }));
}

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
  tierDistribution,
  recoveryRate,
}) => {
  // Transform trend data for Tremor SparkAreaChart
  const sparklineData = useMemo(() => transformTrendData(trendData), [trendData]);

  // Determine delta type for trend badge
  const deltaType = weekOverWeekChange === undefined
    ? 'unchanged'
    : weekOverWeekChange > 0
      ? 'increase'
      : weekOverWeekChange < 0
        ? 'decrease'
        : 'unchanged';

  // Calculate tier percentages for CategoryBar
  const tierTotal = tierDistribution
    ? tierDistribution.tierA + tierDistribution.tierB + tierDistribution.tierC
    : 0;
  
  const tierPercentages = tierTotal > 0 && tierDistribution
    ? [
        Math.round((tierDistribution.tierA / tierTotal) * 100),
        Math.round((tierDistribution.tierB / tierTotal) * 100),
        Math.round((tierDistribution.tierC / tierTotal) * 100),
      ]
    : [33, 34, 33];

  return (
    <Card 
      className={cn(
        'relative overflow-hidden bg-gradient-to-br from-[#0f172a] via-[#1e293b] to-[#0f172a]',
        isRefreshing && 'animate-pulse'
      )}
      decoration="left"
      decorationColor="emerald"
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

      <div className="relative">
        {/* Header row */}
        <Flex justifyContent="between" alignItems="start" className="mb-4">
          <div className="flex items-center gap-2">
            <Zap className="h-5 w-5 text-emerald-400" />
            <Text className="text-slate-400 font-medium">
              Command Center — HEDGE FUND MODE v0.1
            </Text>
            {isRefreshing && (
              <RefreshCw className="h-3.5 w-3.5 animate-spin text-slate-500" />
            )}
          </div>
          
          {/* Refresh + timestamp */}
          <div className="flex items-center gap-3">
            {lastUpdated && (
              <Text className="text-slate-500 text-xs">
                {lastUpdated.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
              </Text>
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
        </Flex>

        {/* Main metrics grid */}
        <div className="grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
          {/* Active Judgments */}
          <div className="space-y-2">
            <Flex justifyContent="start" alignItems="baseline" className="gap-3">
              <Metric className="text-white font-bold">
                {loading ? '—' : formatNumber(totalCases)}
              </Metric>
              {weekOverWeekChange !== undefined && !loading && (
                <BadgeDelta
                  deltaType={deltaType}
                  size="sm"
                >
                  {weekOverWeekChange > 0 ? '+' : ''}
                  {weekOverWeekChange.toFixed(1)}%
                </BadgeDelta>
              )}
            </Flex>
            <Text className="text-slate-400">Active Judgments</Text>
          </div>

          {/* Total Exposure */}
          <div className="space-y-2">
            <Metric className="text-white font-bold">
              {loading ? '—' : formatCurrency(totalExposure)}
            </Metric>
            <Text className="text-slate-400">Total Exposure</Text>
          </div>

          {/* 7-Day Trend Sparkline */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <TrendingUp className="h-4 w-4 text-emerald-400" />
              <Text className="text-slate-400">7-Day Trend</Text>
            </div>
            {loading ? (
              <div className="h-10 w-full animate-pulse rounded bg-slate-700" />
            ) : sparklineData.length > 1 ? (
              <SparkAreaChart
                data={sparklineData}
                categories={['value']}
                index="day"
                colors={['emerald']}
                className="h-10 w-full"
                curveType="monotone"
              />
            ) : (
              <Text className="text-slate-500 text-xs">No trend data</Text>
            )}
          </div>

          {/* Recovery Rate Progress */}
          <div className="space-y-2">
            <Flex justifyContent="between" alignItems="center">
              <div className="flex items-center gap-2">
                <Shield className="h-4 w-4 text-emerald-400" />
                <Text className="text-slate-400">Recovery Rate</Text>
              </div>
              <Text className="text-white font-semibold">
                {recoveryRate !== undefined ? `${recoveryRate.toFixed(1)}%` : '—'}
              </Text>
            </Flex>
            <ProgressBar
              value={recoveryRate ?? 0}
              color="emerald"
              className="mt-2"
            />
          </div>
        </div>

        {/* Tier Distribution Bar */}
        {tierDistribution && tierTotal > 0 && (
          <div className="mt-6 pt-4 border-t border-slate-700/50">
            <Flex justifyContent="between" alignItems="center" className="mb-2">
              <Text className="text-slate-400">Portfolio Tier Distribution</Text>
              <Legend
                categories={['Tier A (Strategic)', 'Tier B (Active)', 'Tier C (Monitor)']}
                colors={['emerald', 'blue', 'slate']}
                className="[&_span]:text-slate-400 [&_span]:text-xs"
              />
            </Flex>
            <CategoryBar
              values={tierPercentages}
              colors={['emerald', 'blue', 'slate']}
              markerValue={tierPercentages[0]}
              className="mt-2"
            />
            <Flex justifyContent="between" className="mt-2">
              <Text className="text-slate-500 text-xs">
                {tierDistribution.tierA} cases ({tierPercentages[0]}%)
              </Text>
              <Text className="text-slate-500 text-xs">
                {tierDistribution.tierB} cases ({tierPercentages[1]}%)
              </Text>
              <Text className="text-slate-500 text-xs">
                {tierDistribution.tierC} cases ({tierPercentages[2]}%)
              </Text>
            </Flex>
          </div>
        )}
      </div>
    </Card>
  );
};

export default OverviewHero;
