/**
 * ExecutiveDashboardPage - Dad's quick-glance scoreboard
 *
 * Simplified layout: Scoreboard → Trend Chart
 * Fast, clean, no cognitive load.
 */
import React, { useCallback, useMemo, useState } from 'react';
import { RefreshCw, BarChart3 } from 'lucide-react';
import { ExecutiveScoreboard } from '../components/ExecutiveScoreboard';
import type { ScoreboardMetric } from '../components/ExecutiveScoreboard';
import MetricsGate from '../components/MetricsGate';
import { EnforcementFlowChart } from '../components/EnforcementFlowChart';
import type { EnforcementFlowPoint } from '../components/EnforcementFlowChart';
import EmptyState from '../components/EmptyState';
import { useEnforcementMetrics, useIntakeMetrics, type IntakeMetricRow } from '../hooks/useExecutiveMetrics';
import { useEnforcementOverview } from '../hooks/useEnforcementOverview';
import { usePlaintiffCallQueue, type PlaintiffCallQueueRow } from '../hooks/usePlaintiffCallQueue';
import { formatCurrency } from '../utils/formatters';

const RECENT_WINDOW_DAYS = 7;
const RANGE_OPTIONS = [
  { label: '8 weeks', value: 8 },
  { label: '12 weeks', value: 12 },
  { label: '16 weeks', value: 16 },
];

const ExecutiveDashboardPageNew: React.FC = () => {
  const { state: intakeState, refetch: refetchIntake } = useIntakeMetrics(45);
  const { state: enforcementOverviewState, refetch: refetchEnforcementOverview } = useEnforcementOverview();
  const { state: callQueueState, refetch: refetchCallQueue } = usePlaintiffCallQueue(40);
  const [rangeWeeks, setRangeWeeks] = useState<number>(12);
  const { state: enforcementTrendState, refetch: refetchEnforcementTrend } = useEnforcementMetrics(rangeWeeks);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const handleRefreshAll = useCallback(async () => {
    setIsRefreshing(true);
    try {
      await Promise.allSettled([
        refetchIntake(),
        refetchEnforcementOverview(),
        refetchCallQueue(),
        refetchEnforcementTrend(),
      ]);
    } finally {
      setIsRefreshing(false);
    }
  }, [refetchCallQueue, refetchEnforcementOverview, refetchEnforcementTrend, refetchIntake]);

  // Derive scoreboard metrics
  const newPlaintiffs = useMemo(() => {
    if (intakeState.status !== 'ready' || !intakeState.data) return 0;
    return countRecentPlaintiffs(intakeState.data, RECENT_WINDOW_DAYS);
  }, [intakeState]);

  const activeCases = useMemo(() => {
    if (enforcementOverviewState.status !== 'ready' || !enforcementOverviewState.data) return 0;
    return enforcementOverviewState.data.reduce((sum, row) => sum + row.caseCount, 0);
  }, [enforcementOverviewState]);

  const activeExposure = useMemo(() => {
    if (enforcementOverviewState.status !== 'ready' || !enforcementOverviewState.data) return 0;
    return enforcementOverviewState.data.reduce((sum, row) => sum + row.totalJudgmentAmount, 0);
  }, [enforcementOverviewState]);

  const callsToday = useMemo(() => {
    if (callQueueState.status !== 'ready' || !callQueueState.data) return 0;
    return deriveCallsToday(callQueueState.data);
  }, [callQueueState]);

  const isLoading = [intakeState, enforcementOverviewState, callQueueState].some(
    (s) => s.status === 'loading' || s.status === 'idle'
  );

  const scoreboardMetrics: ScoreboardMetric[] = [
    {
      label: `New plaintiffs (${RECENT_WINDOW_DAYS}d)`,
      value: formatNumber(newPlaintiffs),
      trend: newPlaintiffs > 0 ? 'up' : 'neutral',
      trendLabel: newPlaintiffs > 10 ? 'Strong intake' : undefined,
    },
    {
      label: 'Active cases',
      value: formatNumber(activeCases),
      trend: 'neutral',
    },
    {
      label: 'Total exposure',
      value: formatCurrency(activeExposure),
      trend: activeExposure > 100_000 ? 'up' : 'neutral',
      trendLabel: activeExposure > 100_000 ? 'Growing portfolio' : undefined,
    },
    {
      label: "Today's calls",
      value: formatNumber(callsToday),
      trend: callsToday > 20 ? 'down' : 'neutral',
      trendLabel: callsToday > 20 ? 'Heavy day' : undefined,
    },
  ];

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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Scoreboard</h1>
          <p className="mt-1 text-sm text-slate-500">Business health at a glance</p>
        </div>
        <button
          type="button"
          onClick={() => void handleRefreshAll()}
          disabled={isRefreshing}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${isRefreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Scoreboard */}
      <ExecutiveScoreboard metrics={scoreboardMetrics} isLoading={isLoading} />

      {/* Enforcement Trend Chart */}
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
                className="rounded-lg border border-slate-200 bg-white px-3 py-1.5 text-sm text-slate-700 shadow-sm"
                value={rangeWeeks}
                onChange={(e) => setRangeWeeks(Number(e.target.value))}
              >
                {RANGE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
              <button
                type="button"
                onClick={() => void refetchEnforcementTrend()}
                disabled={enforcementTrendState.status === 'loading'}
                className="inline-flex items-center gap-1.5 rounded-lg bg-slate-100 px-3 py-1.5 text-sm font-medium text-slate-700 transition-colors hover:bg-slate-200"
              >
                <RefreshCw className={`h-3.5 w-3.5 ${enforcementTrendState.status === 'loading' ? 'animate-spin' : ''}`} />
                Refresh
              </button>
            </div>
          </div>
        </div>

        <div className="p-6">
          <MetricsGate
            state={enforcementTrendState}
            loadingFallback={<ChartSkeleton />}
            errorTitle="Unable to load trend data"
            onRetry={() => void refetchEnforcementTrend()}
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
        {['v_metrics_intake_daily', 'v_enforcement_overview', 'v_plaintiff_call_queue', 'v_metrics_enforcement'].map((view) => (
          <span key={view} className="rounded bg-slate-100 px-2 py-0.5 font-mono text-slate-500">{view}</span>
        ))}
      </div>

      {/* What changed today */}
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="px-6 py-4 border-b border-slate-100">
          <h2 className="text-lg font-semibold text-slate-900">What changed today</h2>
        </div>
        <div className="px-6 py-4">
          <TodayActivityList
            newPlaintiffs={newPlaintiffs}
            callsToday={callsToday}
            activeCases={activeCases}
          />
        </div>
      </section>
    </div>
  );
};

export default ExecutiveDashboardPageNew;

// --- Helpers ---

function formatNumber(value: number): string {
  return new Intl.NumberFormat('en-US').format(value);
}

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

function deriveCallsToday(rows: PlaintiffCallQueueRow[]): number {
  // Call queue represents plaintiffs that need to be called
  // Simply count all rows as they are pre-filtered by the view
  return rows.length;
}

function ChartSkeleton() {
  return (
    <div className="flex h-64 items-center justify-center">
      <div className="h-48 w-full animate-pulse rounded-lg bg-slate-100" />
    </div>
  );
}

interface TodayActivityListProps {
  newPlaintiffs: number;
  callsToday: number;
  activeCases: number;
}

function TodayActivityList({ newPlaintiffs, callsToday, activeCases }: TodayActivityListProps) {
  const activities: { label: string; value: number; positive: boolean }[] = [
    { label: 'New plaintiffs added', value: newPlaintiffs, positive: newPlaintiffs > 0 },
    { label: 'Calls scheduled today', value: callsToday, positive: callsToday > 0 },
    { label: 'Active enforcement cases', value: activeCases, positive: activeCases > 0 },
  ];

  const hasActivity = activities.some((a) => a.value > 0);

  if (!hasActivity) {
    return (
      <p className="text-sm text-slate-500">No activity to report yet today. Check back later!</p>
    );
  }

  return (
    <ul className="space-y-2">
      {activities.map((activity) => (
        <li key={activity.label} className="flex items-center gap-3 text-sm">
          <span className={`h-2 w-2 rounded-full ${activity.positive ? 'bg-emerald-500' : 'bg-slate-300'}`} />
          <span className="text-slate-700">{activity.label}</span>
          <span className="font-semibold text-slate-900">{activity.value}</span>
        </li>
      ))}
    </ul>
  );
}
