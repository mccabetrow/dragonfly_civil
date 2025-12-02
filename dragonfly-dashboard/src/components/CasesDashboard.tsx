import React, { useMemo, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import DemoLockCard from './DemoLockCard';
import RefreshButton from './RefreshButton';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import { useCasesDashboard, type CasesDashboardRow } from '../hooks/useCasesDashboard';
import { formatCurrency, formatDateTime } from '../utils/formatters';
import SectionHeader from './SectionHeader';

const CasesDashboard: React.FC = () => {
  const { state, refetch } = useCasesDashboard();
  const navigate = useNavigate();

  const rows = state.data?.rows ?? [];
  const totalCount = state.data?.totalCount ?? 0;
  const status = state.status;
  const isIdle = status === 'idle';
  const isLoading = status === 'loading' || isIdle;
  const isError = status === 'error';
  const isDemoLocked = status === 'demo_locked';
  const hasRows = rows.length > 0;
  const displayError = state.errorMessage || (typeof state.error === 'string' ? state.error : state.error?.message) || null;
  const showTotalCount = status === 'ready' && !displayError && !isDemoLocked && totalCount >= 0;
  const showSkeleton = isLoading && !hasRows && !displayError && !isDemoLocked;
  const showEmpty = status === 'ready' && !displayError && !isDemoLocked && !hasRows;
  const showDemoLock = isDemoLocked;
  const showTable = hasRows && !displayError && !isDemoLocked;

  const tableRows = useMemo(() => rows, [rows]);

  const handleNavigate = useCallback(
    (caseNumber: string) => {
      if (!caseNumber || caseNumber === '—') return;
      navigate(`/cases/${encodeURIComponent(caseNumber)}`);
    },
    [navigate],
  );

  return (
    <div className="space-y-8">
      <header className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-white px-6 py-6 shadow-sm">
        <SectionHeader
          title="Plaintiff-ready cases"
          description="Every judgment entrusted to Dragonfly, prioritized for action. Track scores, outreach status, and fresh enrichment in one glance."
          actions={
            <RefreshButton
              onClick={() => void refetch()}
              isLoading={isLoading}
              hasData={hasRows}
            />
          }
        />
      </header>

      <section className="rounded-3xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-6 py-4">
          <SectionHeader
            title="Cases overview"
            description="Case numbers, counterparties, and collection momentum at a glance."
            actions={
              showTotalCount ? (
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-400">
                  {totalCount.toLocaleString()} {totalCount === 1 ? 'case' : 'cases'}
                </div>
              ) : null
            }
          />
        </div>

        {showSkeleton && <TableSkeleton />}

        {isError && displayError && !isLoading ? <ErrorState onRetry={refetch} message={displayError} /> : null}

        {showDemoLock && <DemoLockCard description={state.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />}

        {showEmpty && <EmptyState />}

        {showTable && (
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-slate-100 text-left">
              <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                <tr>
                  <HeaderCell>Stage</HeaderCell>
                  <HeaderCell>Case number</HeaderCell>
                  <HeaderCell>Plaintiff</HeaderCell>
                  <HeaderCell>Defendant</HeaderCell>
                  <HeaderCell>Collectability</HeaderCell>
                  <HeaderCell>Judgment amount</HeaderCell>
                  <HeaderCell>Enrichment</HeaderCell>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
                {tableRows.map((row: CasesDashboardRow) => (
                  <CaseRow key={`${row.judgmentId}-${row.caseNumber}`} row={row} onNavigate={handleNavigate} />
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
};

export default CasesDashboard;

function HeaderCell({ children }: { children: React.ReactNode }) {
  return <th className="px-6 py-3">{children}</th>;
}

function DataCell({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return <td className={`px-6 py-4 align-middle ${className}`.trim()}>{children}</td>;
}

function formatCurrencyCell(value: number | null): string {
  return formatCurrency(value ?? null);
}

const skeletonRow = Array.from({ length: 7 });

const TableSkeleton: React.FC = () => (
  <div className="space-y-0">
    <div className="animate-pulse border-b border-slate-100 px-6 py-4">
      <div className="grid grid-cols-7 gap-6">
        {skeletonRow.map((_, index) => (
          <div key={`skeleton-${index}`} className="h-4 rounded bg-slate-200" />
        ))}
      </div>
    </div>
    {Array.from({ length: 5 }).map((_, rowIndex) => (
      <div key={`skeleton-body-${rowIndex}`} className="animate-pulse border-b border-slate-100 px-6 py-4">
        <div className="grid grid-cols-7 gap-6">
          {skeletonRow.map((__, index) => (
            <div key={`skeleton-body-${rowIndex}-${index}`} className="h-3.5 rounded bg-slate-200" />
          ))}
        </div>
      </div>
    ))}
  </div>
);

const EmptyState: React.FC = () => (
  <div className="px-6 py-14 text-center">
    <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-slate-100 text-slate-400">
      <span className="text-xl" aria-hidden="true">
        •
      </span>
    </div>
    <p className="mt-6 text-base font-semibold text-slate-900">No cases yet</p>
    <p className="mt-2 text-sm text-slate-600">
      Once we ingest judgments for your firm, they’ll appear here with scores and statuses that help you prioritize outreach.
    </p>
  </div>
);

function CaseRow({ row, onNavigate }: { row: CasesDashboardRow; onNavigate: (caseNumber: string) => void }) {
  const handleClick = () => onNavigate(row.caseNumber);
  const handleKeyDown = (event: React.KeyboardEvent<HTMLTableRowElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onNavigate(row.caseNumber);
    }
  };

  return (
    <tr
      tabIndex={0}
      onClick={handleClick}
      onKeyDown={handleKeyDown}
      aria-label={`View case ${row.caseNumber !== '—' ? row.caseNumber : row.judgmentId}`}
      className="cursor-pointer transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500/40"
    >
      <DataCell>
        <StageBadge stage={row.enforcementStage} label={row.enforcementStageLabel} updatedAt={row.enforcementStageUpdatedIso} />
      </DataCell>
      <DataCell className="font-medium text-slate-800">{row.caseNumber}</DataCell>
      <DataCell>{row.plaintiffName}</DataCell>
      <DataCell>{row.defendantName}</DataCell>
      <DataCell>
        <CollectabilityBadge
          tier={row.collectabilityTier}
          label={row.collectabilityTierLabel}
          ageDays={row.collectabilityAgeDays}
        />
      </DataCell>
      <DataCell>{formatCurrencyCell(row.judgmentAmount)}</DataCell>
      <DataCell>
        <div className="flex flex-col">
          <span className="font-medium text-slate-700">{row.lastEnrichmentStatusLabel}</span>
          <span className="text-xs text-slate-500">{formatDateTime(row.lastEnrichedAtIso)}</span>
        </div>
      </DataCell>
    </tr>
  );
}

function collectabilityBadgeClass(tier: string | null): string {
  if (!tier) {
    return 'inline-flex w-max items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600';
  }
  switch (tier.toLowerCase()) {
    case 'tier_1':
    case 'tier1':
      return 'inline-flex w-max items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-700';
    case 'tier_2':
    case 'tier2':
      return 'inline-flex w-max items-center rounded-full border border-lime-500/30 bg-lime-500/10 px-2 py-0.5 text-xs font-semibold text-lime-700';
    case 'tier_3':
    case 'tier3':
      return 'inline-flex w-max items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-700';
    case 'tier_4':
    case 'tier4':
      return 'inline-flex w-max items-center rounded-full border border-orange-500/30 bg-orange-500/10 px-2 py-0.5 text-xs font-semibold text-orange-700';
    case 'tier_5':
    case 'tier5':
      return 'inline-flex w-max items-center rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-0.5 text-xs font-semibold text-rose-700';
    default:
      return 'inline-flex w-max items-center rounded-full border border-slate-500/30 bg-slate-500/10 px-2 py-0.5 text-xs font-semibold text-slate-700';
  }
}

function StageBadge({ stage, label, updatedAt }: { stage: string | null; label: string; updatedAt: string | null }) {
  const badgeClass = stageBadgeClass(stage);
  return (
    <div className="flex flex-col gap-1">
      <span className={badgeClass}>{label}</span>
      <span className="text-xs text-slate-500">{formatDateTime(updatedAt)}</span>
    </div>
  );
}

function stageBadgeClass(stage: string | null): string {
  if (!stage) {
    return 'inline-flex w-max items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600';
  }
  switch (stage.toLowerCase()) {
    case 'collected':
      return 'inline-flex w-max items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-semibold text-emerald-700';
    case 'payment_plan':
      return 'inline-flex w-max items-center rounded-full border border-teal-500/30 bg-teal-500/10 px-2 py-0.5 text-xs font-semibold text-teal-700';
    case 'waiting_payment':
      return 'inline-flex w-max items-center rounded-full border border-sky-500/30 bg-sky-500/10 px-2 py-0.5 text-xs font-semibold text-sky-700';
    case 'levy_issued':
      return 'inline-flex w-max items-center rounded-full border border-indigo-500/30 bg-indigo-500/10 px-2 py-0.5 text-xs font-semibold text-indigo-700';
    case 'paperwork_filed':
      return 'inline-flex w-max items-center rounded-full border border-blue-500/30 bg-blue-500/10 px-2 py-0.5 text-xs font-semibold text-blue-700';
    case 'pre_enforcement':
      return 'inline-flex w-max items-center rounded-full border border-amber-500/30 bg-amber-500/10 px-2 py-0.5 text-xs font-semibold text-amber-700';
    case 'closed_no_recovery':
      return 'inline-flex w-max items-center rounded-full border border-slate-500/30 bg-slate-500/10 px-2 py-0.5 text-xs font-semibold text-slate-700';
    default:
      return 'inline-flex w-max items-center rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-600';
  }
}

function CollectabilityBadge({ tier, label, ageDays }: { tier: string | null; label: string; ageDays: number | null }) {
  const badgeClass = collectabilityBadgeClass(tier);
  const age = typeof ageDays === 'number' && Number.isFinite(ageDays) ? ageDays : null;
  return (
    <div className="flex flex-col gap-1">
      <span className={badgeClass}>{label}</span>
      {age !== null ? (
        <span className="text-xs text-slate-500">{age === 1 ? '1 day old' : `${age} days old`}</span>
      ) : null}
    </div>
  );
}

function ErrorState({ onRetry, message }: { onRetry: () => Promise<void>; message: string }) {
  const handleRetry = useCallback(() => {
    void onRetry();
  }, [onRetry]);

  return (
    <div className="flex flex-col items-center justify-center gap-3 px-6 py-12 text-center">
      <p className="text-base font-semibold text-slate-900">We couldn’t load cases.</p>
      <p className="max-w-sm text-sm text-slate-600">Please try again. {message}</p>
      <button
        type="button"
        onClick={handleRetry}
        className="inline-flex items-center rounded-full bg-blue-600 px-5 py-2 text-sm font-semibold text-white shadow-sm transition hover:bg-blue-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-500/40"
      >
        Retry
      </button>
    </div>
  );
}
