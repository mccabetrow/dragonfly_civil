/**
 * EnforcementEnginePage
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Real-time monitoring dashboard for the Enforcement Engine Worker.
 * Financial terminal style with dark mode, auto-refresh polling.
 *
 * Features:
 *   - KPI strip: plans created, packets generated, worker status
 *   - Queue health indicator with status pills
 *   - 30-second auto-refresh with manual refresh button
 *   - Skeleton loading states
 *   - Error recovery with retry button
 *
 * Route: /enforcement/engine
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ArrowUpRight,
  CheckCircle2,
  Clock,
  FileText,
  Loader2,
  RefreshCw,
  Server,
  Target,
  XCircle,
  Zap,
} from 'lucide-react';
import {
  Button,
} from '../../components/primitives';
import {
  useEnforcementEngineData,
  computeEnforcementEngineKPIs,
} from '../../hooks/useEnforcementEngineData';
import { useRefreshBus } from '../../context/RefreshContext';
import { cn } from '../../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// SKELETON COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

const KPICardSkeleton: React.FC = () => (
  <div className="rounded-xl border border-slate-700/50 bg-slate-800/50 p-5 backdrop-blur-sm">
    <div className="flex items-center justify-between mb-3">
      <div className="h-3 w-24 animate-pulse rounded bg-slate-700" />
      <div className="h-8 w-8 animate-pulse rounded-lg bg-slate-700" />
    </div>
    <div className="h-8 w-20 animate-pulse rounded bg-slate-700 mb-2" />
    <div className="h-3 w-16 animate-pulse rounded bg-slate-700" />
  </div>
);

const PageSkeleton: React.FC = () => (
  <div className="space-y-6">
    {/* KPI Strip */}
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
      {Array.from({ length: 4 }).map((_, i) => (
        <KPICardSkeleton key={i} />
      ))}
    </div>

    {/* Secondary metrics */}
    <div className="grid gap-4 lg:grid-cols-3">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="rounded-xl border border-slate-700/50 bg-slate-800/50 p-5"
        >
          <div className="h-4 w-32 animate-pulse rounded bg-slate-700 mb-4" />
          <div className="space-y-3">
            {Array.from({ length: 3 }).map((__, j) => (
              <div key={j} className="flex justify-between">
                <div className="h-3 w-20 animate-pulse rounded bg-slate-700" />
                <div className="h-3 w-12 animate-pulse rounded bg-slate-700" />
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// KPI CARD COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface KPICardProps {
  title: string;
  value: number | string;
  subtitle?: string;
  trend?: number;
  icon: React.ElementType;
  iconColor?: string;
  accentColor?: string;
}

const KPICard: React.FC<KPICardProps> = ({
  title,
  value,
  subtitle,
  trend,
  icon: Icon,
  iconColor = 'text-blue-400',
  accentColor = 'from-blue-500/20 to-transparent',
}) => (
  <motion.div
    initial={{ opacity: 0, y: 10 }}
    animate={{ opacity: 1, y: 0 }}
    transition={{ duration: 0.3 }}
    className={cn(
      'relative overflow-hidden rounded-xl border border-slate-700/50',
      'bg-gradient-to-br from-slate-800/80 to-slate-900/80',
      'backdrop-blur-sm p-5'
    )}
  >
    {/* Gradient accent */}
    <div
      className={cn(
        'absolute inset-0 bg-gradient-to-br opacity-50',
        accentColor
      )}
    />

    <div className="relative z-10">
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs font-medium uppercase tracking-wider text-slate-400">
          {title}
        </span>
        <div
          className={cn(
            'flex items-center justify-center w-8 h-8 rounded-lg',
            'bg-slate-700/50'
          )}
        >
          <Icon className={cn('w-4 h-4', iconColor)} />
        </div>
      </div>

      <div className="flex items-baseline gap-2">
        <span className="text-3xl font-bold text-white tabular-nums">
          {typeof value === 'number' ? value.toLocaleString() : value}
        </span>
        {trend !== undefined && trend !== 0 && (
          <span
            className={cn(
              'flex items-center text-xs font-medium',
              trend > 0 ? 'text-emerald-400' : 'text-rose-400'
            )}
          >
            <ArrowUpRight
              className={cn('w-3 h-3 mr-0.5', trend < 0 && 'rotate-90')}
            />
            {Math.abs(trend)}%
          </span>
        )}
      </div>

      {subtitle && (
        <span className="text-xs text-slate-500 mt-1 block">{subtitle}</span>
      )}
    </div>
  </motion.div>
);

// ═══════════════════════════════════════════════════════════════════════════
// STATUS PILL COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

type StatusType = 'healthy' | 'busy' | 'backlogged' | 'idle' | 'error';

interface StatusPillProps {
  status: StatusType;
  label?: string;
}

const STATUS_CONFIG: Record<
  StatusType,
  { color: string; bgColor: string; icon: React.ElementType }
> = {
  healthy: {
    color: 'text-emerald-400',
    bgColor: 'bg-emerald-500/20 border-emerald-500/30',
    icon: CheckCircle2,
  },
  busy: {
    color: 'text-amber-400',
    bgColor: 'bg-amber-500/20 border-amber-500/30',
    icon: Activity,
  },
  backlogged: {
    color: 'text-rose-400',
    bgColor: 'bg-rose-500/20 border-rose-500/30',
    icon: AlertTriangle,
  },
  idle: {
    color: 'text-slate-400',
    bgColor: 'bg-slate-500/20 border-slate-500/30',
    icon: Clock,
  },
  error: {
    color: 'text-rose-400',
    bgColor: 'bg-rose-500/20 border-rose-500/30',
    icon: XCircle,
  },
};

const StatusPill: React.FC<StatusPillProps> = ({ status, label }) => {
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1.5 px-3 py-1 rounded-full',
        'text-xs font-medium border',
        config.bgColor,
        config.color
      )}
    >
      <Icon className="w-3 h-3" />
      {label || status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// STAT ROW COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

interface StatRowProps {
  label: string;
  value: number | string;
  icon?: React.ElementType;
  color?: string;
}

const StatRow: React.FC<StatRowProps> = ({
  label,
  value,
  icon: Icon,
  color = 'text-slate-400',
}) => (
  <div className="flex items-center justify-between py-2">
    <div className="flex items-center gap-2">
      {Icon && <Icon className={cn('w-4 h-4', color)} />}
      <span className="text-sm text-slate-400">{label}</span>
    </div>
    <span className="text-sm font-medium text-white tabular-nums">
      {typeof value === 'number' ? value.toLocaleString() : value}
    </span>
  </div>
);

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const EnforcementEnginePage: React.FC = () => {
  const { data, status, refetch, errorMessage } = useEnforcementEngineData();
  const { triggerRefresh } = useRefreshBus();

  const kpis = useMemo(() => computeEnforcementEngineKPIs(data), [data]);

  const isLoading = status === 'loading' && !data;
  const isError = status === 'error';
  const isReady = status === 'ready' && data;

  const handleRefresh = () => {
    void refetch();
    triggerRefresh();
  };

  // Format generated_at timestamp
  const lastUpdated = useMemo(() => {
    if (!data?.generated_at) return null;
    try {
      const date = new Date(data.generated_at);
      return date.toLocaleTimeString('en-US', {
        hour: 'numeric',
        minute: '2-digit',
        second: '2-digit',
      });
    } catch {
      return null;
    }
  }, [data?.generated_at]);

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 via-slate-900 to-slate-800 text-white">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4 mb-8">
          <div>
            <h1 className="text-2xl font-bold text-white flex items-center gap-3">
              <div className="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-purple-600">
                <Zap className="w-5 h-5 text-white" />
              </div>
              Enforcement Engine
            </h1>
            <p className="text-sm text-slate-400 mt-1">
              Real-time AI worker pipeline monitoring
            </p>
          </div>

          <div className="flex items-center gap-3">
            {/* Last updated indicator */}
            {lastUpdated && (
              <span className="text-xs text-slate-500">
                Updated {lastUpdated}
              </span>
            )}

            {/* Refresh button */}
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRefresh}
              disabled={status === 'loading'}
              className="bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
            >
              {status === 'loading' ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <RefreshCw className="w-4 h-4" />
              )}
              <span className="ml-2">Refresh</span>
            </Button>

            {/* Queue health status */}
            <StatusPill status={kpis.queueHealth} />
          </div>
        </div>

        {/* Loading State */}
        {isLoading && <PageSkeleton />}

        {/* Error State */}
        {isError && (
          <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="rounded-xl border border-rose-500/30 bg-rose-500/10 p-6 text-center"
          >
            <AlertCircle className="w-10 h-10 text-rose-400 mx-auto mb-3" />
            <h3 className="text-lg font-semibold text-white mb-2">
              Failed to load metrics
            </h3>
            <p className="text-sm text-slate-400 mb-4">
              {errorMessage || 'Unable to connect to the enforcement engine.'}
            </p>
            <Button
              variant="secondary"
              size="sm"
              onClick={handleRefresh}
              className="bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700"
            >
              <RefreshCw className="w-4 h-4 mr-2" />
              Try Again
            </Button>
          </motion.div>
        )}

        {/* Ready State */}
        {isReady && (
          <div className="space-y-6">
            {/* Primary KPI Strip */}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
              <KPICard
                title="Plans Created (24h)"
                value={data.plans_created_24h}
                subtitle={`${data.total_plans.toLocaleString()} total`}
                icon={Target}
                iconColor="text-violet-400"
                accentColor="from-violet-500/20 to-transparent"
              />
              <KPICard
                title="Packets Generated (24h)"
                value={data.packets_generated_24h}
                subtitle={`${data.total_packets.toLocaleString()} total`}
                icon={FileText}
                iconColor="text-blue-400"
                accentColor="from-blue-500/20 to-transparent"
              />
              <KPICard
                title="Active Workers"
                value={data.active_workers}
                subtitle={`${data.pending_jobs} pending`}
                icon={Server}
                iconColor="text-emerald-400"
                accentColor="from-emerald-500/20 to-transparent"
              />
              <KPICard
                title="Success Rate (24h)"
                value={`${kpis.successRate24h}%`}
                subtitle={`${data.completed_24h} completed`}
                icon={CheckCircle2}
                iconColor={kpis.successRate24h >= 95 ? 'text-emerald-400' : 'text-amber-400'}
                accentColor={
                  kpis.successRate24h >= 95
                    ? 'from-emerald-500/20 to-transparent'
                    : 'from-amber-500/20 to-transparent'
                }
              />
            </div>

            {/* Secondary Metrics Cards */}
            <div className="grid gap-4 lg:grid-cols-3">
              {/* Plan Velocity */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.1 }}
                className={cn(
                  'rounded-xl border border-slate-700/50',
                  'bg-gradient-to-br from-slate-800/80 to-slate-900/80',
                  'backdrop-blur-sm p-5'
                )}
              >
                <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
                  <Target className="w-4 h-4 text-violet-400" />
                  Plan Creation
                </h3>
                <div className="divide-y divide-slate-700/50">
                  <StatRow label="Last 24 hours" value={data.plans_created_24h} />
                  <StatRow label="Last 7 days" value={data.plans_created_7d} />
                  <StatRow label="All time" value={data.total_plans} />
                </div>
              </motion.div>

              {/* Packet Generation */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.15 }}
                className={cn(
                  'rounded-xl border border-slate-700/50',
                  'bg-gradient-to-br from-slate-800/80 to-slate-900/80',
                  'backdrop-blur-sm p-5'
                )}
              >
                <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
                  <FileText className="w-4 h-4 text-blue-400" />
                  Packet Generation
                </h3>
                <div className="divide-y divide-slate-700/50">
                  <StatRow label="Last 24 hours" value={data.packets_generated_24h} />
                  <StatRow label="Last 7 days" value={data.packets_generated_7d} />
                  <StatRow label="All time" value={data.total_packets} />
                </div>
              </motion.div>

              {/* Queue Status */}
              <motion.div
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: 0.2 }}
                className={cn(
                  'rounded-xl border border-slate-700/50',
                  'bg-gradient-to-br from-slate-800/80 to-slate-900/80',
                  'backdrop-blur-sm p-5'
                )}
              >
                <h3 className="text-sm font-semibold text-slate-300 mb-4 flex items-center gap-2">
                  <Server className="w-4 h-4 text-emerald-400" />
                  Queue Status
                </h3>
                <div className="divide-y divide-slate-700/50">
                  <StatRow
                    label="Active workers"
                    value={data.active_workers}
                    icon={Activity}
                    color="text-emerald-400"
                  />
                  <StatRow
                    label="Pending jobs"
                    value={data.pending_jobs}
                    icon={Clock}
                    color="text-amber-400"
                  />
                  <StatRow
                    label="Completed (24h)"
                    value={data.completed_24h}
                    icon={CheckCircle2}
                    color="text-blue-400"
                  />
                  <StatRow
                    label="Failed (24h)"
                    value={data.failed_24h}
                    icon={XCircle}
                    color={data.failed_24h > 0 ? 'text-rose-400' : 'text-slate-500'}
                  />
                </div>
              </motion.div>
            </div>

            {/* Footer with refresh info */}
            <div className="text-center text-xs text-slate-600 py-4">
              Auto-refreshes every 30 seconds • Press R or click Refresh for immediate update
            </div>
          </div>
        )}
      </div>
    </div>
  );
};

export default EnforcementEnginePage;
