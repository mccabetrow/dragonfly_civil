import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import PageHeader from '../components/PageHeader';
import SectionHeader from '../components/SectionHeader';
import MetricCard from '../components/MetricCard';
import DemoLockCard from '../components/DemoLockCard';
import EmptyState from '../components/EmptyState';
import StatusMessage from '../components/StatusMessage';
import { DashboardError } from '../components/DashboardError';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import {
  CALL_QUEUE_LOCK_MESSAGE,
  PRIORITY_LOCK_MESSAGE,
  usePipelineMetrics,
  useOpenCallTasks,
  usePriorityPipeline,
  type CollectabilityTier,
  type PipelineLifecycleStatus,
  type PipelineTaskRow,
  type Jbi900SummaryMetrics,
  type PriorityPipelineRow,
} from '../hooks/usePipelineDashboard';
import { supabaseClient } from '../lib/supabaseClient';

type CallOutcome = 'completed' | 'cannot_contact' | 'do_not_pursue';

interface CallOutcomePayload {
  outcome: CallOutcome;
  notes: string;
  followUp: string;
}

interface LogOutcomeMapping {
  outcome: 'reached' | 'no_answer' | 'do_not_call';
  interest: 'hot' | 'warm' | 'cold' | 'none';
}

const CALL_OUTCOME_OPTIONS: Array<{ value: CallOutcome; label: string; helper: string }> = [
  { value: 'completed', label: 'Completed', helper: 'Plaintiff reached and outcome logged.' },
  { value: 'cannot_contact', label: 'Cannot Contact', helper: 'Multiple attempts, no connection yet.' },
  { value: 'do_not_pursue', label: 'Do Not Pursue', helper: 'Asked us to stop or not a fit.' },
];

function mapPipelineOutcome(outcome: CallOutcome): LogOutcomeMapping {
  switch (outcome) {
    case 'completed':
      return { outcome: 'reached', interest: 'hot' };
    case 'do_not_pursue':
      return { outcome: 'do_not_call', interest: 'none' };
    case 'cannot_contact':
    default:
      return { outcome: 'no_answer', interest: 'none' };
  }
}

const STATUS_LABELS: Record<PipelineLifecycleStatus, string> = {
  new: 'New leads',
  contacted: 'Contacted',
  qualified: 'Qualified',
  signed: 'Signed',
};

const STATUS_DESCRIPTIONS: Record<PipelineLifecycleStatus, string> = {
  new: 'Fresh Simplicity imports still waiting on first outreach.',
  contacted: 'Mom or Ops already touched base at least once.',
  qualified: 'Validated and reviewing terms or documents.',
  signed: 'Commitments in hand and onboarding with Dad.',
};

const TIER_COLORS: Record<CollectabilityTier, string> = {
  A: 'bg-emerald-100 text-emerald-800',
  B: 'bg-amber-100 text-amber-800',
  C: 'bg-slate-200 text-slate-600',
};

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const numberFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 0,
});

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
});

const DEFAULT_ASSIGNEE = 'mom_full_name_or_user_id';
const EMPTY_JBI_SUMMARY: Jbi900SummaryMetrics = {
  totalPlaintiffCount: 0,
  totalJudgmentAmount: 0,
  entries: [],
};
const DEFAULT_LIFECYCLE_COUNTS: Record<PipelineLifecycleStatus, number> = {
  new: 0,
  contacted: 0,
  qualified: 0,
  signed: 0,
};
const DEFAULT_TIER_TOTALS: Record<CollectabilityTier, number> = {
  A: 0,
  B: 0,
  C: 0,
};

const PipelineDashboard: React.FC = () => {
  const navigate = useNavigate();
  const { state: pipelineState, refetch: refetchPipelineMetrics } = usePipelineMetrics();
  const callTasksState = useOpenCallTasks({ limit: 12, assignee: DEFAULT_ASSIGNEE });
  const priorityState = usePriorityPipeline(20);

  const [selectedTask, setSelectedTask] = useState<PipelineTaskRow | null>(null);
  const [isSavingOutcome, setIsSavingOutcome] = useState(false);
  const [outcomeError, setOutcomeError] = useState<string | null>(null);

  const metrics = pipelineState.status === 'ready' ? pipelineState.data : null;
  const lifecycleCounts = metrics?.lifecycleCounts ?? DEFAULT_LIFECYCLE_COUNTS;
  const tierTotals = metrics?.tierTotals ?? DEFAULT_TIER_TOTALS;
  const jbiSummary = metrics?.jbi900Summary ?? EMPTY_JBI_SUMMARY;
  const simplicityPlaintiffCount = metrics?.simplicityPlaintiffCount ?? 0;

  const lifecycleEntries = useMemo(
    () =>
      (Object.keys(STATUS_LABELS) as PipelineLifecycleStatus[]).map((status) => ({
        key: status,
        label: STATUS_LABELS[status],
        description: STATUS_DESCRIPTIONS[status],
        value: lifecycleCounts[status] ?? 0,
      })),
    [lifecycleCounts],
  );

  const tierEntries = useMemo(
    () =>
      (['A', 'B', 'C'] as CollectabilityTier[]).map((tier) => ({
        tier,
        value: tierTotals[tier] ?? 0,
      })),
    [tierTotals],
  );

  const totalTierDollars = useMemo(
    () => tierEntries.reduce((sum, entry) => sum + entry.value, 0),
    [tierEntries],
  );

  const metricsLoading = pipelineState.status === 'idle' || pipelineState.status === 'loading';
  const metricsDemoLocked = pipelineState.status === 'demo_locked';
  const metricsErrorMessage =
    pipelineState.status === 'error'
      ? pipelineState.errorMessage ?? (typeof pipelineState.error === 'string' ? pipelineState.error : pipelineState.error?.message) ?? 'Unable to load pipeline metrics.'
      : null;
  const callTasks = callTasksState.data ?? [];
  const callLoading = callTasksState.status === 'idle' || callTasksState.status === 'loading';
  const callDemoLocked = callTasksState.status === 'demo_locked';
  const callErrorMessage =
    callTasksState.status === 'error' ? callTasksState.errorMessage ?? 'Unable to load call tasks.' : null;

  const priorityRows = priorityState.data ?? [];
  const priorityLoading = priorityState.status === 'idle' || priorityState.status === 'loading';
  const priorityDemoLocked = priorityState.status === 'demo_locked';
  const priorityErrorMessage =
    priorityState.status === 'error' ? priorityState.errorMessage ?? 'Unable to load priority pipeline.' : null;

  const pageLoading = metricsLoading || callLoading || priorityLoading;

  const summaryCards = [
    {
      key: 'simplicity',
      label: 'Simplicity plaintiffs',
      value: simplicityPlaintiffCount,
      footer: 'Total plaintiffs synced from the latest Simplicity exports.',
    },
    {
      key: 'qualified',
      label: 'Qualified',
      value: lifecycleCounts.qualified,
      footer: 'Validated and ready to send agreements.',
    },
    {
      key: 'signed',
      label: 'Signed',
      value: lifecycleCounts.signed,
      footer: 'Paperwork signed and being staged for enforcement.',
    },
  ];

  const handleOpenPlaintiff = (plaintiffId: string) => {
    if (!plaintiffId) {
      return;
    }
    navigate(`/plaintiffs/${encodeURIComponent(plaintiffId)}`);
  };

  const handleOpenJudgment = (judgmentId: string) => {
    if (!judgmentId) {
      return;
    }
    navigate(`/judgments/${encodeURIComponent(judgmentId)}`);
  };

  const handleOpenOutcome = (task: PipelineTaskRow) => {
    setOutcomeError(null);
    setSelectedTask(task);
  };

  const handleCloseOutcome = () => {
    if (isSavingOutcome) {
      return;
    }
    setSelectedTask(null);
  };

  const handleSubmitOutcome = async (payload: CallOutcomePayload) => {
    if (!selectedTask) {
      return;
    }
    setIsSavingOutcome(true);
    setOutcomeError(null);

    let followUpIso: string | null = null;
    if (payload.followUp) {
      const parsed = Date.parse(payload.followUp);
      if (Number.isNaN(parsed)) {
        setOutcomeError('Follow-up timestamp is invalid. Use YYYY-MM-DDTHH:MM.');
        setIsSavingOutcome(false);
        return;
      }
      followUpIso = new Date(parsed).toISOString();
    }

    try {
      const mapped = mapPipelineOutcome(payload.outcome);
      const { error } = await supabaseClient.rpc('log_call_outcome', {
        _plaintiff_id: selectedTask.plaintiffId,
        _task_id: selectedTask.taskId,
        _outcome: mapped.outcome,
        _interest: mapped.interest,
        _notes: payload.notes.trim() ? payload.notes.trim() : null,
        _follow_up_at: followUpIso,
      });

      if (error) {
        throw error;
      }

      await callTasksState.refetch();
      setSelectedTask(null);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unable to record call outcome.';
      setOutcomeError(message);
    } finally {
      setIsSavingOutcome(false);
    }
  };

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Pipeline"
        title="Pipeline dashboard"
        subtitle="Supabase production parity"
      >
        <p className="text-sm text-white/80">
          Shows Simplicity ingestion, lifecycle counts, Mom’s call queue, and the priority stack Dad should attack first.
        </p>
      </PageHeader>

      <section className="df-card space-y-4">
        <SectionHeader
          eyebrow="Snapshot"
          title="Pipeline summary"
          description="All of these metrics originate from Supabase so the dashboard mirrors production."
        />
        {metricsDemoLocked ? (
          <DemoLockCard description={pipelineState.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
        ) : metricsErrorMessage ? (
          <DashboardError message={metricsErrorMessage} title="Pipeline snapshot unavailable" onRetry={() => void refetchPipelineMetrics()} />
        ) : (
          <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
            {summaryCards.map((card) => (
              <MetricCard
                key={card.key}
                label={card.label}
                value={metricsLoading ? '…' : numberFormatter.format(card.value)}
                loading={metricsLoading}
                footer={card.footer}
              />
            ))}
          </div>
        )}
      </section>

      {!metricsDemoLocked && !metricsErrorMessage && (
        <>
          <section className="grid gap-4 lg:grid-cols-3">
            <article className="df-card space-y-4 lg:col-span-2">
              <SectionHeader
                eyebrow="Lifecycle"
                title="Where plaintiffs sit"
                description="Counts sourced from plaintiffs.status so pipe reviews stay honest."
              />
              {metricsLoading ? (
                <p className="text-sm text-slate-500">Calculating lifecycle counts…</p>
              ) : (
                <dl className="grid gap-4 sm:grid-cols-2">
                  {lifecycleEntries.map((entry) => (
                    <div key={entry.key} className="rounded-2xl border border-slate-100 bg-slate-50/50 p-4">
                      <dt className="text-xs font-semibold uppercase tracking-widest text-slate-500">{entry.label}</dt>
                      <dd className="mt-2 text-3xl font-semibold text-slate-900">{entry.value.toLocaleString()}</dd>
                      <p className="mt-2 text-xs text-slate-500">{entry.description}</p>
                    </div>
                  ))}
                </dl>
              )}
            </article>

            <article className="df-card space-y-4">
              <SectionHeader
                eyebrow="Collectability"
                title="Tier distribution"
                description="Pulled from v_collectability_snapshot so Ops knows where the dollars sit."
              />
              {metricsLoading ? (
                <p className="text-sm text-slate-500">Summing collectability tiers…</p>
              ) : (
                <ul className="space-y-4">
                  {tierEntries.map((entry) => (
                    <li key={entry.tier}>
                      <div className="flex items-center justify-between text-sm font-semibold text-slate-900">
                        <span>Tier {entry.tier}</span>
                        <span>{currencyFormatter.format(entry.value)}</span>
                      </div>
                      <div className="mt-2 h-2 rounded-full bg-slate-200">
                        <div
                          className={`h-2 rounded-full ${TIER_COLORS[entry.tier]}`}
                          style={{
                            width: totalTierDollars > 0 ? `${Math.min(100, Math.round((entry.value / totalTierDollars) * 100))}%` : '4%',
                          }}
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </article>
          </section>

          <section className="df-card space-y-4">
            <SectionHeader
              eyebrow="JBI 900"
              title="Vendor intake health"
              description="Tracks the latest status mix from v_plaintiffs_jbi_900."
            />
            {metricsLoading ? (
              <p className="text-sm text-slate-500">Crunching JBI stats…</p>
            ) : jbiSummary.entries.length === 0 ? (
              <EmptyState title="No JBI 900 rows yet" description="Import the latest vendor drop to populate this card." />
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                <article className="rounded-2xl border border-slate-100 bg-slate-50/50 p-4">
                  <p className="text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Total plaintiffs</p>
                  <p className="mt-2 text-3xl font-semibold text-slate-900">{jbiSummary.totalPlaintiffCount.toLocaleString()}</p>
                  <p className="mt-4 text-xs font-semibold uppercase tracking-[0.3em] text-slate-500">Total judgment</p>
                  <p className="mt-2 text-2xl font-semibold text-slate-900">{currencyFormatter.format(jbiSummary.totalJudgmentAmount)}</p>
                </article>
                <ul className="space-y-3">
                  {jbiSummary.entries.map((entry) => (
                    <li key={entry.status} className="rounded-2xl border border-slate-100 bg-white/80 px-4 py-3">
                      <p className="text-sm font-semibold text-slate-900">{formatStatus(entry.status)}</p>
                      <p className="text-xs text-slate-500">
                        {entry.plaintiffCount.toLocaleString()} plaintiffs · {currencyFormatter.format(entry.totalJudgmentAmount)}
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </section>
        </>
      )}

      <section className="df-card space-y-4">
        <SectionHeader
          eyebrow="Call queue"
          title="Mom’s live call tasks"
          description="Backed by v_plaintiff_open_tasks limited to the Mom assignee."
        />
        {callLoading ? (
          <p className="text-sm text-slate-500">Loading call queue…</p>
        ) : callDemoLocked ? (
          <DemoLockCard description={callTasksState.lockMessage ?? CALL_QUEUE_LOCK_MESSAGE} />
        ) : callErrorMessage ? (
          <DashboardError
            title="Unable to load call tasks"
            message={callErrorMessage}
            onRetry={() => void callTasksState.refetch()}
          />
        ) : callTasks.length === 0 ? (
          <EmptyState
            title="No open call tasks"
            description="Once Mom is assigned new calls they’ll show up here."
            actionLabel="Refresh"
            onAction={() => void callTasksState.refetch()}
          />
        ) : (
          <CallTasksTable rows={callTasks} onOpenPlaintiff={handleOpenPlaintiff} onLogOutcome={handleOpenOutcome} />
        )}
      </section>

      <section className="df-card space-y-4">
        <SectionHeader
          eyebrow="Priority pipeline"
          title="Judgments Dad should work first"
          description="Ranks v_priority_pipeline by tier, collectability, and dollars."
        />
        {priorityLoading ? (
          <p className="text-sm text-slate-500">Ranking judgments…</p>
        ) : priorityDemoLocked ? (
          <DemoLockCard description={PRIORITY_LOCK_MESSAGE} />
        ) : priorityErrorMessage ? (
          <DashboardError
            title="Unable to load priority pipeline"
            message={priorityErrorMessage}
            onRetry={() => void priorityState.refetch()}
          />
        ) : priorityRows.length === 0 ? (
          <EmptyState
            title="No judgments matched the filters"
            description="Adjust the limit in usePriorityPipeline or refresh after the next import."
          />
        ) : (
          <PriorityTable rows={priorityRows} onOpenJudgment={handleOpenJudgment} />
        )}
      </section>
  {pageLoading && <StatusMessage tone="info">Refreshing pipeline insights…</StatusMessage>}

      {selectedTask ? (
        <CallOutcomeModal
          task={selectedTask}
          isSubmitting={isSavingOutcome}
          errorMessage={outcomeError}
          onClose={handleCloseOutcome}
          onSubmit={handleSubmitOutcome}
        />
      ) : null}
    </div>
  );
};

export default PipelineDashboard;
export { PipelineDashboard };

interface CallTasksTableProps {
  rows: PipelineTaskRow[];
  onOpenPlaintiff: (plaintiffId: string) => void;
  onLogOutcome: (row: PipelineTaskRow) => void;
}

const CallTasksTable: React.FC<CallTasksTableProps> = ({ rows, onOpenPlaintiff, onLogOutcome }) => {
  return (
    <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-left text-sm text-slate-700">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Plaintiff</th>
              <th className="px-4 py-3">Contact</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Due</th>
              <th className="px-4 py-3">Judgment</th>
              <th className="px-4 py-3">Tier</th>
              <th className="px-4 py-3">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {rows.map((row) => (
              <tr key={row.taskId} className="hover:bg-slate-50">
                <td className="px-4 py-3">
                  <button
                    type="button"
                    onClick={() => onOpenPlaintiff(row.plaintiffId)}
                    className="text-left font-semibold text-slate-900 underline-offset-2 hover:underline"
                  >
                    {row.plaintiffName}
                  </button>
                  <div className="text-xs text-slate-500">Task #{row.taskId.slice(0, 8)}</div>
                </td>
                <td className="px-4 py-3 text-sm text-slate-600">
                  <div>{row.phone || '—'}</div>
                  <div className="text-xs text-slate-500">{row.email || '—'}</div>
                </td>
                <td className="px-4 py-3 text-sm">
                  <span className="rounded-full bg-slate-100 px-2 py-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    {row.status}
                  </span>
                </td>
                <td className="px-4 py-3 text-sm text-slate-600">{formatDate(row.dueAt)}</td>
                <td className="px-4 py-3 text-sm font-semibold text-slate-900">
                  {currencyFormatter.format(row.judgmentTotal)}
                </td>
                <td className="px-4 py-3 text-sm">
                  <TierBadge tier={row.topTier} />
                </td>
                <td className="px-4 py-3 text-sm">
                  <button
                    type="button"
                    className="rounded-md border border-slate-300 px-3 py-1 text-xs font-semibold uppercase tracking-wide text-slate-700 transition hover:border-slate-400 hover:bg-slate-50"
                    onClick={() => onLogOutcome(row)}
                  >
                    Outcome
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

interface PriorityTableProps {
  rows: PriorityPipelineRow[];
  onOpenJudgment: (judgmentId: string) => void;
}

const PriorityTable: React.FC<PriorityTableProps> = ({ rows, onOpenJudgment }) => {
  return (
    <div className="mt-6 overflow-hidden rounded-2xl border border-slate-200">
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-200 text-left text-sm text-slate-700">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-4 py-3">Plaintiff</th>
              <th className="px-4 py-3">Tier</th>
              <th className="px-4 py-3">Priority</th>
              <th className="px-4 py-3">Rank</th>
              <th className="px-4 py-3">Judgment</th>
              <th className="px-4 py-3">Stage</th>
              <th className="px-4 py-3">Status</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {rows.map((row) => (
              <tr
                key={row.judgmentId}
                tabIndex={0}
                onClick={() => onOpenJudgment(row.judgmentId)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter' || event.key === ' ') {
                    event.preventDefault();
                    onOpenJudgment(row.judgmentId);
                  }
                }}
                className="cursor-pointer transition hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-slate-400/60"
              >
                <td className="px-4 py-3 font-semibold text-slate-900">
                  {row.plaintiffName}
                  <div className="text-xs text-slate-500">Judgment #{row.judgmentId}</div>
                </td>
                <td className="px-4 py-3 text-sm">
                  <TierBadge tier={row.collectabilityTier} />
                </td>
                <td className="px-4 py-3 text-sm">
                  <PriorityBadge priority={row.priorityLevel} />
                </td>
                <td className="px-4 py-3 text-sm text-slate-600">#{row.tierRank}</td>
                <td className="px-4 py-3 text-sm font-semibold text-slate-900">
                  {currencyFormatter.format(row.judgmentAmount)}
                </td>
                <td className="px-4 py-3 text-sm text-slate-600">{row.stage ?? '—'}</td>
                <td className="px-4 py-3 text-sm text-slate-600">{row.plaintiffStatus ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
};

const TierBadge: React.FC<{ tier: string | null }> = ({ tier }) => {
  if (!tier) {
    return <span className="rounded-full bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-600">Tier —</span>;
  }
  const normalized = tier.toUpperCase() as CollectabilityTier;
  const tone = TIER_COLORS[normalized] ?? 'bg-slate-200 text-slate-600';
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase tracking-wide ${tone}`}>
      Tier {normalized}
    </span>
  );
};

const PriorityBadge: React.FC<{ priority: string | null }> = ({ priority }) => {
  if (!priority) {
    return <span className="rounded-full bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-600">Unranked</span>;
  }
  const normalized = priority.trim().toUpperCase();
  const tone =
    normalized === 'HIGH'
      ? 'bg-rose-100 text-rose-800'
      : normalized === 'MEDIUM'
        ? 'bg-amber-100 text-amber-800'
        : 'bg-slate-200 text-slate-600';
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase tracking-wide ${tone}`}>
      {normalized}
    </span>
  );
};

interface CallOutcomeModalProps {
  task: PipelineTaskRow;
  isSubmitting: boolean;
  errorMessage: string | null;
  onClose: () => void;
  onSubmit: (payload: CallOutcomePayload) => Promise<void> | void;
}

const CallOutcomeModal: React.FC<CallOutcomeModalProps> = ({ task, isSubmitting, errorMessage, onClose, onSubmit }) => {
  const [outcome, setOutcome] = useState<CallOutcome>('completed');
  const [notes, setNotes] = useState('');
  const [followUp, setFollowUp] = useState(() => formatDatetimeLocal(task.dueAt));

  useEffect(() => {
    setOutcome('completed');
    setNotes('');
    setFollowUp(formatDatetimeLocal(task.dueAt));
  }, [task]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void onSubmit({ outcome, notes, followUp });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 px-4">
      <div className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Log call outcome</p>
            <h3 className="text-xl font-semibold text-slate-900">{task.plaintiffName}</h3>
            <p className="text-sm text-slate-500">Task ID {task.taskId}</p>
          </div>
          <button
            type="button"
            className="text-sm font-semibold text-slate-500 hover:text-slate-700"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Close
          </button>
        </div>

        <form className="mt-4 space-y-4" onSubmit={handleSubmit}>
          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Outcome</label>
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              value={outcome}
              onChange={(event) => setOutcome(event.target.value as CallOutcome)}
              disabled={isSubmitting}
            >
              {CALL_OUTCOME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            <p className="mt-1 text-xs text-slate-500">
              {CALL_OUTCOME_OPTIONS.find((option) => option.value === outcome)?.helper}
            </p>
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Notes</label>
            <textarea
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              rows={3}
              placeholder="Who you spoke with, next steps, etc."
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              disabled={isSubmitting}
            />
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Next follow-up (optional)</label>
            <input
              type="datetime-local"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-900"
              value={followUp}
              onChange={(event) => setFollowUp(event.target.value)}
              disabled={isSubmitting}
            />
            <p className="mt-1 text-xs text-slate-500">Use local time; we convert to UTC for Supabase.</p>
          </div>

          {errorMessage && <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{errorMessage}</p>}

          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-50"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white hover:bg-slate-800 disabled:opacity-60"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Saving…' : 'Log Outcome'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

function formatDate(value: string | null): string {
  if (!value) {
    return '—';
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return '—';
  }
  return dateFormatter.format(parsed);
}

function formatDatetimeLocal(value: string | null): string {
  if (!value) {
    return '';
  }
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) {
    return '';
  }
  return new Date(parsed).toISOString().slice(0, 16);
}

function formatStatus(value: string): string {
  if (!value) {
    return 'Unspecified';
  }
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\b\w/g, (match) => match.toUpperCase());
}

