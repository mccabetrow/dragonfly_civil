import { useCallback, useMemo, type ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import MetricsGate from '../components/MetricsGate';
import { InlineSpinner } from '../components/InlineSpinner.tsx';
import { useJudgmentDetail, type JudgmentDetailData, type JudgmentTaskRow } from '../hooks/useJudgmentDetail';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsState,
} from '../hooks/metricsState';
import { formatCurrency, formatDateTime } from '../utils/formatters';

export default function JudgmentDetailPage() {
  const params = useParams<{ judgmentId?: string }>();
  const navigate = useNavigate();

  const decodedId = useMemo(() => {
    if (!params.judgmentId) {
      return '';
    }
    try {
      return decodeURIComponent(params.judgmentId);
    } catch (err) {
      console.warn('[JudgmentDetailPage] failed to decode id', err);
      return params.judgmentId;
    }
  }, [params.judgmentId]);

  const { state, data, error, lockMessage, refetch } = useJudgmentDetail(decodedId);
  const summaryPlaintiffId = data?.summary.plaintiffId ?? null;
  const summaryCaseNumber = data?.summary.caseNumber ?? null;

  const handleOpenPlaintiff = useCallback(() => {
    if (summaryPlaintiffId) {
      navigate(`/plaintiffs/${encodeURIComponent(summaryPlaintiffId)}`);
    }
  }, [navigate, summaryPlaintiffId]);

  const handleOpenCase = useCallback(() => {
    if (summaryCaseNumber) {
      navigate(`/cases/number/${encodeURIComponent(summaryCaseNumber)}`);
    }
  }, [navigate, summaryCaseNumber]);

  const metricsSnapshot = useMemo<MetricsState<JudgmentDetailData | null>>(() => {
    switch (state) {
      case 'idle':
        return buildInitialMetricsState<JudgmentDetailData | null>();
      case 'loading':
        return buildLoadingMetricsState<JudgmentDetailData | null>();
      case 'demo_locked':
        return buildDemoLockedState<JudgmentDetailData | null>(lockMessage ?? undefined);
      case 'error': {
        const friendly = error ?? 'Failed to load judgment detail.';
        return buildErrorMetricsState<JudgmentDetailData | null>(new Error(friendly), { message: friendly });
      }
      case 'ready':
      case 'not-found':
        return buildReadyMetricsState<JudgmentDetailData | null>(data ?? null);
      default:
        return buildInitialMetricsState<JudgmentDetailData | null>();
    }
  }, [state, data, error, lockMessage]);

  let readyContent: ReactNode;
  if (state === 'not-found' || !data) {
    readyContent = <JudgmentNotFoundCard />;
  } else {
    const { summary, enforcementHistory, priorityHistory, tasks } = data;

    readyContent = (
      <div className="space-y-6">
        <header className="flex flex-col gap-5 rounded-3xl border border-slate-200 bg-white px-6 py-6 shadow-sm lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Judgment detail</p>
            <h1 className="mt-1 text-2xl font-semibold text-slate-900">
              {summary.caseNumber ? `Case ${summary.caseNumber}` : `Judgment ${summary.id}`}
            </h1>
            <p className="text-sm text-slate-600">{summary.plaintiffName}</p>
            <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-2 text-sm text-slate-600 sm:grid-cols-2 lg:grid-cols-3">
              <DetailRow label="Plaintiff" value={summary.plaintiffName} />
              <DetailRow label="Defendant" value={summary.defendantName ?? '—'} />
              <DetailRow label="Location" value={formatLocation(summary.county, summary.state)} />
              <DetailRow label="Stage" value={summary.enforcementStageLabel ?? '—'} />
              <DetailRow label="Stage updated" value={formatDateTime(summary.enforcementStageUpdatedAt)} />
              <DetailRow label="Judgment" value={formatCurrency(summary.judgmentAmount)} />
              <DetailRow label="Collectability tier" value={summary.collectabilityTier ?? '—'} />
              <DetailRow label="Collectability age" value={formatAge(summary.collectabilityAgeDays)} />
              <DetailRow label="Last enrichment" value={formatDateTime(summary.lastEnrichedAt)} />
              <DetailRow label="Priority" value={<PriorityBadge level={summary.priorityLevel} label={summary.priorityLabel} />} />
              <DetailRow label="Priority updated" value={formatDateTime(summary.priorityUpdatedAt)} />
              <DetailRow label="Plaintiff status" value={summary.plaintiffStatus ?? '—'} />
            </dl>
          </div>
          <div className="flex flex-col gap-2 sm:flex-row">
            <button
              type="button"
              onClick={refetch}
              className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
            >
              Refresh
            </button>
            <button
              type="button"
              onClick={handleOpenCase}
              disabled={!summary.caseNumber}
              className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Open case
            </button>
            <button
              type="button"
              onClick={handleOpenPlaintiff}
              disabled={!summary.plaintiffId}
              className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:cursor-not-allowed disabled:opacity-60"
            >
              Open plaintiff
            </button>
          </div>
        </header>

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <TimelineCard
            title="Enforcement history"
            emptyMessage="No enforcement events recorded yet."
            entries={enforcementHistory.map((event) => ({
              id: event.id,
              primary: event.stageLabel ?? event.stage ?? 'Unknown stage',
              secondary: formatDateTime(event.changedAt),
              meta: event.changedBy ? `By ${event.changedBy}` : undefined,
              note: event.note ?? undefined,
            }))}
          />
          <TimelineCard
            title="Priority changes"
            emptyMessage="No manual priority changes recorded."
            entries={priorityHistory.map((event) => ({
              id: event.id,
              primary: event.priorityLabel,
              secondary: formatDateTime(event.changedAt),
              meta: event.changedBy ? `By ${event.changedBy}` : undefined,
              note: event.note ?? undefined,
            }))}
          />
        </section>

        <TasksCard tasks={tasks} />
      </div>
    );
  }

  const loadingFallback = (
    <div className="flex h-full flex-col items-center justify-center gap-3 py-16">
      <InlineSpinner label="Loading judgment" />
      <p className="text-sm text-slate-500">Fetching the latest enforcement details.</p>
    </div>
  );

  return (
    <MetricsGate
      state={metricsSnapshot}
      loadingFallback={loadingFallback}
      errorTitle="Judgment detail error"
      onRetry={refetch}
      ready={readyContent}
    />
  );
}

function JudgmentNotFoundCard() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-3xl border border-slate-200 bg-white py-14">
      <p className="text-lg font-semibold text-slate-800">Judgment not found</p>
      <p className="text-sm text-slate-500">We could not locate that judgment in Supabase.</p>
      <Link
        to="/cases"
        className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
      >
        Back to overview
      </Link>
    </div>
  );
}

function DetailRow({ label, value }: { label: string; value: ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-slate-400">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-slate-700">{value}</dd>
    </div>
  );
}

function formatLocation(county: string | null, state: string | null): string {
  if (!county && !state) {
    return '—';
  }
  if (county && state) {
    return `${county}, ${state}`;
  }
  return county ?? state ?? '—';
}

function formatAge(value: number | null): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '—';
  }
  if (value === 1) {
    return '1 day';
  }
  return `${value.toLocaleString()} days`;
}

function PriorityBadge({ level, label }: { level: string; label: string }) {
  const tone = level === 'urgent'
    ? 'bg-rose-100 text-rose-800 border-rose-200'
    : level === 'high'
      ? 'bg-amber-100 text-amber-800 border-amber-200'
      : level === 'low'
        ? 'bg-slate-100 text-slate-600 border-slate-200'
        : level === 'on_hold'
          ? 'bg-slate-200 text-slate-700 border-slate-300'
          : 'bg-emerald-100 text-emerald-800 border-emerald-200';
  return <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-semibold ${tone}`}>{label}</span>;
}

interface TimelineEntry {
  id: string;
  primary: string;
  secondary?: string;
  meta?: string;
  note?: string;
}

function TimelineCard({ title, entries, emptyMessage }: { title: string; entries: TimelineEntry[]; emptyMessage: string }) {
  return (
    <div className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">{title}</h2>
      </header>
      <div className="flex-1 px-5 py-4">
        {entries.length === 0 ? (
          <p className="text-sm text-slate-500">{emptyMessage}</p>
        ) : (
          <ol className="space-y-4">
            {entries.map((entry) => (
              <li key={entry.id} className="flex items-start gap-3">
                <span className="mt-1 h-2 w-2 rounded-full bg-slate-300" aria-hidden />
                <div>
                  <p className="text-sm font-semibold text-slate-800">{entry.primary}</p>
                  {entry.secondary ? <p className="text-xs text-slate-500">{entry.secondary}</p> : null}
                  {entry.meta ? <p className="text-xs text-slate-500">{entry.meta}</p> : null}
                  {entry.note ? <p className="text-sm text-slate-600">{entry.note}</p> : null}
                </div>
              </li>
            ))}
          </ol>
        )}
      </div>
    </div>
  );
}

function TasksCard({ tasks }: { tasks: JudgmentTaskRow[] }) {
  if (tasks.length === 0) {
    return (
      <div className="rounded-3xl border border-slate-200 bg-white px-6 py-6 text-sm text-slate-600 shadow-sm">
        <h2 className="text-base font-semibold text-slate-900">Enforcement tasks</h2>
        <p className="mt-2 text-sm text-slate-500">No enforcement tasks have been logged for this case.</p>
      </div>
    );
  }

  return (
    <div className="rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="flex items-center justify-between border-b border-slate-100 px-5 py-4">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Enforcement tasks</h2>
          <p className="text-xs text-slate-500">Sorted by most recent activity.</p>
        </div>
      </header>
      <div className="overflow-x-auto">
        <table className="min-w-full divide-y divide-slate-100 text-left text-sm text-slate-700">
          <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
            <tr>
              <th className="px-5 py-3">Label</th>
              <th className="px-5 py-3">Status</th>
              <th className="px-5 py-3">Due</th>
              <th className="px-5 py-3">Created</th>
              <th className="px-5 py-3">Assignee</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 bg-white">
            {tasks.map((task) => (
              <tr key={task.id}>
                <td className="px-5 py-3 font-semibold text-slate-900">
                  {task.label}
                  {task.stepType ? <div className="text-xs text-slate-500">{task.stepType}</div> : null}
                </td>
                <td className="px-5 py-3">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${taskStatusTone(task.status)}`}>
                    {formatStatus(task.status)}
                  </span>
                </td>
                <td className="px-5 py-3">{task.dueAt ? formatDateTime(task.dueAt) : '—'}</td>
                <td className="px-5 py-3">{task.createdAt ? formatDateTime(task.createdAt) : '—'}</td>
                <td className="px-5 py-3">{task.assignee ?? '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatStatus(value: string): string {
  return value
    .split(/[_\s]+/)
    .map((segment) => (segment ? segment[0].toUpperCase() + segment.slice(1) : ''))
    .join(' ');
}

function taskStatusTone(status: string): string {
  const normalized = status.trim().toLowerCase();
  if (['done', 'completed', 'closed'].includes(normalized)) {
    return 'bg-emerald-100 text-emerald-800';
  }
  if (['in_progress', 'active'].includes(normalized)) {
    return 'bg-amber-100 text-amber-800';
  }
  if (['blocked', 'failed', 'cancelled'].includes(normalized)) {
    return 'bg-rose-100 text-rose-800';
  }
  return 'bg-slate-100 text-slate-700';
}
