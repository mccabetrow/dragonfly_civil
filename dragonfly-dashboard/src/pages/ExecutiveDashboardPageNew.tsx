/**
 * ExecutiveDashboardPageNew - Command Center
 *
 * True operations command center with:
 * - Hero strip with snapshot + 7-day trend
 * - Tier distribution bar
 * - Today's Priorities with tier badges
 * - Weekly flow chart
 */
import React, { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { BarChart3, AlertTriangle, Target, DollarSign, TrendingUp } from 'lucide-react';
import MetricsGate from '../components/MetricsGate';
import { EnforcementFlowChart } from '../components/EnforcementFlowChart';
import type { EnforcementFlowPoint } from '../components/EnforcementFlowChart';
import EmptyState from '../components/EmptyState';
import { OverviewHero } from '../components/dashboard/OverviewHero';
import { TierDistributionBar } from '../components/dashboard/TierDistributionBar';
import type { TierSegment } from '../components/dashboard/TierDistributionBar';
import ActionList from '../components/dashboard/ActionList';
import { DashboardError } from '../components/DashboardError';
import { Card, CardHeader, CardTitle, CardContent } from '../components/ui/Card';
import { Badge } from '../components/ui/Badge';
import { KPICard, RecoveryAreaChart, PortfolioDonutChart } from '../components/charts';
import type { RecoveryDataPoint, PortfolioSegment } from '../components/charts';
import { useEnforcementMetrics, useIntakeMetrics, type IntakeMetricRow } from '../hooks/useExecutiveMetrics';
import { useEnforcementOverview } from '../hooks/useEnforcementOverview';
import { usePlaintiffCallQueue } from '../hooks/usePlaintiffCallQueue';
import { usePriorityCases, toActionItems } from '../hooks/usePriorityCases';
import { useRefreshBus } from '../context/RefreshContext';

const RANGE_OPTIONS = [
  { label: '8 weeks', value: 8 },
  { label: '12 weeks', value: 12 },
  { label: '16 weeks', value: 16 },
];

const ExecutiveDashboardPageNew: React.FC = () => {
  const navigate = useNavigate();
  const { state: intakeState } = useIntakeMetrics(45);
  const { state: enforcementOverviewState } = useEnforcementOverview();
  const { state: callQueueState } = usePlaintiffCallQueue(40);
  const { state: priorityCasesState } = usePriorityCases(5);
  const [rangeWeeks, setRangeWeeks] = useState<number>(12);
  const { state: enforcementTrendState } = useEnforcementMetrics(rangeWeeks);
  const { triggerRefresh, isRefreshing } = useRefreshBus();
  const [lastRefresh, setLastRefresh] = useState<Date | null>(null);

  // ═══════════════════════════════════════════════════════════════════════════
  // DERIVED METRICS
  // ═══════════════════════════════════════════════════════════════════════════

  // Active cases total
  const activeCases = useMemo(() => {
    if (enforcementOverviewState.status !== 'ready' || !enforcementOverviewState.data) return 0;
    return enforcementOverviewState.data.reduce((sum, row) => sum + row.caseCount, 0);
  }, [enforcementOverviewState]);

  // Total exposure
  const activeExposure = useMemo(() => {
    if (enforcementOverviewState.status !== 'ready' || !enforcementOverviewState.data) return 0;
    return enforcementOverviewState.data.reduce((sum, row) => sum + row.totalJudgmentAmount, 0);
  }, [enforcementOverviewState]);

  // Week-over-week change (calculate from intake data)
  const weekOverWeekChange = useMemo(() => {
    if (intakeState.status !== 'ready' || !intakeState.data || intakeState.data.length < 14) {
      return undefined;
    }
    const thisWeek = countRecentPlaintiffs(intakeState.data, 7);
    const lastWeek = countPlaintiffsInRange(intakeState.data, 7, 14);
    if (lastWeek === 0) return thisWeek > 0 ? 100 : 0;
    return ((thisWeek - lastWeek) / lastWeek) * 100;
  }, [intakeState]);

  // 7-day trend data for mini chart
  const trendData = useMemo(() => {
    if (intakeState.status !== 'ready' || !intakeState.data) return [];
    // Get daily counts for last 7 days
    const dailyCounts: number[] = [];
    for (let i = 6; i >= 0; i--) {
      const dayStart = new Date();
      dayStart.setHours(0, 0, 0, 0);
      dayStart.setDate(dayStart.getDate() - i);
      const dayEnd = new Date(dayStart);
      dayEnd.setDate(dayEnd.getDate() + 1);

      const count = intakeState.data.reduce((sum, row) => {
        const ts = Date.parse(row.activityDate);
        if (!Number.isNaN(ts) && ts >= dayStart.getTime() && ts < dayEnd.getTime()) {
          return sum + row.plaintiffCount;
        }
        return sum;
      }, 0);
      dailyCounts.push(count);
    }
    return dailyCounts;
  }, [intakeState]);

  // Tier distribution from enforcement overview
  const tierSegments = useMemo<TierSegment[]>(() => {
    if (enforcementOverviewState.status !== 'ready' || !enforcementOverviewState.data) {
      return [
        { tier: 'A', caseCount: 0, totalValue: 0 },
        { tier: 'B', caseCount: 0, totalValue: 0 },
        { tier: 'C', caseCount: 0, totalValue: 0 },
      ];
    }

    const tierMap: Record<'A' | 'B' | 'C', { count: number; value: number }> = {
      A: { count: 0, value: 0 },
      B: { count: 0, value: 0 },
      C: { count: 0, value: 0 },
    };

    enforcementOverviewState.data.forEach((row) => {
      const tier = normalizeTier(row.collectabilityTier);
      tierMap[tier].count += row.caseCount;
      tierMap[tier].value += row.totalJudgmentAmount;
    });

    return [
      { tier: 'A', caseCount: tierMap.A.count, totalValue: tierMap.A.value },
      { tier: 'B', caseCount: tierMap.B.count, totalValue: tierMap.B.value },
      { tier: 'C', caseCount: tierMap.C.count, totalValue: tierMap.C.value },
    ];
  }, [enforcementOverviewState]);

  // Projected 90-day recovery (estimated at 15% of Tier A + 8% of Tier B)
  const projectedRecovery90Days = useMemo(() => {
    const tierA = tierSegments.find((s) => s.tier === 'A')?.totalValue ?? 0;
    const tierB = tierSegments.find((s) => s.tier === 'B')?.totalValue ?? 0;
    return tierA * 0.15 + tierB * 0.08;
  }, [tierSegments]);

  // Recovery velocity chart data (derived from enforcement trend)
  const recoveryChartData = useMemo<RecoveryDataPoint[]>(() => {
    if (enforcementTrendState.status !== 'ready' || !enforcementTrendState.data) {
      return [];
    }
    // Use closed cases as proxy for recovery (in real app, would use actual collection data)
    return enforcementTrendState.data
      .slice()
      .reverse()
      .slice(-8) // Last 8 weeks
      .map((row, idx) => ({
        date: row.bucketWeek,
        label: `W${idx + 1}`,
        collected: row.casesClosed * 2500, // Placeholder: avg $2500 per closed case
        projected: idx >= 6 ? row.casesClosed * 2500 * 1.1 : undefined, // Project last 2 weeks
      }));
  }, [enforcementTrendState]);

  // Portfolio composition (Wage Garnishments vs Bank Levies vs Other)
  const portfolioData = useMemo<PortfolioSegment[]>(() => {
    // In production, this would come from enforcement_actions by type
    // For now, derive from tier distribution as approximation
    const tierA = tierSegments.find((s) => s.tier === 'A')?.totalValue ?? 0;
    const tierB = tierSegments.find((s) => s.tier === 'B')?.totalValue ?? 0;
    const tierC = tierSegments.find((s) => s.tier === 'C')?.totalValue ?? 0;
    const total = tierA + tierB + tierC;
    
    if (total === 0) {
      return [
        { name: 'Wage Garnishments', value: 0, color: '#6366f1' },
        { name: 'Bank Levies', value: 0, color: '#8b5cf6' },
        { name: 'Other', value: 0, color: '#94a3b8' },
      ];
    }

    // Approximate distribution: 55% wage garnishment, 30% bank levy, 15% other
    return [
      { name: 'Wage Garnishments', value: total * 0.55, color: '#6366f1' },
      { name: 'Bank Levies', value: total * 0.30, color: '#8b5cf6' },
      { name: 'Other', value: total * 0.15, color: '#94a3b8' },
    ];
  }, [tierSegments]);

  // Priority count by tier
  const priorityTierCounts = useMemo(() => {
    if (priorityCasesState.status !== 'ready' || !priorityCasesState.data) {
      return { A: 0, B: 0 };
    }
    return priorityCasesState.data.reduce(
      (acc, c) => {
        if (c.tier === 'A') acc.A++;
        else if (c.tier === 'B') acc.B++;
        return acc;
      },
      { A: 0, B: 0 }
    );
  }, [priorityCasesState]);

  // Loading states
  const isLoading = [intakeState, enforcementOverviewState, callQueueState].some(
    (s) => s.status === 'loading' || s.status === 'idle'
  );

  // Convert priority cases to action items for ActionList
  const priorityActionItems = useMemo(() => {
    if (priorityCasesState.status !== 'ready' || !priorityCasesState.data) return [];
    return toActionItems(priorityCasesState.data);
  }, [priorityCasesState]);

  const isPriorityLoading = priorityCasesState.status === 'loading' || priorityCasesState.status === 'idle';
  const isPriorityError = priorityCasesState.status === 'error';

  // Check for errors
  const hasError = [intakeState, enforcementOverviewState, callQueueState].some(
    (s) => s.status === 'error'
  );
  const errorMessage = [intakeState, enforcementOverviewState, callQueueState]
    .find((s) => s.status === 'error')?.errorMessage ?? 'Unable to load metrics';

  // Chart data
  const chartData = useMemo<EnforcementFlowPoint[]>(() => {
    if (enforcementTrendState.status !== 'ready' || !enforcementTrendState.data) {
      return [];
    }
    const normalized = enforcementTrendState.data
      .slice()
      .reverse()
      .map((row) => ({
        bucketLabel: row.bucketWeek,
        casesOpened: row.casesOpened,
        casesClosed: row.casesClosed,
        activeJudgmentAmount: row.activeJudgmentAmount,
      }));
    if (rangeWeeks > 0 && normalized.length > rangeWeeks) {
      return normalized.slice(-rangeWeeks);
    }
    return normalized;
  }, [enforcementTrendState.data, enforcementTrendState.status, rangeWeeks]);

  // Refresh handler
  const handleRefresh = () => {
    setLastRefresh(new Date());
    triggerRefresh();
  };

  // ═══════════════════════════════════════════════════════════════════════════
  // RENDER
  // ═══════════════════════════════════════════════════════════════════════════

  return (
    <div className="space-y-6">
      {/* Error state */}
      {hasError && (
        <DashboardError
          title="Data unavailable"
          message={errorMessage}
          onRetry={handleRefresh}
        />
      )}

      {/* Hero Strip */}
      <OverviewHero
        totalCases={activeCases}
        totalExposure={activeExposure}
        weekOverWeekChange={weekOverWeekChange}
        trendData={trendData}
        isRefreshing={isRefreshing || isLoading}
        lastUpdated={lastRefresh}
        onRefresh={handleRefresh}
        loading={isLoading}
      />

      {/* KPI Cards Row */}
      <div className="grid gap-4 sm:grid-cols-2">
        <KPICard
          title="Total Liquidation Value"
          value={`$${(activeExposure / 1_000_000).toFixed(2)}M`}
          subtitle="Active judgments under enforcement"
          icon={<DollarSign className="h-4 w-4" />}
          trend={weekOverWeekChange !== undefined ? { value: weekOverWeekChange, label: 'vs last week' } : undefined}
          loading={isLoading}
        />
        <KPICard
          title="Projected Recovery (90 Days)"
          value={`$${(projectedRecovery90Days / 1_000).toFixed(0)}K`}
          subtitle="Based on Tier A/B success rates"
          icon={<TrendingUp className="h-4 w-4" />}
          loading={isLoading}
        />
      </div>

      {/* Charts Row */}
      <div className="grid gap-4 lg:grid-cols-2">
        <RecoveryAreaChart
          data={recoveryChartData}
          title="Recovery Velocity"
          subtitle="Weekly collection performance"
          loading={enforcementTrendState.status === 'loading' || enforcementTrendState.status === 'idle'}
          showProjected
        />
        <PortfolioDonutChart
          data={portfolioData}
          title="Portfolio Composition"
          subtitle="Enforcement method distribution"
          loading={isLoading}
          centerLabel="Total Value"
        />
      </div>

      {/* Tier Distribution Bar */}
      <Card>
        <CardContent className="pt-5">
          <TierDistributionBar
            segments={tierSegments}
            loading={enforcementOverviewState.status === 'loading' || enforcementOverviewState.status === 'idle'}
          />
        </CardContent>
      </Card>

      {/* Today's Priorities */}
      {isPriorityError ? (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-rose-700">
              <AlertTriangle className="h-5 w-5" />
              Unable to load priorities
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="mb-3 text-sm text-slate-600">
              {priorityCasesState.errorMessage ?? "We couldn't fetch today's priority cases."}
            </p>
            <button
              type="button"
              onClick={handleRefresh}
              className="text-sm font-medium text-indigo-600 hover:text-indigo-700"
            >
              Try again
            </button>
          </CardContent>
        </Card>
      ) : (
        <div className="rounded-2xl border border-slate-200 bg-white shadow-sm">
          {/* Custom header with tier badge */}
          <div className="flex items-center justify-between border-b border-slate-100 px-6 py-4">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-100 text-amber-600">
                <Target className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Today's Priorities</h2>
                <p className="text-sm text-slate-500">High-value cases ready for action</p>
              </div>
            </div>
            {/* Tier source badge */}
            {(priorityTierCounts.A > 0 || priorityTierCounts.B > 0) && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-400">From</span>
                {priorityTierCounts.A > 0 && (
                  <Badge variant="tier-a" size="sm">
                    {priorityTierCounts.A} Tier A
                  </Badge>
                )}
                {priorityTierCounts.B > 0 && (
                  <Badge variant="tier-b" size="sm">
                    {priorityTierCounts.B} Tier B
                  </Badge>
                )}
              </div>
            )}
          </div>

          <div className="p-6">
            <ActionList
              items={priorityActionItems}
              loading={isPriorityLoading}
              maxItems={5}
              emptyMessage="No high-priority cases right now. Great work!"
              onItemClick={(item) => {
                navigate(`/cases?caseId=${item.id}`);
              }}
            />
          </div>
        </div>
      )}

      {/* Weekly Flow Chart */}
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-100 text-indigo-600">
                <BarChart3 className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Weekly Flow</h2>
                <p className="text-sm text-slate-500">Cases opened vs closed, exposure trend</p>
              </div>
            </div>
            <div className="flex items-center gap-3">
              <select
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 shadow-sm transition focus:border-indigo-300 focus:outline-none focus:ring-2 focus:ring-indigo-500/20"
                value={rangeWeeks}
                onChange={(e) => setRangeWeeks(Number(e.target.value))}
              >
                {RANGE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        <div className="p-6">
          <MetricsGate
            state={enforcementTrendState}
            loadingFallback={<ChartSkeleton />}
            errorTitle="Unable to load trend data"
            onRetry={handleRefresh}
            ready={
              chartData.length === 0 ? (
                <EmptyState
                  title="No enforcement data yet"
                  description="Add judgments to see trends."
                />
              ) : (
                <EnforcementFlowChart data={chartData} />
              )
            }
          />
        </div>
      </section>

      {/* Data sources footer */}
      <div className="flex flex-wrap items-center gap-2 text-xs text-slate-400">
        <span>Sources:</span>
        {['v_metrics_intake_daily', 'v_enforcement_overview', 'v_collectability_snapshot', 'v_metrics_enforcement'].map(
          (view) => (
            <span key={view} className="rounded bg-slate-100 px-2 py-0.5 font-mono text-slate-500">
              {view}
            </span>
          )
        )}
      </div>
    </div>
  );
};

export default ExecutiveDashboardPageNew;

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function countRecentPlaintiffs(rows: IntakeMetricRow[], windowDays: number): number {
  const now = Date.now();
  const windowMs = windowDays * 24 * 60 * 60 * 1000;
  return rows.reduce((sum, row) => {
    const ts = Date.parse(row.activityDate);
    if (!Number.isNaN(ts) && now - ts <= windowMs) {
      return sum + row.plaintiffCount;
    }
    return sum;
  }, 0);
}

function countPlaintiffsInRange(rows: IntakeMetricRow[], startDays: number, endDays: number): number {
  const now = Date.now();
  const startMs = startDays * 24 * 60 * 60 * 1000;
  const endMs = endDays * 24 * 60 * 60 * 1000;
  return rows.reduce((sum, row) => {
    const ts = Date.parse(row.activityDate);
    const age = now - ts;
    if (!Number.isNaN(ts) && age > startMs && age <= endMs) {
      return sum + row.plaintiffCount;
    }
    return sum;
  }, 0);
}

function normalizeTier(tier: string | null): 'A' | 'B' | 'C' {
  const normalized = (tier ?? '').toUpperCase().trim();
  if (normalized === 'A' || normalized === 'B') return normalized as 'A' | 'B';
  return 'C';
}

function ChartSkeleton() {
  return (
    <div className="flex h-64 items-center justify-center">
      <div className="h-48 w-full animate-pulse rounded-lg bg-slate-100" />
    </div>
  );
}
