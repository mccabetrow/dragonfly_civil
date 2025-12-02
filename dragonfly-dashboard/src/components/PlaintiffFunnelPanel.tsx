import React from 'react';
import { DashboardError } from './DashboardError.tsx';
import DemoLockCard from './DemoLockCard';
import { InlineSpinner } from './InlineSpinner.tsx';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import { usePlaintiffFunnelStats, type PlaintiffFunnelStat } from '../hooks/usePlaintiffFunnelStats';
import { PLAINTIFF_STATUS_ORDER } from '../constants/plaintiffStatus';
import { formatCurrency } from '../utils/formatters';
import SectionHeader from './SectionHeader';

const PlaintiffFunnelPanel: React.FC = () => {
  const { state, refetch } = usePlaintiffFunnelStats();
  const stats = state.data ?? [];
  const status = state.status;
  const isIdle = status === 'idle';
  const isLoading = status === 'loading' || isIdle;
  const isDemoLocked = status === 'demo_locked';
  const isError = status === 'error';
  const showSkeleton = isLoading && stats.length === 0;
  const displayError = state.errorMessage || (typeof state.error === 'string' ? state.error : state.error?.message) || null;
  const fallbackErrorMessage = displayError ?? 'Unable to load funnel stats.';

  const refreshButton = (
    <button
      type="button"
      onClick={() => void refetch()}
      disabled={isLoading}
      className="inline-flex items-center gap-2 rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
    >
      {isLoading ? <InlineSpinner /> : null}
      <span>{isLoading ? 'Updating…' : 'Refresh'}</span>
    </button>
  );

  if (isDemoLocked) {
    return (
      <section className="df-card space-y-4">
        <SectionHeader
          title="Plaintiff funnel"
          description="Volume and value across each stage of the intake funnel."
        />
        <DemoLockCard description={state.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
      </section>
    );
  }

  return (
    <section className="df-card space-y-4">
      <SectionHeader
        title="Plaintiff funnel"
        description="Volume and value across each stage of the intake funnel."
        actions={refreshButton}
      />

      {showSkeleton ? (
        <SkeletonGrid />
      ) : isError ? (
        <DashboardError message={fallbackErrorMessage} onRetry={() => void refetch()} />
      ) : (
        <CardsGrid stats={stats} />
      )}
    </section>
  );
};

interface CardsGridProps {
  stats: PlaintiffFunnelStat[];
}

function CardsGrid({ stats }: CardsGridProps) {
  if (stats.length === 0) {
    return <p className="text-sm text-slate-500">No plaintiffs captured in the funnel yet.</p>;
  }

  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {stats.map((stat) => (
        <article key={stat.status} className="rounded-2xl border border-slate-100 bg-slate-50 px-5 py-4">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{stat.statusLabel}</p>
          <p className="mt-3 text-2xl font-semibold text-slate-900">{formatCount(stat.plaintiffCount)}</p>
          <p className="text-sm text-slate-600">{formatCurrency(stat.totalJudgmentAmount)}</p>
        </article>
      ))}
    </div>
  );
}

function SkeletonGrid() {
  const placeholderCount = PLAINTIFF_STATUS_ORDER.length + 1;
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: placeholderCount }).map((_, idx) => (
        <div key={idx} className="animate-pulse rounded-2xl border border-slate-100 bg-slate-50 px-5 py-4">
          <div className="h-3 w-24 rounded bg-slate-100" />
          <div className="mt-3 h-6 w-16 rounded bg-slate-100" />
          <div className="mt-2 h-3 w-28 rounded bg-slate-100" />
        </div>
      ))}
    </div>
  );
}

function formatCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '0';
  }
  return value.toLocaleString();
}

export default PlaintiffFunnelPanel;
