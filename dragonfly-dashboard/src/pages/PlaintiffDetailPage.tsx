import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import MetricsGate from '../components/MetricsGate';
import { InlineSpinner } from '../components/InlineSpinner.tsx';
import { ActivityFeed } from '../components/ActivityFeed.tsx';
import { usePlaintiffDetail } from '../hooks/usePlaintiffDetail';
import {
  DEFAULT_DEMO_LOCK_MESSAGE,
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsState,
} from '../hooks/metricsState';
import { supabaseClient } from '../lib/supabaseClient';
import { PLAINTIFF_STATUS_DISPLAY, PLAINTIFF_STATUS_LABELS } from '../constants/plaintiffStatus';
import { setPlaintiffStatus, type PlaintiffStatus } from '../utils/plaintiffStatusClient';
import type {
  PlaintiffDetailData,
  PlaintiffJudgmentRow,
  PlaintiffStatusEvent,
  PipelineSummary,
} from '../hooks/usePlaintiffDetail';
import { formatCurrency, formatDateTime } from '../utils/formatters';

const LazyPlaintiffTasksSection = lazy(() => import('../components/PlaintiffTasksSection'));

export default function PlaintiffDetailPage() {
  const params = useParams<{ plaintiffId?: string }>();
  const navigate = useNavigate();
  const decodedId = useMemo(() => {
    if (!params.plaintiffId) {
      return '';
    }
    try {
      return decodeURIComponent(params.plaintiffId);
    } catch (err) {
      console.warn('[PlaintiffDetailPage] failed to decode plaintiff id', err);
      return params.plaintiffId;
    }
  }, [params.plaintiffId]);

  const { state, data, error, lockMessage, refetch } = usePlaintiffDetail(decodedId);

  const metricsSnapshot = useMemo<MetricsState<PlaintiffDetailData | null>>(() => {
    switch (state) {
      case 'idle':
        return buildInitialMetricsState<PlaintiffDetailData | null>();
      case 'loading':
        return buildLoadingMetricsState<PlaintiffDetailData | null>();
      case 'demo_locked':
        return buildDemoLockedState<PlaintiffDetailData | null>(lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE);
      case 'error': {
        const friendly = error ?? 'Failed to load plaintiff detail.';
        return buildErrorMetricsState<PlaintiffDetailData | null>(new Error(friendly), { message: friendly });
      }
      case 'ready':
      case 'not-found':
        return buildReadyMetricsState<PlaintiffDetailData | null>(data ?? null);
      default:
        return buildInitialMetricsState<PlaintiffDetailData | null>();
    }
  }, [state, data, error, lockMessage]);

  const handleCaseNavigate = useCallback(
    (row: PlaintiffJudgmentRow) => {
      if (row.caseNumber) {
        navigate(`/cases/number/${encodeURIComponent(row.caseNumber)}`);
      }
    },
    [navigate],
  );

  let readyContent: ReactNode;
  if (state === 'not-found' || !data) {
    readyContent = <PlaintiffNotFoundCard />;
  } else {
    const { summary, contacts, judgments, statusHistory } = data;
    const normalizedStatusCode = summary.status.code === 'unknown' ? null : (summary.status.code as PlaintiffStatus);

    readyContent = (
      <div className="space-y-6">
        <header className="flex flex-col gap-4 rounded-3xl border border-slate-200 bg-white px-6 py-6 shadow-sm sm:flex-row sm:items-end sm:justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Plaintiff detail</p>
            <h1 className="mt-1 text-2xl font-semibold text-slate-900">{summary.name}</h1>
            <dl className="mt-4 grid grid-cols-1 gap-x-8 gap-y-2 text-sm text-slate-600 sm:grid-cols-2 lg:grid-cols-3">
              <DetailRow label="Firm" value={summary.firmName ?? '—'} />
              <DetailRow label="Primary email" value={summary.email ?? '—'} />
              <DetailRow label="Primary phone" value={summary.phone ?? '—'} />
              <DetailRow label="Status" value={<StatusBadge label={summary.status.label} />} />
              <DetailRow label="Total judgment" value={formatCurrency(summary.totalJudgmentAmount)} />
              <DetailRow label="Cases" value={summary.caseCount.toLocaleString()} />
              <DetailRow label="Enforcement active" value={formatCount(summary.pipeline.enforcementActive)} />
              <DetailRow label="Enforcement planning" value={formatCount(summary.pipeline.enforcementPlanning)} />
              <DetailRow label="Outreach" value={formatCount(summary.pipeline.outreach)} />
              <DetailRow label="Collected" value={formatCount(summary.pipeline.collected)} />
              <DetailRow label="Created" value={formatDateTime(summary.createdAt)} />
              <DetailRow label="Updated" value={formatDateTime(summary.updatedAt)} />
            </dl>
          </div>
          <button
            type="button"
            onClick={refetch}
            className="self-start rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
          >
            Refresh
          </button>
        </header>

        <StatusActions
          plaintiffId={summary.id}
          currentStatus={normalizedStatusCode}
          currentLabel={summary.status.label}
          onStatusUpdated={refetch}
        />

        <Suspense fallback={<TasksSectionFallback />}>
          <LazyPlaintiffTasksSection plaintiffId={decodedId} />
        </Suspense>

        <PlaintiffActivitySection judgments={judgments} />

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-3">
          <JudgmentsCard
            judgments={judgments}
            onNavigate={handleCaseNavigate}
            className="lg:col-span-2"
            pipeline={summary.pipeline}
          />
          <ContactsCard contacts={contacts} />
        </section>

        <section className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          <StatusHistoryCard events={statusHistory} />
          <NotesCard detail={data} />
        </section>
      </div>
    );
  }

  const loadingFallback = (
    <div className="flex h-full flex-col items-center justify-center gap-3 py-16">
      <InlineSpinner label="Loading plaintiff" />
      <p className="text-sm text-slate-500">Fetching the latest portfolio details.</p>
    </div>
  );

  return (
    <MetricsGate
      state={metricsSnapshot}
      loadingFallback={loadingFallback}
      errorTitle="Plaintiff detail error"
      onRetry={refetch}
      ready={readyContent}
    />
  );
}

function PlaintiffNotFoundCard() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 rounded-3xl border border-slate-200 bg-white py-14">
      <p className="text-lg font-semibold text-slate-800">Plaintiff not found</p>
      <p className="text-sm text-slate-500">We could not locate that plaintiff in the system.</p>
      <Link
        to="/cases"
        className="rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100"
      >
        Back to overview
      </Link>
    </div>
  );
}

interface StatusActionsProps {
  plaintiffId: string;
  currentStatus: PlaintiffStatus | null;
  currentLabel: string;
  onStatusUpdated: () => Promise<void>;
}

function StatusActions({ plaintiffId, currentStatus, currentLabel, onStatusUpdated }: StatusActionsProps) {
  const [note, setNote] = useState('');
  const [isUpdating, setIsUpdating] = useState(false);
  const [pendingStatus, setPendingStatus] = useState<PlaintiffStatus | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  useEffect(() => {
    if (!message) {
      return;
    }
    const timer = window.setTimeout(() => setMessage(null), 4000);
    return () => window.clearTimeout(timer);
  }, [message]);

  useEffect(() => {
    if (!error) {
      return;
    }
    const timer = window.setTimeout(() => setError(null), 6000);
    return () => window.clearTimeout(timer);
  }, [error]);

  const handleStatusUpdate = async (nextStatus: PlaintiffStatus) => {
    if (!plaintiffId) {
      return;
    }

    const trimmedNote = note.trim();
    if (currentStatus === nextStatus && trimmedNote.length === 0) {
      setMessage('Status already set.');
      return;
    }

    setIsUpdating(true);
    setPendingStatus(nextStatus);
    setError(null);
    setMessage(null);

    try {
      await setPlaintiffStatus(
        supabaseClient,
        plaintiffId,
        nextStatus,
        trimmedNote.length > 0 ? trimmedNote : undefined,
      );
      setNote('');
      setMessage(`Status updated to ${PLAINTIFF_STATUS_LABELS[nextStatus]}.`);
      await onStatusUpdated();
    } catch (err) {
      const fallback = err instanceof Error && err.message ? err.message : 'Failed to update status.';
      setError(fallback);
    } finally {
      setIsUpdating(false);
      setPendingStatus(null);
    }
  };

  return (
    <section className="rounded-3xl border border-slate-200 bg-white px-6 py-5 shadow-sm">
      <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
        <div className="space-y-2">
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Status controls</p>
          <p className="text-sm text-slate-600">
            Current status: <span className="font-semibold text-slate-900">{currentLabel}</span>
          </p>
          <div className="flex flex-wrap gap-2">
            {PLAINTIFF_STATUS_DISPLAY.map((option) => {
              const isActive = currentStatus === option.code;
              const isPending = pendingStatus === option.code;
              const baseClass = isActive
                ? 'border-slate-900 bg-slate-900 text-white'
                : 'border-slate-300 text-slate-700 hover:bg-slate-100';
              return (
                <button
                  key={option.code}
                  type="button"
                  onClick={() => void handleStatusUpdate(option.code)}
                  disabled={isUpdating}
                  className={`inline-flex items-center gap-2 rounded-full border px-3 py-1.5 text-xs font-semibold transition disabled:cursor-not-allowed disabled:opacity-60 ${baseClass}`}
                >
                  {isUpdating && isPending ? (
                    <span className="flex items-center gap-2">
                      <InlineSpinner />
                      Updating…
                    </span>
                  ) : (
                    option.label
                  )}
                </button>
              );
            })}
          </div>
        </div>
        <div className="w-full max-w-sm space-y-2">
          <label className="text-xs font-semibold uppercase tracking-wide text-slate-400" htmlFor="status-note">
            Progress note (optional)
          </label>
          <textarea
            id="status-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            rows={3}
            placeholder="Add context before updating the status."
            disabled={isUpdating}
            className="w-full rounded-xl border border-slate-300 px-3 py-2 text-sm text-slate-700 transition focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
          />
          <p className="text-xs text-slate-500">Notes are recorded when a status action is taken.</p>
        </div>
      </div>
      {message ? <p className="mt-4 text-sm font-medium text-emerald-700">{message}</p> : null}
      {error ? <p className="mt-4 text-sm font-medium text-rose-600">{error}</p> : null}
    </section>
  );
}

function TasksSectionFallback() {
  return (
    <section className="rounded-3xl border border-slate-200 bg-white px-6 py-6 shadow-sm">
      <div className="flex items-center gap-3 text-sm text-slate-600">
        <InlineSpinner />
        <span>Loading tasks…</span>
      </div>
    </section>
  );
}

function PlaintiffActivitySection({ judgments }: { judgments: PlaintiffJudgmentRow[] }) {
  const [selectedCaseId, setSelectedCaseId] = useState<string | null>(null);
  const caseOptions = useMemo(() => {
    return judgments
      .filter((row) => Boolean(row.enforcementCaseId))
      .map((row) => ({
        caseId: row.enforcementCaseId as string,
        label: row.caseNumber ?? `Judgment ${row.judgmentId.slice(-6)}`,
      }));
  }, [judgments]);

  useEffect(() => {
    if (caseOptions.length === 0) {
      setSelectedCaseId(null);
      return;
    }
    if (!selectedCaseId || !caseOptions.some((option) => option.caseId === selectedCaseId)) {
      setSelectedCaseId(caseOptions[0]?.caseId ?? null);
    }
  }, [caseOptions, selectedCaseId]);

  return (
    <section className="rounded-3xl border border-slate-200 bg-white px-6 py-5 shadow-sm">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Activity stream</p>
          <p className="text-sm text-slate-600">Unified enforcement timeline for this portfolio.</p>
        </div>
        {caseOptions.length > 1 ? (
          <label className="text-xs text-slate-500">
            Case
            <select
              value={selectedCaseId ?? ''}
              onChange={(event) => setSelectedCaseId(event.target.value || null)}
              className="ml-2 rounded-full border border-slate-300 px-3 py-1 text-sm text-slate-700"
            >
              {caseOptions.map((option) => (
                <option key={option.caseId} value={option.caseId}>
                  {option.label}
                </option>
              ))}
            </select>
          </label>
        ) : caseOptions.length === 1 ? (
          <p className="text-xs font-semibold text-slate-500">Case {caseOptions[0].label}</p>
        ) : null}
      </header>
      <div className="mt-4">
        {caseOptions.length === 0 ? (
          <p className="text-sm text-slate-500">No enforcement cases are linked to this plaintiff yet.</p>
        ) : (
          <ActivityFeed
            caseId={selectedCaseId}
            limit={40}
            emptyMessage="No activity captured for the selected case yet."
          />
        )}
      </div>
    </section>
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

function StatusBadge({ label }: { label: string }) {
  return (
    <span className="inline-flex items-center rounded-full bg-slate-900 px-2 py-0.5 text-xs font-semibold text-white">
      {label}
    </span>
  );
}

function formatCount(value: number): string {
  if (!Number.isFinite(value) || value <= 0) {
    return '—';
  }
  return value.toLocaleString();
}

function JudgmentsCard({
  judgments,
  onNavigate,
  className,
  pipeline,
}: {
  judgments: PlaintiffJudgmentRow[];
  onNavigate: (row: PlaintiffJudgmentRow) => void;
  className?: string;
  pipeline: PipelineSummary;
}) {
  const hasRows = judgments.length > 0;

  return (
    <div className={`flex h-full flex-col rounded-3xl border border-slate-200 bg-white shadow-sm ${className ?? ''}`.trim()}>
      <header className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Judgments</h2>
          <p className="text-xs text-slate-500">Click a row to open the case detail.</p>
        </div>
        <PipelineSummaryPills pipeline={pipeline} />
      </header>
      <div className="flex-1 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-slate-100 text-left">
            <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
              <tr>
                <HeaderCell>Case number</HeaderCell>
                <HeaderCell>Defendant</HeaderCell>
                <HeaderCell>Judgment amount</HeaderCell>
                <HeaderCell>Stage</HeaderCell>
                <HeaderCell>Stage updated</HeaderCell>
                <HeaderCell>Collectability</HeaderCell>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
              {hasRows
                ? judgments.map((row) => <JudgmentRow key={row.judgmentId} row={row} onNavigate={onNavigate} />)
                : (
                    <tr>
                      <td colSpan={6} className="px-5 py-12 text-center text-sm text-slate-500">
                        No judgments are linked to this plaintiff yet.
                      </td>
                    </tr>
                  )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function HeaderCell({ children }: { children: React.ReactNode }) {
  return <th className="px-5 py-3 sm:px-6">{children}</th>;
}

function JudgmentRow({ row, onNavigate }: { row: PlaintiffJudgmentRow; onNavigate: (row: PlaintiffJudgmentRow) => void }) {
  const handleClick = () => onNavigate(row);
  const handleKeyDown = (event: React.KeyboardEvent<HTMLTableRowElement>) => {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onNavigate(row);
    }
  };

  return (
    <tr
      tabIndex={row.caseNumber ? 0 : -1}
      onClick={row.caseNumber ? handleClick : undefined}
      onKeyDown={row.caseNumber ? handleKeyDown : undefined}
      className={`transition ${row.caseNumber ? 'cursor-pointer hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500/40' : ''}`.trim()}
    >
      <td className="px-5 py-4 text-sm font-semibold text-slate-800 sm:px-6">{row.caseNumber ?? '—'}</td>
      <td className="px-5 py-4 sm:px-6">{row.defendantName ?? '—'}</td>
      <td className="px-5 py-4 sm:px-6">{formatCurrency(row.judgmentAmount)}</td>
      <td className="px-5 py-4 sm:px-6">{row.enforcementStageLabel ?? '—'}</td>
      <td className="px-5 py-4 sm:px-6">{formatDateTime(row.enforcementStageUpdatedAt)}</td>
      <td className="px-5 py-4 sm:px-6">{row.collectabilityTier ?? '—'}</td>
    </tr>
  );
}

function PipelineSummaryPills({ pipeline }: { pipeline: PipelineSummary }) {
  const entries: Array<{ label: string; value: number; tone: 'emerald' | 'sky' | 'amber' | 'slate' }> = [
    { label: 'Active', value: pipeline.enforcementActive, tone: 'emerald' },
    { label: 'Planning', value: pipeline.enforcementPlanning, tone: 'sky' },
    { label: 'Outreach', value: pipeline.outreach, tone: 'amber' },
    { label: 'Collected', value: pipeline.collected, tone: 'slate' },
  ];

  return (
    <div className="flex flex-wrap gap-2">
      {entries.map((entry) => (
        <span
          key={entry.label}
          className={`inline-flex items-center rounded-full border px-3 py-1 text-xs font-semibold ${pipelineTone(entry.tone)}`}
        >
          {entry.label}: {formatCount(entry.value)}
        </span>
      ))}
    </div>
  );
}

function pipelineTone(tone: 'emerald' | 'sky' | 'amber' | 'slate'): string {
  switch (tone) {
    case 'emerald':
      return 'border-emerald-200 bg-emerald-50 text-emerald-700';
    case 'sky':
      return 'border-sky-200 bg-sky-50 text-sky-700';
    case 'amber':
      return 'border-amber-200 bg-amber-50 text-amber-700';
    case 'slate':
    default:
      return 'border-slate-200 bg-slate-50 text-slate-700';
  }
}

function ContactsCard({ contacts }: { contacts: PlaintiffDetailData['contacts'] }) {
  const hasContacts = contacts.length > 0;

  return (
    <div className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">Contacts</h2>
      </header>
      <div className="flex-1 px-5 py-4">
        {hasContacts ? (
          <ul className="space-y-4">
            {contacts.map((contact) => (
              <li key={contact.id} className="rounded-2xl border border-slate-100 bg-slate-50 px-4 py-3">
                <p className="font-semibold text-slate-800">{contact.name}</p>
                <p className="text-xs text-slate-500">{contact.role ?? 'Contact'}</p>
                <dl className="mt-2 grid grid-cols-1 gap-y-1 text-sm text-slate-600">
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Email</dt>
                    <dd className="mt-0.5">{contact.email ?? '—'}</dd>
                  </div>
                  <div>
                    <dt className="text-xs uppercase tracking-wide text-slate-400">Phone</dt>
                    <dd className="mt-0.5">{contact.phone ?? '—'}</dd>
                  </div>
                </dl>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-slate-500">No contacts have been captured for this plaintiff yet.</p>
        )}
      </div>
    </div>
  );
}

function StatusHistoryCard({ events }: { events: PlaintiffStatusEvent[] }) {
  return (
    <div className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">Status history</h2>
      </header>
      <div className="flex-1 px-5 py-4">
        {events.length > 0 ? (
          <ol className="space-y-4">
            {events.map((event) => (
              <li key={event.id} className="flex items-start gap-3">
                <span className="mt-1 h-2 w-2 rounded-full bg-slate-300" aria-hidden />
                <div>
                  <p className="text-sm font-semibold text-slate-800">{event.statusLabel}</p>
                  <p className="text-xs text-slate-500">{formatDateTime(event.changedAt)}</p>
                  {event.note ? <p className="mt-1 text-sm text-slate-600">{event.note}</p> : null}
                  {event.changedBy ? <p className="text-xs text-slate-500">By {event.changedBy}</p> : null}
                </div>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-sm text-slate-500">No status changes recorded yet.</p>
        )}
      </div>
    </div>
  );
}

function NotesCard({ detail }: { detail: PlaintiffDetailData }) {
  const hasStatusHistory = detail.statusHistory.length > 0;

  const lastStatus = hasStatusHistory ? detail.statusHistory[0] : null;

  return (
    <div className="flex h-full flex-col rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="border-b border-slate-100 px-5 py-4">
        <h2 className="text-base font-semibold text-slate-900">Latest signals</h2>
      </header>
      <div className="flex-1 px-5 py-4 text-sm text-slate-600">
        {hasStatusHistory ? (
          <div className="space-y-3">
            <p>
              <span className="font-semibold text-slate-800">Current status:</span> {lastStatus?.statusLabel ?? detail.summary.status.label}
            </p>
            {lastStatus?.note ? <p>{lastStatus.note}</p> : null}
            <p className="text-xs text-slate-500">Updated {formatDateTime(lastStatus?.changedAt)}{lastStatus?.changedBy ? ` by ${lastStatus.changedBy}` : ''}</p>
          </div>
        ) : (
          <p>No recent status updates recorded.</p>
        )}
      </div>
    </div>
  );
}
