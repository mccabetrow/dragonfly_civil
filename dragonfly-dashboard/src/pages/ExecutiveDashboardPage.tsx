import React, { useCallback, useMemo, useState } from 'react';
import PageHeader from '../components/PageHeader';
import SectionHeader from '../components/SectionHeader';
import MetricCard from '../components/MetricCard';
import EmptyState from '../components/EmptyState';
import MetricsGate from '../components/MetricsGate';
import { EnforcementFlowChart } from '../components/EnforcementFlowChart';
import type { EnforcementFlowPoint } from '../components/EnforcementFlowChart';
import RefreshButton from '../components/RefreshButton';
import DemoLockCard from '../components/DemoLockCard';
import { DashboardError } from '../components/DashboardError';
import LitigationBudgetCard from '../components/LitigationBudgetCard';
import { useEnforcementMetrics, useIntakeMetrics, type IntakeMetricRow } from '../hooks/useExecutiveMetrics';
import { useEnforcementOverview, type EnforcementOverviewRow } from '../hooks/useEnforcementOverview';
import { usePlaintiffCallQueue, type PlaintiffCallQueueRow } from '../hooks/usePlaintiffCallQueue';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';

const RECENT_WINDOW_DAYS = 7;
const RANGE_OPTIONS = [
  { label: 'Last 8 weeks', value: 8 },
  { label: 'Last 12 weeks', value: 12 },
  { label: 'Last 16 weeks', value: 16 },
];
const SOURCE_VIEWS = [
  'v_plaintiff_call_queue',
  'v_enforcement_overview',
  'v_metrics_enforcement',
  'v_metrics_intake_daily',
];

const ExecutiveDashboardPage: React.FC = () => {
  const { state: intakeState, refetch: refetchIntake } = useIntakeMetrics(45);
  const { state: enforcementOverviewState, refetch: refetchEnforcementOverview } = useEnforcementOverview();
  const { state: callQueueState, refetch: refetchCallQueue } = usePlaintiffCallQueue(40);
  const [rangeWeeks, setRangeWeeks] = useState<number>(RANGE_OPTIONS[1]?.value ?? 12);
  const { state: enforcementTrendState, refetch: refetchEnforcementTrend } = useEnforcementMetrics(rangeWeeks);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const snapshotStates = [intakeState, enforcementOverviewState, callQueueState];
  const snapshotHasData = snapshotStates.some((snapshot) => Boolean(snapshot.data));
  const chartHasExistingData = Boolean(enforcementTrendState.data);
  const hasAnyData = snapshotHasData || chartHasExistingData;
  const metricsLocked = snapshotStates.every((snapshot) => snapshot.status === 'demo_locked');
  const metricsErrored = snapshotStates.every((snapshot) => snapshot.status === 'error');
  const metricsLoading =
    !snapshotHasData && snapshotStates.some((snapshot) => snapshot.status === 'loading' || snapshot.status === 'idle');
  const lockMessage = snapshotStates.find((snapshot) => snapshot.lockMessage)?.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE;
  const errorMessage =
    snapshotStates.find((snapshot) => snapshot.errorMessage)?.errorMessage ?? 'Unable to load executive snapshot metrics.';

  const newPlaintiffs =
    intakeState.status === 'ready' ? countRecentPlaintiffs(intakeState.data ?? [], RECENT_WINDOW_DAYS) : 0;
  const activeCases =
    enforcementOverviewState.status === 'ready' ? sumActiveCases(enforcementOverviewState.data ?? []) : 0;
  const activeJudgmentAmount =
    enforcementOverviewState.status === 'ready' ? sumActiveJudgment(enforcementOverviewState.data ?? []) : 0;
  const callsToday = callQueueState.status === 'ready' ? deriveCallsToday(callQueueState.data ?? []) : 0;

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

  const handleRangeChange = useCallback((event: React.ChangeEvent<HTMLSelectElement>) => {
    const nextValue = Number(event.target.value);
    setRangeWeeks(Number.isNaN(nextValue) ? RANGE_OPTIONS[0].value : nextValue);
  }, []);

  const handleTrendRefresh = useCallback(() => refetchEnforcementTrend(), [refetchEnforcementTrend]);

  const metricCards = [
    {
      key: 'newPlaintiffs',
      label: `Plaintiffs imported (${RECENT_WINDOW_DAYS}d)`,
      description: 'Unique plaintiffs entering Dragonfly during the past week.',
      state: intakeState,
      value: newPlaintiffs,
      formatter: formatNumber,
    },
    {
      key: 'activeCases',
      label: 'Active enforcement cases',
      description: 'Matters currently tracked across enforcement stages.',
      state: enforcementOverviewState,
      value: activeCases,
      formatter: formatNumber,
    },
    {
      key: 'activeExposure',
      label: 'Active judgment amount',
      description: 'Blended judgment value tied to those active matters.',
      state: enforcementOverviewState,
      value: activeJudgmentAmount,
      formatter: formatCurrency,
    },
    {
      key: 'callsToday',
      label: 'Calls scheduled for today',
      description: 'Call-queue load surfaced by v_plaintiff_call_queue.',
      state: callQueueState,
      value: callsToday,
      formatter: formatNumber,
    },
  ];

  const metricGrid = (
    <div className="grid auto-rows-fr gap-4 md:grid-cols-2 xl:grid-cols-4">
      {metricCards.map((metric) => {
        const state = metric.state;
        const status = state.status;
        const cardStatus = status === 'demo_locked' ? 'locked' : status === 'error' ? 'error' : 'default';
        const message =
          status === 'demo_locked'
            ? state.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE
            : status === 'error'
            ? state.errorMessage || (typeof state.error === 'string' ? state.error : state.error?.message) || 'Unable to load this metric.'
            : undefined;
        return (
          <MetricCard
            key={metric.key}
            label={metric.label}
            value={status === 'ready' ? metric.formatter(metric.value) : undefined}
            loading={status === 'loading' || status === 'idle'}
            status={cardStatus}
            message={message}
            footer={metric.description}
            className="h-full"
          />
        );
      })}
    </div>
  );
  let metricSectionContent: React.ReactNode;
  if (metricsLocked) {
    metricSectionContent = <DemoLockCard className="w-full" description={lockMessage} />;
  } else if (metricsErrored) {
    metricSectionContent = (
      <DashboardError
        className="w-full"
        title="Unable to load executive summary"
        message={errorMessage}
        onRetry={handleRefreshAll}
      />
    );
  } else if (metricsLoading) {
    metricSectionContent = <MetricGridSkeleton />;
  } else {
    metricSectionContent = metricGrid;
  }

  const chartActions = (
    <div className="flex flex-wrap items-center gap-3">
      <label className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-[0.3em] text-slate-500">
        Range
        <select
          className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-semibold uppercase tracking-[0.3em] text-slate-700 shadow-sm focus:border-slate-400 focus:outline-none"
          value={rangeWeeks}
          onChange={handleRangeChange}
        >
          {RANGE_OPTIONS.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <RefreshButton
        onClick={handleTrendRefresh}
        isLoading={enforcementTrendState.status === 'loading'}
        hasData={chartHasExistingData}
        label="Refresh trend"
      />
    </div>
  );

  const sourceBadges = (
    <div className="flex flex-wrap gap-2">
      {SOURCE_VIEWS.map((view) => (
        <span
          key={view}
          className="rounded-full border border-white/20 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.25em] text-white/75"
        >
          {view}
        </span>
      ))}
    </div>
  );

  return (
    <div className="df-page">
      <PageHeader
        eyebrow="Executive Pulse"
        title="Executive dashboard"
        subtitle="Supabase production parity"
        actions={
          <RefreshButton onClick={handleRefreshAll} isLoading={isRefreshing} hasData={hasAnyData} label="Refresh data" />
        }
      >
        {sourceBadges}
      </PageHeader>

      <section>
        <SectionHeader
          eyebrow="Snapshot"
          title="Executive summary"
          description="Quick view of pipeline intake, active exposure, and today's call queue."
        />
        <div className="mt-4">{metricSectionContent}</div>
      </section>

      {/* Litigation Budget Section */}
      <section>
        <SectionHeader
          eyebrow="Financial Modeling"
          title="Daily Litigation Budget"
          description="Budget allocations for skip tracing, litigation, marshals, and FOIL based on Tier A + B liquidity."
        />
        <div className="mt-4">
          <LitigationBudgetCard />
        </div>
      </section>

      <section className="df-card space-y-6">
        <SectionHeader
          eyebrow="Enforcement performance"
          title="Weekly flow vs. active exposure"
          description="Bars show cases opened versus closed; the line tracks total active judgment exposure."
          actions={chartActions}
        />
        <MetricsGate
          className="mt-2"
          state={enforcementTrendState}
          loadingFallback={<ChartSkeleton />}
          errorTitle="Unable to load enforcement metrics"
          onRetry={handleTrendRefresh}
          ready={
            chartData.length === 0 ? (
              <EmptyState
                title="No enforcement records yet"
                description="Add judgments to see the flow trend populate."
              />
            ) : (
              <EnforcementFlowChart data={chartData} />
            )
          }
        />
        <p className="mt-4 text-xs text-slate-500">
          Weekly enforcement flow shows opened vs. closed cases alongside exposure pulled from Supabase ({' '}
          <code className="rounded bg-slate-100 px-1 text-[11px] text-slate-700">v_metrics_enforcement</code> ).
        </p>
      </section>
    </div>
  );
};

export default ExecutiveDashboardPage;

function countRecentPlaintiffs(rows: IntakeMetricRow[], windowDays: number): number {
  if (!rows.length) {
    return 0;
  }
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

function sumActiveCases(rows: EnforcementOverviewRow[]): number {
  if (!rows.length) {
    return 0;
  }
  return rows.reduce((sum, row) => sum + row.caseCount, 0);
}

function sumActiveJudgment(rows: EnforcementOverviewRow[]): number {
  if (!rows.length) {
    return 0;
  }
  return rows.reduce((sum, row) => sum + row.totalJudgmentAmount, 0);
}

function deriveCallsToday(rows: PlaintiffCallQueueRow[]): number {
  if (!rows.length) {
    return 0;
  }
  const today = new Date();
  const todaysRows = rows.filter((row) => isSameDay(row.createdAt ?? row.lastContactedAt, today));
  return todaysRows.length > 0 ? todaysRows.length : rows.length;
}

function isSameDay(value: string | null, reference: Date): boolean {
  if (!value) {
    return false;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return false;
  }
  return (
    parsed.getFullYear() === reference.getFullYear() &&
    parsed.getMonth() === reference.getMonth() &&
    parsed.getDate() === reference.getDate()
  );
}

function formatNumber(value: number) {
  if (!Number.isFinite(value)) {
    return '0';
  }
  return value.toLocaleString();
}

function formatCurrency(value: number) {
  if (!Number.isFinite(value)) {
    return '$0';
  }
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    maximumFractionDigits: value >= 100000 ? 0 : 2,
  }).format(value);
}

function MetricGridSkeleton() {
  return (
    <div className="grid auto-rows-fr gap-4 md:grid-cols-2 xl:grid-cols-4">
      {Array.from({ length: 4 }).map((_, index) => (
        <div
          key={`metric-skeleton-${index}`}
          className="rounded-2xl border border-slate-200/80 bg-white/80 p-5 shadow-sm shadow-slate-900/5"
        >
          <div className="df-skeleton h-3 w-28" aria-hidden />
          <div className="mt-4 df-skeleton h-12 w-40" aria-hidden />
          <div className="mt-4 df-skeleton h-3 w-3/4" aria-hidden />
        </div>
      ))}
    </div>
  );
}

function ChartSkeleton() {
  return (
    <div className="df-card space-y-4" aria-label="Loading enforcement chart">
      <div className="df-skeleton h-3 w-24" aria-hidden />
      <div className="df-skeleton h-3 w-40" aria-hidden />
      <div className="h-[260px] w-full rounded-2xl border border-dashed border-slate-200/80 bg-slate-50 p-6">
        <div className="flex h-full items-end gap-3">
          {Array.from({ length: 6 }).map((_, index) => (
            <div key={`chart-skeleton-bar-${index}`} className="flex-1 space-y-3">
              <div className="df-skeleton h-[120px] w-full" aria-hidden />
              <div className="df-skeleton h-2 w-full" aria-hidden />
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
