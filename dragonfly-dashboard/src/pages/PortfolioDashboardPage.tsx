/**
 * PortfolioDashboardPage - CEO/Investor Overview
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Primary dashboard for executive portfolio overview featuring:
 * - Top Section: 4 large KPI cards (Portfolio Value, Served, Collection Rate, Actionable)
 * - Middle Section: 90-day trend chart + High-Value Pipeline table
 * - Right Rail: Alerts feed
 *
 * Design: Premium dark fintech theme with cyan accents
 */
import React, { useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  DollarSign,
  FileCheck,
  TrendingUp,
  Target,
  AlertCircle,
  Bell,
  CheckCircle,
  XCircle,
  Info,
  Clock,
  ChevronRight,
  Sparkles,
} from 'lucide-react';
import { AreaChart, Badge } from '@tremor/react';
import { usePortfolioStats } from '../hooks/usePortfolioStats';
import { useRecentAlerts, type SystemAlert, type AlertSeverity } from '../hooks/useRecentAlerts';
import { usePriorityCases } from '../hooks/usePriorityCases';
import { TierBadge } from '../components/primitives';
import { useRefreshBus } from '../context/RefreshContext';
import { cn } from '../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
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

const formatPercentage = (value: number): string => `${value.toFixed(1)}%`;

const getRelativeTime = (timestamp: string): string => {
  const now = Date.now();
  const then = new Date(timestamp).getTime();
  const diffMs = now - then;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);

  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
};

// ═══════════════════════════════════════════════════════════════════════════
// KPI CARD COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface KPIMetricCardProps {
  label: string;
  value: string;
  subtitle?: string;
  icon: React.ReactNode;
  trend?: { value: number; label: string };
  loading?: boolean;
  accentColor: 'cyan' | 'emerald' | 'gold' | 'violet';
  sparklineData?: number[];
}

const accentClasses = {
  cyan: {
    iconBg: 'bg-cyan-500/10 dark:bg-cyan-400/10',
    iconText: 'text-cyan-600 dark:text-cyan-400',
    glow: 'shadow-glow-cyan',
    border: 'border-cyan-500/20',
  },
  emerald: {
    iconBg: 'bg-emerald-500/10 dark:bg-emerald-400/10',
    iconText: 'text-emerald-600 dark:text-emerald-400',
    glow: 'shadow-glow-emerald',
    border: 'border-emerald-500/20',
  },
  gold: {
    iconBg: 'bg-amber-500/10 dark:bg-amber-400/10',
    iconText: 'text-amber-600 dark:text-amber-400',
    glow: 'shadow-glow-gold',
    border: 'border-amber-500/20',
  },
  violet: {
    iconBg: 'bg-violet-500/10 dark:bg-violet-400/10',
    iconText: 'text-violet-600 dark:text-violet-400',
    glow: '',
    border: 'border-violet-500/20',
  },
};

const KPIMetricCard: React.FC<KPIMetricCardProps> = ({
  label,
  value,
  subtitle,
  icon,
  trend,
  loading,
  accentColor,
  sparklineData,
}) => {
  const accent = accentClasses[accentColor];

  if (loading) {
    return (
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative overflow-hidden rounded-2xl border border-slate-700/50 bg-dragonfly-navy-800/60 p-6 backdrop-blur-sm"
      >
        <div className="space-y-4">
          <div className="h-4 w-24 animate-pulse rounded bg-slate-700/50" />
          <div className="h-10 w-40 animate-pulse rounded-lg bg-slate-700/50" />
          <div className="h-3 w-32 animate-pulse rounded bg-slate-700/30" />
        </div>
      </motion.div>
    );
  }

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      whileHover={{ y: -2, scale: 1.01 }}
      transition={{ type: 'spring', stiffness: 300, damping: 20 }}
      className={cn(
        'group relative overflow-hidden rounded-2xl border bg-dragonfly-navy-800/60 p-6 backdrop-blur-sm transition-all duration-300',
        'hover:border-cyan-500/30 hover:bg-dragonfly-navy-800/80',
        accent.border
      )}
    >
      {/* Subtle gradient overlay */}
      <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-white/[0.02] to-transparent" />

      <div className="relative flex items-start justify-between gap-4">
        <div className="flex-1">
          <p className="text-xs font-semibold uppercase tracking-[0.2em] text-slate-400">
            {label}
          </p>
          <p className="mt-3 text-4xl font-bold tracking-tight text-white">
            {value}
          </p>
          {subtitle && (
            <p className="mt-1.5 text-sm text-slate-400">{subtitle}</p>
          )}
          {trend && (
            <div className="mt-3 inline-flex items-center gap-1.5">
              <span
                className={cn(
                  'inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold',
                  trend.value >= 0
                    ? 'bg-emerald-500/10 text-emerald-400'
                    : 'bg-rose-500/10 text-rose-400'
                )}
              >
                <TrendingUp
                  className={cn('h-3 w-3', trend.value < 0 && 'rotate-180')}
                />
                {trend.value >= 0 ? '+' : ''}
                {trend.value.toFixed(1)}%
              </span>
              <span className="text-xs text-slate-500">{trend.label}</span>
            </div>
          )}
        </div>

        {/* Icon */}
        <div className={cn('rounded-xl p-3', accent.iconBg)}>
          <div className={accent.iconText}>{icon}</div>
        </div>
      </div>

      {/* Mini sparkline */}
      {sparklineData && sparklineData.length > 0 && (
        <div className="mt-4 h-12 opacity-60">
          <MiniSparkline data={sparklineData} color={accentColor} />
        </div>
      )}
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// MINI SPARKLINE
// ═══════════════════════════════════════════════════════════════════════════

interface MiniSparklineProps {
  data: number[];
  color: 'cyan' | 'emerald' | 'gold' | 'violet';
}

const sparklineColors = {
  cyan: 'stroke-cyan-400',
  emerald: 'stroke-emerald-400',
  gold: 'stroke-amber-400',
  violet: 'stroke-violet-400',
};

const MiniSparkline: React.FC<MiniSparklineProps> = ({ data, color }) => {
  const max = Math.max(...data, 1);
  const min = Math.min(...data, 0);
  const range = max - min || 1;
  const width = 100;
  const height = 40;
  const padding = 4;

  const points = data
    .map((val, i) => {
      const x = padding + (i / (data.length - 1)) * (width - 2 * padding);
      const y = height - padding - ((val - min) / range) * (height - 2 * padding);
      return `${x},${y}`;
    })
    .join(' ');

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="h-full w-full">
      <polyline
        points={points}
        fill="none"
        className={cn('stroke-2', sparklineColors[color])}
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// ALERT ITEM COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const severityConfig: Record<AlertSeverity, { icon: React.ReactNode; bg: string; border: string }> = {
  info: {
    icon: <Info className="h-4 w-4" />,
    bg: 'bg-blue-500/10',
    border: 'border-blue-500/30',
  },
  success: {
    icon: <CheckCircle className="h-4 w-4" />,
    bg: 'bg-emerald-500/10',
    border: 'border-emerald-500/30',
  },
  warning: {
    icon: <AlertCircle className="h-4 w-4" />,
    bg: 'bg-amber-500/10',
    border: 'border-amber-500/30',
  },
  error: {
    icon: <XCircle className="h-4 w-4" />,
    bg: 'bg-rose-500/10',
    border: 'border-rose-500/30',
  },
};

const severityTextColors: Record<AlertSeverity, string> = {
  info: 'text-blue-400',
  success: 'text-emerald-400',
  warning: 'text-amber-400',
  error: 'text-rose-400',
};

interface AlertItemProps {
  alert: SystemAlert;
  onMarkRead: (id: string) => void;
}

const AlertItem: React.FC<AlertItemProps> = ({ alert, onMarkRead }) => {
  const config = severityConfig[alert.severity];

  return (
    <motion.div
      initial={{ opacity: 0, x: 20 }}
      animate={{ opacity: 1, x: 0 }}
      className={cn(
        'group relative rounded-xl border p-4 transition-all duration-200',
        'bg-dragonfly-navy-800/40 hover:bg-dragonfly-navy-800/60',
        config.border,
        !alert.read && 'border-l-2'
      )}
      onClick={() => !alert.read && onMarkRead(alert.id)}
    >
      <div className="flex items-start gap-3">
        <div className={cn('rounded-lg p-2', config.bg, severityTextColors[alert.severity])}>
          {config.icon}
        </div>
        <div className="flex-1 min-w-0">
          <p className={cn('text-sm font-medium', alert.read ? 'text-slate-300' : 'text-white')}>
            {alert.title}
          </p>
          <p className="mt-1 text-xs text-slate-400 line-clamp-2">{alert.message}</p>
          <div className="mt-2 flex items-center gap-2 text-xs text-slate-500">
            <Clock className="h-3 w-3" />
            {getRelativeTime(alert.timestamp)}
          </div>
        </div>
        {!alert.read && (
          <div className="h-2 w-2 rounded-full bg-cyan-400 animate-pulse" />
        )}
      </div>
    </motion.div>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// DEMO TREND DATA
// ═══════════════════════════════════════════════════════════════════════════

const generateTrendData = () => {
  const data = [];
  const baseValue = 7_500_000;
  let currentValue = baseValue;

  for (let i = 90; i >= 0; i--) {
    const date = new Date();
    date.setDate(date.getDate() - i);
    const dateStr = date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });

    // Simulate organic growth with some variance
    const dailyChange = (Math.random() - 0.35) * 100_000;
    currentValue = Math.max(baseValue * 0.9, currentValue + dailyChange);

    data.push({
      date: dateStr,
      'Portfolio Value': Math.round(currentValue),
      'Collected': Math.round(currentValue * 0.18 * (Math.random() * 0.3 + 0.85)),
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
  const { alerts, loading: alertsLoading, unreadCount, markAsRead, refetch: refetchAlerts } = useRecentAlerts(8);
  const { state: priorityCasesState } = usePriorityCases(5);
  const { triggerRefresh, isRefreshing } = useRefreshBus();

  // Generate 90-day trend data
  const trendData = useMemo(() => generateTrendData(), []);

  // Sparkline data for collection rate (simulated)
  const collectionSparkline = useMemo(
    () => Array.from({ length: 12 }, () => 14 + Math.random() * 8),
    []
  );

  // High-value pipeline cases
  const pipelineCases = useMemo(() => {
    if (priorityCasesState.status !== 'ready' || !priorityCasesState.data) {
      return [];
    }
    return priorityCasesState.data.slice(0, 5);
  }, [priorityCasesState]);

  // Demo stats fallback
  const stats = portfolioStats ?? {
    totalAum: 8_450_123,
    actionableLiquidity: 4_250_000,
    totalJudgments: 847,
    actionableCount: 312,
    offersOutstanding: 23,
    pipelineValue: 2_150_000,
    tierAllocation: [],
    topCounties: [],
  };

  const servedLast30 = 45; // Demo value
  const collectionRate = 18.5; // Demo value

  return (
    <div className="min-h-screen bg-dragonfly-navy-900">
      {/* Page Header */}
      <header className="border-b border-slate-700/50 bg-dragonfly-navy-900/80 backdrop-blur-sm sticky top-0 z-10">
        <div className="mx-auto max-w-[1600px] px-6 py-5">
          <div className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-3">
                <div className="rounded-xl bg-gradient-to-br from-cyan-500 to-blue-600 p-2">
                  <Sparkles className="h-5 w-5 text-white" />
                </div>
                <div>
                  <h1 className="text-2xl font-bold text-white">Portfolio Dashboard</h1>
                  <p className="text-sm text-slate-400">Real-time executive overview</p>
                </div>
              </div>
            </div>
            <div className="flex items-center gap-4">
              <button
                onClick={() => {
                  triggerRefresh();
                  refetchStats();
                  refetchAlerts();
                }}
                disabled={isRefreshing}
                className={cn(
                  'inline-flex items-center gap-2 rounded-lg px-4 py-2 text-sm font-medium transition-all',
                  'bg-cyan-500/10 text-cyan-400 hover:bg-cyan-500/20',
                  isRefreshing && 'opacity-50 cursor-not-allowed'
                )}
              >
                <TrendingUp className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
                {isRefreshing ? 'Refreshing...' : 'Refresh'}
              </button>
              <div className="relative">
                <button className="relative rounded-lg bg-dragonfly-navy-800 p-2.5 text-slate-400 hover:text-white transition-colors">
                  <Bell className="h-5 w-5" />
                  {unreadCount > 0 && (
                    <span className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-cyan-500 text-[10px] font-bold text-white">
                      {unreadCount}
                    </span>
                  )}
                </button>
              </div>
            </div>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1600px] px-6 py-8">
        {/* Top Section: KPI Cards */}
        <section className="mb-8">
          <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
            <KPIMetricCard
              label="Total Portfolio Value"
              value={formatLargeCurrency(stats.totalAum)}
              subtitle={`${stats.totalJudgments.toLocaleString()} total judgments`}
              icon={<DollarSign className="h-6 w-6" />}
              trend={{ value: 12.4, label: 'vs last month' }}
              loading={statsLoading}
              accentColor="cyan"
            />
            <KPIMetricCard
              label="Judgments Served (30d)"
              value={servedLast30.toString()}
              subtitle="Successfully served"
              icon={<FileCheck className="h-6 w-6" />}
              trend={{ value: 8.2, label: 'vs prior 30d' }}
              loading={statsLoading}
              accentColor="emerald"
            />
            <KPIMetricCard
              label="Collection Rate (YTD)"
              value={formatPercentage(collectionRate)}
              subtitle="Of actionable portfolio"
              icon={<TrendingUp className="h-6 w-6" />}
              trend={{ value: 2.3, label: 'vs last year' }}
              loading={statsLoading}
              accentColor="gold"
              sparklineData={collectionSparkline}
            />
            <KPIMetricCard
              label="Actionable Value"
              value={formatLargeCurrency(stats.actionableLiquidity)}
              subtitle={`${stats.actionableCount.toLocaleString()} high-score cases`}
              icon={<Target className="h-6 w-6" />}
              trend={{ value: 5.7, label: 'vs last month' }}
              loading={statsLoading}
              accentColor="violet"
            />
          </div>
        </section>

        {/* Middle Section: Chart + Table + Alerts */}
        <section className="grid grid-cols-1 gap-6 lg:grid-cols-12">
          {/* Left Column: Trend Chart */}
          <div className="lg:col-span-5">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.1 }}
              className="h-full rounded-2xl border border-slate-700/50 bg-dragonfly-navy-800/60 p-6 backdrop-blur-sm"
            >
              <div className="mb-6">
                <h2 className="text-lg font-semibold text-white">Portfolio Value Trend</h2>
                <p className="text-sm text-slate-400">90-day rolling performance</p>
              </div>
              <AreaChart
                data={trendData}
                index="date"
                categories={['Portfolio Value']}
                colors={['cyan']}
                valueFormatter={(value) => formatCurrency(value)}
                className="h-72"
                showAnimation
                showLegend={false}
                showGridLines={false}
                curveType="monotone"
                yAxisWidth={70}
              />
            </motion.div>
          </div>

          {/* Center Column: Pipeline Table */}
          <div className="lg:col-span-4">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.2 }}
              className="h-full rounded-2xl border border-slate-700/50 bg-dragonfly-navy-800/60 p-6 backdrop-blur-sm"
            >
              <div className="mb-6 flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-white">High-Value Pipeline</h2>
                  <p className="text-sm text-slate-400">Top 5 by amount</p>
                </div>
                <button
                  onClick={() => navigate('/cases')}
                  className="inline-flex items-center gap-1 text-sm text-cyan-400 hover:text-cyan-300 transition-colors"
                >
                  View all <ChevronRight className="h-4 w-4" />
                </button>
              </div>

              <div className="space-y-3">
                {priorityCasesState.status === 'loading' ? (
                  Array.from({ length: 5 }).map((_, i) => (
                    <div key={i} className="animate-pulse rounded-lg bg-slate-700/30 p-4">
                      <div className="h-4 w-3/4 rounded bg-slate-700/50" />
                      <div className="mt-2 h-3 w-1/2 rounded bg-slate-700/30" />
                    </div>
                  ))
                ) : pipelineCases.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-700 p-8 text-center">
                    <Target className="mx-auto h-8 w-8 text-slate-600" />
                    <p className="mt-2 text-sm text-slate-500">No pipeline cases</p>
                  </div>
                ) : (
                  pipelineCases.map((c, idx) => (
                    <motion.div
                      key={c.caseId}
                      initial={{ opacity: 0, x: -10 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={{ delay: 0.05 * idx }}
                      onClick={() => navigate(`/cases/${c.caseId}`)}
                      className="group cursor-pointer rounded-lg border border-slate-700/50 bg-dragonfly-navy-900/40 p-4 transition-all hover:border-cyan-500/30 hover:bg-dragonfly-navy-800/60"
                    >
                      <div className="flex items-center justify-between">
                        <div className="min-w-0 flex-1">
                          <p className="truncate text-sm font-medium text-white group-hover:text-cyan-400 transition-colors">
                            {c.defendantName ?? c.caseNumber}
                          </p>
                          <p className="mt-0.5 text-xs text-slate-500">{c.caseNumber}</p>
                        </div>
                        <div className="flex items-center gap-3 flex-shrink-0">
                          <span className="text-sm font-semibold text-emerald-400">
                            {formatCurrency(c.judgmentAmount ?? 0)}
                          </span>
                          <TierBadge tier={c.tier} size="sm" />
                        </div>
                      </div>
                      <div className="mt-2 flex items-center gap-2">
                        <Badge
                          size="xs"
                          color={
                            c.enrichmentStatus?.toLowerCase().includes('complete')
                              ? 'emerald'
                              : c.enrichmentStatus?.toLowerCase().includes('pending')
                                ? 'amber'
                                : 'slate'
                          }
                        >
                          {c.enrichmentStatus ?? 'Pending'}
                        </Badge>
                      </div>
                    </motion.div>
                  ))
                )}
              </div>
            </motion.div>
          </div>

          {/* Right Rail: Alerts */}
          <div className="lg:col-span-3">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.3 }}
              className="h-full rounded-2xl border border-slate-700/50 bg-dragonfly-navy-800/60 p-6 backdrop-blur-sm"
            >
              <div className="mb-6 flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Bell className="h-5 w-5 text-cyan-400" />
                  <h2 className="text-lg font-semibold text-white">Alerts</h2>
                  {unreadCount > 0 && (
                    <span className="rounded-full bg-cyan-500/20 px-2 py-0.5 text-xs font-medium text-cyan-400">
                      {unreadCount} new
                    </span>
                  )}
                </div>
              </div>

              <div className="space-y-3 max-h-[500px] overflow-y-auto pr-1 custom-scrollbar">
                {alertsLoading ? (
                  Array.from({ length: 4 }).map((_, i) => (
                    <div key={i} className="animate-pulse rounded-lg bg-slate-700/30 p-4">
                      <div className="h-4 w-3/4 rounded bg-slate-700/50" />
                      <div className="mt-2 h-3 w-full rounded bg-slate-700/30" />
                    </div>
                  ))
                ) : alerts.length === 0 ? (
                  <div className="rounded-lg border border-dashed border-slate-700 p-8 text-center">
                    <CheckCircle className="mx-auto h-8 w-8 text-emerald-500/50" />
                    <p className="mt-2 text-sm text-slate-500">All caught up!</p>
                  </div>
                ) : (
                  alerts.map((alert) => (
                    <AlertItem key={alert.id} alert={alert} onMarkRead={markAsRead} />
                  ))
                )}
              </div>
            </motion.div>
          </div>
        </section>
      </main>
    </div>
  );
};

export default PortfolioDashboardPage;
