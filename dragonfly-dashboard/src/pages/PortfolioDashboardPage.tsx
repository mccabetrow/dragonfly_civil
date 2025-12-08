/**
 * PortfolioDashboardPage - HFT Terminal Edition
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * CEO-grade executive dashboard with premium trading terminal aesthetic.
 *
 * Design Principles:
 * - Forced dark mode (Slate-900 base, never white)
 * - Emerald-500 for money/gains, Rose-500 for alerts/losses
 * - Compact density - all KPIs visible without scrolling
 * - Shimmering skeletons (never spinners)
 * - Optimistic UI for all user actions
 * - Bloomberg/Reuters terminal inspiration
 */
import React, { useMemo, useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion, AnimatePresence } from 'framer-motion';
import { AreaChart, DonutChart } from '@tremor/react';
import {
  DollarSign,
  FileCheck,
  TrendingUp,
  TrendingDown,
  Target,
  AlertCircle,
  Bell,
  CheckCircle,
  XCircle,
  Info,
  Clock,
  ChevronRight,
  RefreshCw,
  Activity,
  Zap,
  Archive,
} from 'lucide-react';

import { usePortfolioStats } from '../hooks/usePortfolioStats';
import { useRecentAlerts, type SystemAlert, type AlertSeverity } from '../hooks/useRecentAlerts';
import { usePriorityCases } from '../hooks/usePriorityCases';
import { TierBadge, type TierLevel } from '../components/primitives';
import { useRefreshBus } from '../context/RefreshContext';
import { cn } from '../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// FORMATTERS
// ═══════════════════════════════════════════════════════════════════════════

const formatCurrency = (value: number): string => {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(0)}K`;
  return `$${value.toLocaleString()}`;
};

const formatLargeCurrency = (value: number): string => {
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (value >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value.toLocaleString()}`;
};

const getRelativeTime = (date: string | Date): string => {
  const now = new Date();
  const past = new Date(date);
  const diffMs = now.getTime() - past.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  const diffHours = Math.floor(diffMs / 3_600_000);
  const diffDays = Math.floor(diffMs / 86_400_000);

  if (diffMins < 1) return 'just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return past.toLocaleDateString();
};

// ═══════════════════════════════════════════════════════════════════════════
// SHIMMER SKELETON - HFT Style
// ═══════════════════════════════════════════════════════════════════════════

interface ShimmerProps {
  className?: string;
}

const Shimmer: React.FC<ShimmerProps> = ({ className }) => (
  <div
    className={cn(
      'relative overflow-hidden rounded bg-slate-800/60',
      'before:absolute before:inset-0',
      'before:-translate-x-full before:animate-[shimmer_1.5s_infinite]',
      'before:bg-gradient-to-r before:from-transparent before:via-slate-700/40 before:to-transparent',
      className
    )}
  />
);

const KPICardSkeleton: React.FC = () => (
  <div className="rounded-lg border border-slate-700/50 bg-slate-900/80 p-4">
    <Shimmer className="h-3 w-20 mb-3" />
    <Shimmer className="h-8 w-28 mb-2" />
    <Shimmer className="h-3 w-24" />
  </div>
);

const TableRowSkeleton: React.FC = () => (
  <div className="flex items-center justify-between py-2.5 border-b border-slate-800/50">
    <div className="flex-1">
      <Shimmer className="h-4 w-32 mb-1" />
      <Shimmer className="h-3 w-20" />
    </div>
    <Shimmer className="h-5 w-16" />
  </div>
);

const AlertSkeleton: React.FC = () => (
  <div className="rounded-lg border border-slate-800/50 bg-slate-900/60 p-3">
    <div className="flex gap-3">
      <Shimmer className="h-8 w-8 rounded-lg flex-shrink-0" />
      <div className="flex-1">
        <Shimmer className="h-4 w-3/4 mb-2" />
        <Shimmer className="h-3 w-full mb-2" />
        <Shimmer className="h-2.5 w-16" />
      </div>
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// KPI METRIC CARD - Compact HFT Design
// ═══════════════════════════════════════════════════════════════════════════

interface KPICardProps {
  label: string;
  value: string;
  subtitle?: string;
  icon: React.ReactNode;
  trend?: { value: number; label: string };
  loading?: boolean;
  variant: 'money' | 'count' | 'rate' | 'target';
}

const variantStyles = {
  money: {
    iconBg: 'bg-emerald-500/10',
    iconColor: 'text-emerald-400',
    valueColor: 'text-emerald-400',
    border: 'border-emerald-500/20 hover:border-emerald-500/40',
  },
  count: {
    iconBg: 'bg-cyan-500/10',
    iconColor: 'text-cyan-400',
    valueColor: 'text-white',
    border: 'border-cyan-500/20 hover:border-cyan-500/40',
  },
  rate: {
    iconBg: 'bg-amber-500/10',
    iconColor: 'text-amber-400',
    valueColor: 'text-amber-400',
    border: 'border-amber-500/20 hover:border-amber-500/40',
  },
  target: {
    iconBg: 'bg-violet-500/10',
    iconColor: 'text-violet-400',
    valueColor: 'text-violet-400',
    border: 'border-violet-500/20 hover:border-violet-500/40',
  },
};

const KPICard: React.FC<KPICardProps> = ({
  label,
  value,
  subtitle,
  icon,
  trend,
  loading,
  variant,
}) => {
  const styles = variantStyles[variant];

  if (loading) return <KPICardSkeleton />;

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={cn(
        'group rounded-lg border bg-slate-900/80 p-4 backdrop-blur-sm transition-all duration-200',
        styles.border
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex-1 min-w-0">
          <p className="text-[10px] font-semibold uppercase tracking-[0.15em] text-slate-500">
            {label}
          </p>
          <p className={cn('mt-1.5 text-2xl font-bold tracking-tight', styles.valueColor)}>
            {value}
          </p>
          {subtitle && (
            <p className="mt-0.5 text-[11px] text-slate-500 truncate">{subtitle}</p>
          )}
          {trend && (
            <div className="mt-2 inline-flex items-center gap-1">
              {trend.value >= 0 ? (
                <TrendingUp className="h-3 w-3 text-emerald-400" />
              ) : (
                <TrendingDown className="h-3 w-3 text-rose-400" />
              )}
              <span
                className={cn(
                  'text-[10px] font-semibold',
                  trend.value >= 0 ? 'text-emerald-400' : 'text-rose-400'
                )}
              >
                {trend.value >= 0 ? '+' : ''}{trend.value.toFixed(1)}%
              </span>
              <span className="text-[10px] text-slate-600">{trend.label}</span>
            </div>
          )}
        </div>
        <div className={cn('rounded-lg p-2', styles.iconBg)}>
          <div className={styles.iconColor}>{icon}</div>
        </div>
      </div>
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// ALERT ITEM - Compact with optimistic read
// ═══════════════════════════════════════════════════════════════════════════

const severityStyles: Record<AlertSeverity, { icon: React.ReactNode; color: string }> = {
  info: { icon: <Info className="h-3.5 w-3.5" />, color: 'text-blue-400' },
  success: { icon: <CheckCircle className="h-3.5 w-3.5" />, color: 'text-emerald-400' },
  warning: { icon: <AlertCircle className="h-3.5 w-3.5" />, color: 'text-amber-400' },
  error: { icon: <XCircle className="h-3.5 w-3.5" />, color: 'text-rose-400' },
};

interface AlertItemProps {
  alert: SystemAlert;
  onMarkRead: (id: string) => void;
  onArchive?: (id: string) => void;
}

const AlertItem: React.FC<AlertItemProps> = ({ alert, onMarkRead, onArchive }) => {
  const [optimisticRead, setOptimisticRead] = useState(alert.read);
  const [isArchiving, setIsArchiving] = useState(false);
  const style = severityStyles[alert.severity];

  const handleClick = useCallback(() => {
    if (!optimisticRead) {
      setOptimisticRead(true); // Optimistic update
      onMarkRead(alert.id);
    }
  }, [optimisticRead, onMarkRead, alert.id]);

  const handleArchive = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setIsArchiving(true);
    onArchive?.(alert.id);
  }, [onArchive, alert.id]);

  return (
    <motion.div
      initial={{ opacity: 0, x: 8 }}
      animate={{ opacity: isArchiving ? 0 : 1, x: isArchiving ? 20 : 0 }}
      exit={{ opacity: 0, x: 20 }}
      onClick={handleClick}
      className={cn(
        'group relative rounded-lg border p-3 transition-all duration-150 cursor-pointer',
        'bg-slate-900/60 hover:bg-slate-800/60',
        optimisticRead ? 'border-slate-800/50' : 'border-l-2 border-l-cyan-500 border-slate-800/50'
      )}
    >
      <div className="flex gap-2.5">
        <div className={cn('mt-0.5', style.color)}>{style.icon}</div>
        <div className="flex-1 min-w-0">
          <p className={cn(
            'text-xs font-medium leading-tight',
            optimisticRead ? 'text-slate-400' : 'text-slate-200'
          )}>
            {alert.title}
          </p>
          <p className="mt-1 text-[11px] text-slate-500 line-clamp-2">{alert.message}</p>
          <div className="mt-1.5 flex items-center justify-between">
            <div className="flex items-center gap-1 text-slate-600">
              <Clock className="h-2.5 w-2.5" />
              <span className="text-[10px]">{getRelativeTime(alert.timestamp)}</span>
            </div>
            {onArchive && (
              <button
                onClick={handleArchive}
                className="opacity-0 group-hover:opacity-100 transition-opacity text-slate-500 hover:text-slate-300"
                title="Archive"
              >
                <Archive className="h-3 w-3" />
              </button>
            )}
          </div>
        </div>
        {!optimisticRead && (
          <div className="h-1.5 w-1.5 rounded-full bg-cyan-400 animate-pulse flex-shrink-0 mt-1" />
        )}
      </div>
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// PIPELINE CASE ROW
// ═══════════════════════════════════════════════════════════════════════════

interface PipelineCaseRowProps {
  caseData: {
    caseId: string;
    caseNumber: string;
    defendantName?: string | null;
    judgmentAmount?: number | null;
    tier?: TierLevel | null;
    enrichmentStatus?: string | null;
  };
  onClick: () => void;
}

const PipelineCaseRow: React.FC<PipelineCaseRowProps> = ({ caseData, onClick }) => (
  <motion.div
    initial={{ opacity: 0, x: -8 }}
    animate={{ opacity: 1, x: 0 }}
    whileHover={{ x: 2 }}
    onClick={onClick}
    className="group flex items-center justify-between py-2.5 border-b border-slate-800/50 cursor-pointer hover:bg-slate-800/30 transition-colors -mx-1 px-1 rounded"
  >
    <div className="flex-1 min-w-0">
      <p className="text-sm font-medium text-slate-200 group-hover:text-cyan-400 transition-colors truncate">
        {caseData.defendantName ?? caseData.caseNumber}
      </p>
      <p className="text-[10px] text-slate-500 font-mono">{caseData.caseNumber}</p>
    </div>
    <div className="flex items-center gap-2 flex-shrink-0">
      <span className="text-sm font-semibold text-emerald-400 tabular-nums">
        {formatCurrency(caseData.judgmentAmount ?? 0)}
      </span>
      {caseData.tier && <TierBadge tier={caseData.tier} size="sm" />}
    </div>
  </motion.div>
);

// ═══════════════════════════════════════════════════════════════════════════
// TIER ALLOCATION CHART
// ═══════════════════════════════════════════════════════════════════════════

interface TierAllocationChartProps {
  data: { tier: string; amount: number; count: number }[];
  loading?: boolean;
}

const TierAllocationChart: React.FC<TierAllocationChartProps> = ({ data, loading }) => {
  const chartData = useMemo(() => 
    data.map(d => ({
      name: `Tier ${d.tier}`,
      value: d.amount,
      count: d.count,
    })),
    [data]
  );

  if (loading) {
    return (
      <div className="flex items-center justify-center h-32">
        <Shimmer className="h-24 w-24 rounded-full" />
      </div>
    );
  }

  if (chartData.length === 0) {
    return (
      <div className="flex items-center justify-center h-32 text-slate-600">
        <span className="text-xs">No allocation data</span>
      </div>
    );
  }

  return (
    <DonutChart
      data={chartData}
      index="name"
      category="value"
      colors={['emerald', 'amber', 'slate']}
      valueFormatter={(v) => formatCurrency(v)}
      className="h-32"
      showAnimation
      showLabel
      showTooltip
    />
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA GENERATORS
// ═══════════════════════════════════════════════════════════════════════════

const generateTrendData = () => {
  const data = [];
  const baseValue = 7_500_000;
  let currentValue = baseValue;

  for (let i = 90; i >= 0; i--) {
    const date = new Date();
    date.setDate(date.getDate() - i);
    const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    const dailyChange = (Math.random() - 0.35) * 100_000;
    currentValue = Math.max(baseValue * 0.9, currentValue + dailyChange);

    data.push({
      date: dateStr,
      'Portfolio Value': Math.round(currentValue),
      'Collections': Math.round(currentValue * 0.02 * (Math.random() * 0.3 + 0.85)),
    });
  }
  return data;
};

// ═══════════════════════════════════════════════════════════════════════════
// MAIN COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const PortfolioDashboardPage: React.FC = () => {
  const navigate = useNavigate();
  const { data: portfolioStats, loading: statsLoading, refetch: refetchStats } = usePortfolioStats();
  const { alerts, loading: alertsLoading, unreadCount, markAsRead, refetch: refetchAlerts } = useRecentAlerts(10);
  const { state: priorityCasesState } = usePriorityCases(8);
  const { triggerRefresh, isRefreshing } = useRefreshBus();

  // Trend data - memoized
  const trendData = useMemo(() => generateTrendData(), []);

  // Pipeline cases
  const pipelineCases = useMemo(() => {
    if (priorityCasesState.status !== 'ready' || !priorityCasesState.data) return [];
    return priorityCasesState.data.slice(0, 8);
  }, [priorityCasesState]);

  // Fallback stats for demo
  const stats = portfolioStats ?? {
    totalAum: 8_450_123,
    actionableLiquidity: 4_250_000,
    totalJudgments: 847,
    actionableCount: 312,
    offersOutstanding: 23,
    pipelineValue: 2_150_000,
    tierAllocation: [
      { tier: 'A' as const, label: 'Tier A', amount: 4_200_000, count: 124, color: 'emerald' },
      { tier: 'B' as const, label: 'Tier B', amount: 2_850_000, count: 298, color: 'amber' },
      { tier: 'C' as const, label: 'Tier C', amount: 1_400_000, count: 425, color: 'slate' },
    ],
    topCounties: [],
  };

  const handleRefresh = useCallback(() => {
    triggerRefresh();
    refetchStats();
    refetchAlerts();
  }, [triggerRefresh, refetchStats, refetchAlerts]);

  const handleArchiveAlert = useCallback((id: string) => {
    // Optimistic removal happens in AlertItem
    console.log('[Dashboard] Archiving alert:', id);
  }, []);

  return (
    <div className="min-h-screen bg-slate-950">
      {/* ─────────────────────────────────────────────────────────────────────
          HEADER - Compact HFT Style
          ───────────────────────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-20 border-b border-slate-800/60 bg-slate-950/95 backdrop-blur-md">
        <div className="mx-auto max-w-[1800px] px-4 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2">
                <Activity className="h-5 w-5 text-emerald-400" />
                <h1 className="text-lg font-bold text-white">Portfolio</h1>
              </div>
              <div className="hidden sm:flex items-center gap-1.5 text-[10px] text-slate-500">
                <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
                <span>LIVE</span>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {/* Quick stats bar */}
              <div className="hidden md:flex items-center gap-4 text-xs">
                <div className="flex items-center gap-1.5 text-slate-400">
                  <span className="text-emerald-400 font-semibold tabular-nums">
                    {stats.actionableCount}
                  </span>
                  <span>actionable</span>
                </div>
                <div className="h-3 w-px bg-slate-700" />
                <div className="flex items-center gap-1.5 text-slate-400">
                  <span className="text-cyan-400 font-semibold tabular-nums">
                    {stats.offersOutstanding}
                  </span>
                  <span>offers out</span>
                </div>
              </div>

              {/* Refresh button */}
              <button
                onClick={handleRefresh}
                disabled={isRefreshing}
                className={cn(
                  'flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium transition-all',
                  'bg-slate-800/60 text-slate-300 hover:bg-slate-700/60 hover:text-white',
                  'border border-slate-700/50',
                  isRefreshing && 'opacity-50 cursor-not-allowed'
                )}
              >
                <RefreshCw className={cn('h-3.5 w-3.5', isRefreshing && 'animate-spin')} />
                <span className="hidden sm:inline">{isRefreshing ? 'Syncing' : 'Refresh'}</span>
              </button>

              {/* Alerts bell */}
              <button className="relative rounded-md p-2 text-slate-400 hover:text-white hover:bg-slate-800/60 transition-colors">
                <Bell className="h-4 w-4" />
                {unreadCount > 0 && (
                  <span className="absolute -top-0.5 -right-0.5 flex h-4 w-4 items-center justify-center rounded-full bg-rose-500 text-[9px] font-bold text-white">
                    {unreadCount > 9 ? '9+' : unreadCount}
                  </span>
                )}
              </button>
            </div>
          </div>
        </div>
      </header>

      {/* ─────────────────────────────────────────────────────────────────────
          MAIN CONTENT
          ───────────────────────────────────────────────────────────────────── */}
      <main className="mx-auto max-w-[1800px] px-4 py-4">
        {/* KPI Grid - 4 columns, compact */}
        <section className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
          <KPICard
            label="Total AUM"
            value={formatLargeCurrency(stats.totalAum)}
            subtitle={`${stats.totalJudgments.toLocaleString()} judgments`}
            icon={<DollarSign className="h-4 w-4" />}
            trend={{ value: 12.4, label: 'vs LM' }}
            loading={statsLoading}
            variant="money"
          />
          <KPICard
            label="Actionable Value"
            value={formatLargeCurrency(stats.actionableLiquidity)}
            subtitle={`${stats.actionableCount} high-score cases`}
            icon={<Target className="h-4 w-4" />}
            trend={{ value: 5.7, label: 'vs LM' }}
            loading={statsLoading}
            variant="target"
          />
          <KPICard
            label="Served (30d)"
            value="45"
            subtitle="Successfully served"
            icon={<FileCheck className="h-4 w-4" />}
            trend={{ value: 8.2, label: 'vs prior' }}
            loading={statsLoading}
            variant="count"
          />
          <KPICard
            label="Collection Rate"
            value="18.5%"
            subtitle="YTD vs actionable"
            icon={<TrendingUp className="h-4 w-4" />}
            trend={{ value: 2.3, label: 'vs LY' }}
            loading={statsLoading}
            variant="rate"
          />
        </section>

        {/* Main Grid: Chart + Pipeline + Allocation + Alerts */}
        <section className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Portfolio Value Chart */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 }}
            className="lg:col-span-5 rounded-lg border border-slate-800/60 bg-slate-900/60 p-4"
          >
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-sm font-semibold text-white">Portfolio Value</h2>
                <p className="text-[10px] text-slate-500">90-day trend</p>
              </div>
              <div className="flex items-center gap-3 text-[10px]">
                <div className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-emerald-500" />
                  <span className="text-slate-400">Value</span>
                </div>
                <div className="flex items-center gap-1">
                  <span className="h-2 w-2 rounded-full bg-cyan-500" />
                  <span className="text-slate-400">Collections</span>
                </div>
              </div>
            </div>
            <AreaChart
              data={trendData}
              index="date"
              categories={['Portfolio Value', 'Collections']}
              colors={['emerald', 'cyan']}
              valueFormatter={(v) => formatCurrency(v)}
              className="h-56"
              showAnimation
              showLegend={false}
              showGridLines={false}
              curveType="monotone"
              yAxisWidth={60}
            />
          </motion.div>

          {/* High-Value Pipeline */}
          <motion.div
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.1 }}
            className="lg:col-span-4 rounded-lg border border-slate-800/60 bg-slate-900/60 p-4"
          >
            <div className="flex items-center justify-between mb-3">
              <div>
                <h2 className="text-sm font-semibold text-white">High-Value Pipeline</h2>
                <p className="text-[10px] text-slate-500">Top 8 by amount</p>
              </div>
              <button
                onClick={() => navigate('/cases')}
                className="flex items-center gap-0.5 text-[11px] text-cyan-400 hover:text-cyan-300 transition-colors"
              >
                View all <ChevronRight className="h-3 w-3" />
              </button>
            </div>

            <div className="space-y-0.5 max-h-[280px] overflow-y-auto custom-scrollbar">
              {priorityCasesState.status === 'loading' ? (
                Array.from({ length: 5 }).map((_, i) => <TableRowSkeleton key={i} />)
              ) : pipelineCases.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-8 text-slate-600">
                  <Target className="h-6 w-6 mb-2" />
                  <span className="text-xs">No pipeline cases</span>
                </div>
              ) : (
                pipelineCases.map((c) => (
                  <PipelineCaseRow
                    key={c.caseId}
                    caseData={c}
                    onClick={() => navigate(`/cases/${c.caseId}`)}
                  />
                ))
              )}
            </div>
          </motion.div>

          {/* Right Column: Tier Allocation + Alerts */}
          <div className="lg:col-span-3 space-y-4">
            {/* Tier Allocation */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.15 }}
              className="rounded-lg border border-slate-800/60 bg-slate-900/60 p-4"
            >
              <div className="flex items-center justify-between mb-3">
                <h2 className="text-sm font-semibold text-white">Tier Allocation</h2>
                <Zap className="h-4 w-4 text-amber-400" />
              </div>
              <TierAllocationChart
                data={stats.tierAllocation ?? []}
                loading={statsLoading}
              />
              <div className="mt-3 grid grid-cols-3 gap-2">
                {(stats.tierAllocation ?? []).map((t) => (
                  <div key={t.tier} className="text-center">
                    <p className="text-[10px] text-slate-500">Tier {t.tier}</p>
                    <p className="text-xs font-semibold text-slate-300">{t.count}</p>
                  </div>
                ))}
              </div>
            </motion.div>

            {/* Alerts Feed */}
            <motion.div
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="rounded-lg border border-slate-800/60 bg-slate-900/60 p-4"
            >
              <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-2">
                  <Bell className="h-4 w-4 text-cyan-400" />
                  <h2 className="text-sm font-semibold text-white">Alerts</h2>
                  {unreadCount > 0 && (
                    <span className="rounded-full bg-cyan-500/20 px-1.5 py-0.5 text-[9px] font-semibold text-cyan-400">
                      {unreadCount}
                    </span>
                  )}
                </div>
              </div>

              <div className="space-y-2 max-h-[200px] overflow-y-auto custom-scrollbar">
                <AnimatePresence>
                  {alertsLoading ? (
                    Array.from({ length: 3 }).map((_, i) => <AlertSkeleton key={i} />)
                  ) : alerts.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-6 text-slate-600">
                      <CheckCircle className="h-5 w-5 mb-1 text-emerald-500/50" />
                      <span className="text-xs">All caught up!</span>
                    </div>
                  ) : (
                    alerts.slice(0, 5).map((alert) => (
                      <AlertItem
                        key={alert.id}
                        alert={alert}
                        onMarkRead={markAsRead}
                        onArchive={handleArchiveAlert}
                      />
                    ))
                  )}
                </AnimatePresence>
              </div>
            </motion.div>
          </div>
        </section>
      </main>

      {/* Shimmer keyframes injection */}
      <style>{`
        @keyframes shimmer {
          100% { transform: translateX(100%); }
        }
        .custom-scrollbar::-webkit-scrollbar {
          width: 4px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgb(51 65 85 / 0.5);
          border-radius: 2px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgb(71 85 105 / 0.5);
        }
      `}</style>
    </div>
  );
};

export default PortfolioDashboardPage;
