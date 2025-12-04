/**
 * EnforcementRadarPage
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Daily cockpit for enforcement operations.
 * Shows prioritized cases ranked by collectability + offer strategy.
 * 
 * Layout inspired by high-frequency trading desks:
 * - KPI strip at top
 * - Filter bar
 * - Dense data table with colored badges
 */
import React, { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  Target,
  DollarSign,
  TrendingUp,
  Filter,
  RefreshCw,
  ArrowUpDown,
  Sparkles,
  AlertCircle,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle, Button } from '../../components/primitives';
import { EnrichmentHealth } from '../../components/ops/EnrichmentHealth';
import {
  useEnforcementRadar,
  computeRadarKPIs,
  type OfferStrategy,
} from '../../hooks/useEnforcementRadar';
import { useRefreshBus } from '../../context/RefreshContext';
import { cn } from '../../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

const STRATEGY_OPTIONS: { value: OfferStrategy | 'ALL'; label: string }[] = [
  { value: 'ALL', label: 'All Strategies' },
  { value: 'BUY_CANDIDATE', label: 'Buy Candidates' },
  { value: 'CONTINGENCY', label: 'Contingency' },
  { value: 'ENRICHMENT_PENDING', label: 'Pending Enrichment' },
  { value: 'LOW_PRIORITY', label: 'Low Priority' },
];

// ═══════════════════════════════════════════════════════════════════════════
// BADGE COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

interface ScoreBadgeProps {
  score: number | null;
}

const ScoreBadge: React.FC<ScoreBadgeProps> = ({ score }) => {
  if (score === null) {
    return (
      <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400">
        <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
        —
      </span>
    );
  }

  let colorClasses: string;
  if (score >= 70) {
    colorClasses = 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400';
  } else if (score >= 40) {
    colorClasses = 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400';
  } else {
    colorClasses = 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400';
  }

  return (
    <span
      className={cn(
        'inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-semibold tabular-nums',
        colorClasses
      )}
    >
      {score}
    </span>
  );
};

interface StrategyBadgeProps {
  strategy: OfferStrategy;
}

const StrategyBadge: React.FC<StrategyBadgeProps> = ({ strategy }) => {
  const config: Record<OfferStrategy, { label: string; classes: string }> = {
    BUY_CANDIDATE: {
      label: 'BUY',
      classes: 'bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-400',
    },
    CONTINGENCY: {
      label: 'CONT',
      classes: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-400',
    },
    ENRICHMENT_PENDING: {
      label: 'PEND',
      classes: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400',
    },
    LOW_PRIORITY: {
      label: 'LOW',
      classes: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',
    },
  };

  const { label, classes } = config[strategy];

  return (
    <span
      className={cn(
        'inline-flex items-center px-2 py-0.5 rounded text-xs font-bold uppercase tracking-wide',
        classes
      )}
    >
      {label}
    </span>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// KPI CARD
// ═══════════════════════════════════════════════════════════════════════════

interface KPICardProps {
  title: string;
  value: string | number;
  subtitle?: string;
  icon: React.ElementType;
  iconColor?: string;
}

const KPICard: React.FC<KPICardProps> = ({ title, value, subtitle, icon: Icon, iconColor = 'text-primary' }) => (
  <Card className="relative overflow-hidden">
    <CardContent className="p-4">
      <div className="flex items-start justify-between">
        <div>
          <p className="text-sm font-medium text-muted-foreground">{title}</p>
          <p className="mt-1 text-2xl font-bold tabular-nums">{value}</p>
          {subtitle && <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>}
        </div>
        <div className={cn('p-2 rounded-lg bg-muted/50', iconColor)}>
          <Icon className="h-5 w-5" />
        </div>
      </div>
    </CardContent>
  </Card>
);

// ═══════════════════════════════════════════════════════════════════════════
// MAIN PAGE
// ═══════════════════════════════════════════════════════════════════════════

const EnforcementRadarPage: React.FC = () => {
  const { triggerRefresh, isRefreshing } = useRefreshBus();

  // Filter state
  const [strategyFilter, setStrategyFilter] = useState<OfferStrategy | 'ALL'>('ALL');
  const [minScore, setMinScore] = useState<number>(0);
  const [minAmount, setMinAmount] = useState<string>('');

  // Fetch data with filters
  const { state } = useEnforcementRadar({
    strategy: strategyFilter,
    minScore: minScore > 0 ? minScore : undefined,
    minAmount: minAmount ? Number(minAmount) : undefined,
  });

  // Compute KPIs
  const kpis = useMemo(() => {
    if (state.status !== 'ready' || !state.data) {
      return null;
    }
    return computeRadarKPIs(state.data);
  }, [state]);

  const formatCurrency = (value: number) =>
    new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(value);

  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return '—';
    try {
      return new Date(dateStr).toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: '2-digit',
      });
    } catch {
      return dateStr;
    }
  };

  // ─────────────────────────────────────────────────────────────────────────
  // LOADING STATE
  // ─────────────────────────────────────────────────────────────────────────

  if (state.status === 'loading' || state.status === 'idle') {
    return (
      <div className="space-y-6 p-6 animate-pulse">
        <div className="h-8 w-48 bg-muted rounded" />
        <div className="grid grid-cols-4 gap-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="h-24 bg-muted rounded-lg" />
          ))}
        </div>
        <div className="h-96 bg-muted rounded-lg" />
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // ERROR STATE
  // ─────────────────────────────────────────────────────────────────────────

  if (state.status === 'error') {
    return (
      <div className="p-6">
        <Card className="border-destructive/50">
          <CardContent className="p-6 text-center">
            <AlertCircle className="h-12 w-12 text-destructive mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">Unable to Load Radar</h3>
            <p className="text-muted-foreground mb-4">{state.errorMessage}</p>
            <Button onClick={triggerRefresh}>Retry</Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  // ─────────────────────────────────────────────────────────────────────────
  // DEMO LOCKED STATE
  // ─────────────────────────────────────────────────────────────────────────

  if (state.status === 'demo_locked') {
    return (
      <div className="p-6">
        <Card>
          <CardContent className="p-6 text-center">
            <Sparkles className="h-12 w-12 text-muted-foreground mx-auto mb-4" />
            <h3 className="text-lg font-semibold mb-2">Demo Mode</h3>
            <p className="text-muted-foreground">{state.lockMessage}</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const rows = state.data ?? [];

  // ─────────────────────────────────────────────────────────────────────────
  // READY STATE
  // ─────────────────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6 p-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <Target className="h-6 w-6 text-primary" />
            Enforcement Radar
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Prioritized cases ranked by collectability and offer strategy
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={triggerRefresh}
          disabled={isRefreshing}
          className="gap-2"
        >
          <RefreshCw className={cn('h-4 w-4', isRefreshing && 'animate-spin')} />
          Refresh
        </Button>
      </div>

      {/* KPI Strip */}
      {kpis && (
        <motion.div
          initial={{ opacity: 0, y: 10 }}
          animate={{ opacity: 1, y: 0 }}
          className="grid grid-cols-2 md:grid-cols-4 gap-4"
        >
          <KPICard
            title="Total Actionable Value"
            value={formatCurrency(kpis.totalActionableValue)}
            subtitle={`${kpis.buyCandidateCount + kpis.contingencyCount} cases`}
            icon={DollarSign}
            iconColor="text-green-600"
          />
          <KPICard
            title="Buy Candidates"
            value={kpis.buyCandidateCount}
            subtitle={formatCurrency(kpis.buyCandidateValue)}
            icon={TrendingUp}
            iconColor="text-purple-600"
          />
          <KPICard
            title="Contingency Ready"
            value={kpis.contingencyCount}
            subtitle={formatCurrency(kpis.contingencyValue)}
            icon={Target}
            iconColor="text-blue-600"
          />
          <KPICard
            title="Avg Collectability"
            value={kpis.avgScore !== null ? kpis.avgScore.toFixed(0) : '—'}
            subtitle={`${kpis.pendingCount} pending enrichment`}
            icon={Sparkles}
            iconColor="text-amber-600"
          />
        </motion.div>
      )}

      {/* Filter Bar + Enrichment Health */}
      <div className="grid grid-cols-1 lg:grid-cols-4 gap-4">
        <Card className="lg:col-span-3">
          <CardContent className="p-4">
            <div className="flex flex-wrap items-center gap-4">
              <div className="flex items-center gap-2">
                <Filter className="h-4 w-4 text-muted-foreground" />
                <span className="text-sm font-medium">Filters:</span>
              </div>

              {/* Strategy dropdown */}
              <select
                value={strategyFilter}
                onChange={(e) => setStrategyFilter(e.target.value as OfferStrategy | 'ALL')}
                className="h-9 px-3 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                {STRATEGY_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>

              {/* Min Score slider */}
              <div className="flex items-center gap-2">
                <label className="text-sm text-muted-foreground">Min Score:</label>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={10}
                  value={minScore}
                  onChange={(e) => setMinScore(Number(e.target.value))}
                  className="w-24 accent-primary"
                />
                <span className="text-sm font-medium w-8 tabular-nums">{minScore}</span>
              </div>

              {/* Min Amount input */}
              <div className="flex items-center gap-2">
                <label className="text-sm text-muted-foreground">Min $:</label>
                <input
                  type="number"
                  placeholder="0"
                  value={minAmount}
                  onChange={(e) => setMinAmount(e.target.value)}
                  className="h-9 w-24 px-3 rounded-md border border-input bg-background text-sm focus:outline-none focus:ring-2 focus:ring-ring tabular-nums"
                />
              </div>

              {/* Clear button */}
              {(strategyFilter !== 'ALL' || minScore > 0 || minAmount) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setStrategyFilter('ALL');
                    setMinScore(0);
                    setMinAmount('');
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Enrichment Health Widget */}
        <EnrichmentHealth className="lg:col-span-1" />
      </div>

      {/* Data Table */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-base flex items-center justify-between">
            <span>Radar Queue ({rows.length} cases)</span>
            <ArrowUpDown className="h-4 w-4 text-muted-foreground" />
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b bg-muted/50">
                <tr>
                  <th className="px-4 py-3 text-left font-medium">Case #</th>
                  <th className="px-4 py-3 text-left font-medium">Plaintiff</th>
                  <th className="px-4 py-3 text-left font-medium">Defendant</th>
                  <th className="px-4 py-3 text-right font-medium">Amount</th>
                  <th className="px-4 py-3 text-center font-medium">Score</th>
                  <th className="px-4 py-3 text-center font-medium">Strategy</th>
                  <th className="px-4 py-3 text-left font-medium">Court</th>
                  <th className="px-4 py-3 text-left font-medium">Date</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {rows.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="px-4 py-12 text-center text-muted-foreground">
                      No cases match the current filters.
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => (
                    <tr
                      key={row.id}
                      className="hover:bg-muted/30 transition-colors cursor-pointer"
                    >
                      <td className="px-4 py-3 font-mono text-xs">{row.caseNumber}</td>
                      <td className="px-4 py-3 max-w-[180px] truncate" title={row.plaintiffName}>
                        {row.plaintiffName}
                      </td>
                      <td className="px-4 py-3 max-w-[180px] truncate" title={row.defendantName}>
                        {row.defendantName}
                      </td>
                      <td className="px-4 py-3 text-right font-semibold tabular-nums">
                        {formatCurrency(row.judgmentAmount)}
                      </td>
                      <td className="px-4 py-3 text-center">
                        <ScoreBadge score={row.collectabilityScore} />
                      </td>
                      <td className="px-4 py-3 text-center">
                        <StrategyBadge strategy={row.offerStrategy} />
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">
                        {row.court ?? '—'}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs tabular-nums">
                        {formatDate(row.judgmentDate)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
};

export default EnforcementRadarPage;
