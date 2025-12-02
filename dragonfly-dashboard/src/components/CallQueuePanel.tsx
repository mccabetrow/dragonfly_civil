import React, { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { DashboardError } from './DashboardError.tsx';
import DemoLockCard from './DemoLockCard';
import RefreshButton from './RefreshButton';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import { usePlaintiffCallQueue, type PlaintiffCallQueueRow } from '../hooks/usePlaintiffCallQueue';
import { formatCurrency, formatDateTime } from '../utils/formatters';
import { supabaseClient } from '../lib/supabaseClient';
import { PLAINTIFF_STATUS_DISPLAY, PLAINTIFF_STATUS_LABELS } from '../constants/plaintiffStatus';
import { setPlaintiffStatus, type PlaintiffStatus } from '../utils/plaintiffStatusClient';
import SectionHeader from './SectionHeader';
import StatusMessage from './StatusMessage';
import { InlineSpinner } from './InlineSpinner';
import { useLogCallOutcome } from '../hooks/useLogCallOutcome';

interface CallOutcomeFormValues {
  outcome: string;
  interestLevel: string;
  notes: string;
  nextFollowUpAt: string;
  assignee: string;
}

const SKELETON_ROWS = 5;
const SKELETON_COLUMNS = 7;
const HIGH_PRIORITY_THRESHOLD = 10000;

const QUICK_OUTCOMES: Array<{ key: string; label: string; outcome: string }> = [
  { key: 'no_answer', label: 'No answer', outcome: 'no_answer' },
  { key: 'bad_number', label: 'Bad number', outcome: 'bad_number' },
  { key: 'interested', label: 'Interested', outcome: 'interested' },
  { key: 'not_interested', label: 'Not interested', outcome: 'not_interested' },
  { key: 'call_back', label: 'Call back later', outcome: 'follow_up' },
];

const CallQueuePanel: React.FC = () => {
  const navigate = useNavigate();
  const { state, refetch } = usePlaintiffCallQueue();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [actionMessage, setActionMessage] = useState<string | null>(null);
  const [callFormTarget, setCallFormTarget] = useState<PlaintiffCallQueueRow | null>(null);
  const [quickOutcomePendingId, setQuickOutcomePendingId] = useState<string | null>(null);
  const [notesPanelId, setNotesPanelId] = useState<string | null>(null);
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const { logCallOutcome, isLogging, error: logError, resetError } = useLogCallOutcome();

  const rows = state.data ?? [];
  const status = state.status;
  const isIdle = status === 'idle';
  const isLoading = status === 'loading' || isIdle;
  const isDemoLocked = status === 'demo_locked';
  const isError = status === 'error';
  const showSkeleton = isLoading && rows.length === 0;
  const showEmpty = status === 'ready' && rows.length === 0;
  const showTable = status === 'ready' && rows.length > 0;
  const displayError = state.errorMessage || (typeof state.error === 'string' ? state.error : state.error?.message) || null;
  const statusBadgeClass = useMemo(() => createStatusClassMap(), []);
  const showRefreshingBanner = isLoading && rows.length > 0;
  const totalQueueSize = rows.length;
  const highPriorityCount = useMemo(
    () => rows.filter((row) => Number(row.totalJudgmentAmount) >= HIGH_PRIORITY_THRESHOLD).length,
    [rows],
  );

  const handleNavigate = (plaintiffId: string) => {
    if (!plaintiffId) {
      return;
    }
    navigate(`/plaintiffs/${encodeURIComponent(plaintiffId)}`);
  };

  const handleStatusUpdate = async (plaintiffId: string, nextStatus: PlaintiffStatus) => {
    if (!plaintiffId) {
      return;
    }
    setPendingId(plaintiffId);
    setActionError(null);
    setActionMessage(null);
    try {
      await setPlaintiffStatus(supabaseClient, plaintiffId, nextStatus);
      await refetch();
      setActionMessage(`Marked as ${PLAINTIFF_STATUS_LABELS[nextStatus]}.`);
    } catch (err) {
      const fallback = err instanceof Error && err.message ? err.message : 'Failed to update status.';
      setActionError(fallback);
    } finally {
      setPendingId(null);
    }
  };

  const handleCallOutcomeSubmit = async (target: PlaintiffCallQueueRow, values: CallOutcomeFormValues) => {
    if (!target.plaintiffId) {
      return;
    }
    setActionError(null);
    try {
      await logCallOutcome({
        plaintiffId: target.plaintiffId,
        outcome: values.outcome,
        interestLevel: values.interestLevel,
        notes: values.notes,
        nextFollowUpAt: values.nextFollowUpAt,
        assignee: values.assignee,
      });
      await refetch();
      setActionMessage('Call outcome logged.');
      setCallFormTarget(null);
    } catch (err) {
      const fallback = err instanceof Error && err.message ? err.message : 'Failed to log call outcome.';
      setActionError(fallback);
    }
  };

  const handleQuickOutcome = async (target: PlaintiffCallQueueRow, outcome: string) => {
    if (!target.plaintiffId) {
      return;
    }
    const draftNote = noteDrafts[target.plaintiffId]?.trim() ?? null;
    setActionError(null);
    setQuickOutcomePendingId(target.plaintiffId);
    try {
      await logCallOutcome({
        plaintiffId: target.plaintiffId,
        outcome,
        notes: draftNote,
      });
      await refetch();
      setActionMessage('Call outcome logged.');
      setNoteDrafts((previous) => ({ ...previous, [target.plaintiffId ?? '']: '' }));
      setNotesPanelId((previous) => (previous === target.plaintiffId ? null : previous));
    } catch (err) {
      const fallback = err instanceof Error && err.message ? err.message : 'Failed to log call outcome.';
      setActionError(fallback);
    } finally {
      setQuickOutcomePendingId(null);
    }
  };

  useEffect(() => {
    if (!actionMessage) {
      return;
    }
    const timer = window.setTimeout(() => setActionMessage(null), 4000);
    return () => window.clearTimeout(timer);
  }, [actionMessage]);

  useEffect(() => {
    if (!actionError) {
      return;
    }
    const timer = window.setTimeout(() => setActionError(null), 6000);
    return () => window.clearTimeout(timer);
  }, [actionError]);

  const refreshButton = (
    <RefreshButton onClick={() => void refetch()} isLoading={isLoading} hasData={rows.length > 0} />
  );

  useEffect(() => {
    if (logError) {
      setActionError(logError);
    }
  }, [logError]);

  if (isDemoLocked) {
    return (
      <section className="df-card space-y-4">
        <SectionHeader
          title="Call Queue"
          description="Top plaintiffs ordered by value and latest contact cadence."
        />
        <DemoLockCard description={state.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
      </section>
    );
  }

  return (
    <section className="df-card space-y-4">
      <SectionHeader
        title="Call Queue"
        description="Top plaintiffs ordered by value and latest contact cadence."
        actions={refreshButton}
      />

      <div className="flex flex-wrap items-start justify-between gap-4 rounded-lg border border-slate-100 bg-slate-50/60 p-4">
        <p className="text-sm text-slate-700">
          <strong>Start at the top, work down.</strong> Log every call attempt. Use the status buttons to mark what happened so the system can schedule the next touch.
        </p>
        <div className="flex flex-wrap gap-3">
          <QueueStat label="In queue" value={totalQueueSize} />
          <QueueStat label="High priority" value={highPriorityCount} helper={formatHighPriorityHelper()} />
        </div>
      </div>

      {actionMessage ? <p className="text-sm font-medium text-emerald-700">{actionMessage}</p> : null}
      {actionError ? <p className="text-sm font-medium text-rose-600">{actionError}</p> : null}
      {showRefreshingBanner ? <StatusMessage tone="info">Refreshing call queue…</StatusMessage> : null}

      {showSkeleton ? (
        <SkeletonTable />
      ) : isError ? (
        <DashboardError
          message={displayError ?? 'Unable to load the call queue.'}
          onRetry={() => void refetch()}
        />
      ) : showEmpty ? (
        <EmptyState />
      ) : showTable ? (
        <div className="overflow-hidden rounded-md border border-slate-100">
          <table className="min-w-full divide-y divide-slate-100">
            <thead className="bg-slate-50">
              <tr>
                <HeaderCell>#</HeaderCell>
                <HeaderCell>Plaintiff</HeaderCell>
                <HeaderCell>Firm</HeaderCell>
                <HeaderCell className="text-right">Judgment</HeaderCell>
                <HeaderCell className="text-center">Status</HeaderCell>
                <HeaderCell>Reachability</HeaderCell>
                <HeaderCell className="text-right">Log Call</HeaderCell>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 bg-white">
              {rows.map((row, index) => {
                const rowKey = row.plaintiffId || `${row.plaintiffName}-${row.createdAt ?? row.lastContactedAt ?? index}`;
                return (
                <tr
                  key={rowKey}
                  className={`hover:bg-slate-50 ${row.plaintiffId ? 'cursor-pointer' : 'cursor-default'}`}
                  onClick={() => handleNavigate(row.plaintiffId)}
                >
                  <BodyCell>{index + 1}</BodyCell>
                  <BodyCell>
                    <div className="font-medium text-slate-900">{row.plaintiffName}</div>
                    <div className="text-xs text-slate-500">{formatCaseCount(row.caseCount)}</div>
                    {row.phone ? <div className="text-xs font-mono text-slate-600">{row.phone}</div> : <div className="text-xs text-rose-600">No phone on file</div>}
                  </BodyCell>
                  <BodyCell>{row.firmName}</BodyCell>
                  <BodyCell className="text-right">{formatCurrency(row.totalJudgmentAmount)}</BodyCell>
                  <BodyCell className="text-center">
                    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusBadgeClass[row.status] ?? statusBadgeClass.unknown}`}>
                      {row.statusLabel}
                    </span>
                  </BodyCell>
                  <BodyCell>
                    <div className="text-sm font-semibold text-slate-900">{formatLastContact(row.lastContactedAt, row.createdAt)}</div>
                    <div className="text-xs text-slate-500">{formatLastOutcome(row.lastCallOutcome, row.lastCallAttemptedAt)}</div>
                    <div className="text-xs text-slate-500">Days since contact: {formatDaysSinceContact(row.lastContactedAt, row.createdAt)}</div>
                  </BodyCell>
                  <BodyCell className="text-right">
                    <div className="flex flex-col items-end gap-2">
                      <div className="flex flex-wrap justify-end gap-2">
                        {QUICK_OUTCOMES.map((action) => {
                          const isRowQuickLogging = quickOutcomePendingId === row.plaintiffId && isLogging;
                          return (
                          <button
                            key={`${row.plaintiffId}-${action.key}`}
                            type="button"
                            className="rounded-full border border-slate-300 px-3 py-1 text-xs font-semibold text-slate-700 transition hover:border-slate-400 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
                            disabled={!row.plaintiffId || isLogging || quickOutcomePendingId === row.plaintiffId}
                            onClick={(event) => {
                              event.stopPropagation();
                              void handleQuickOutcome(row, action.outcome);
                            }}
                          >
                            {isRowQuickLogging ? 'Saving…' : action.label}
                          </button>
                          );
                        })}
                      </div>
                      <div className="flex flex-wrap items-center justify-end gap-2 text-xs text-slate-500">
                        <button
                          type="button"
                          className="text-xs font-semibold text-slate-700 underline-offset-2 hover:underline"
                          onClick={(event) => {
                            event.stopPropagation();
                            if (!row.plaintiffId) {
                              return;
                            }
                            setNotesPanelId((previous) => (previous === row.plaintiffId ? null : row.plaintiffId));
                          }}
                        >
                          {notesPanelId === row.plaintiffId ? 'Hide notes' : 'Add notes'}
                        </button>
                        <button
                          type="button"
                          className="text-xs font-semibold text-slate-700 underline-offset-2 hover:underline"
                          disabled={!row.plaintiffId || isLogging}
                          onClick={(event) => {
                            event.stopPropagation();
                            if (!row.plaintiffId) {
                              return;
                            }
                            resetError();
                            setCallFormTarget(row);
                          }}
                        >
                          Open full form
                        </button>
                      </div>
                      {notesPanelId === row.plaintiffId ? (
                        <textarea
                          className="w-full rounded-md border border-slate-300 px-2 py-1 text-xs text-slate-700 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
                          rows={2}
                          placeholder="Optional notes before logging"
                          value={noteDrafts[row.plaintiffId] ?? ''}
                          onChange={(event) => {
                            event.stopPropagation();
                            const value = event.target.value;
                            setNoteDrafts((previous) => ({ ...previous, [row.plaintiffId ?? '']: value }));
                          }}
                        />
                      ) : null}
                      <StatusActionMenu
                        disabled={!row.plaintiffId || isLoading || pendingId === row.plaintiffId}
                        isPending={pendingId === row.plaintiffId}
                        onSelect={(next) => void handleStatusUpdate(row.plaintiffId, next)}
                      />
                    </div>
                  </BodyCell>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <StatusMessage tone="info">Loading call queue…</StatusMessage>
      )}

      {callFormTarget ? (
        <CallOutcomeForm
          target={callFormTarget}
          isSubmitting={isLogging}
          onCancel={() => {
            resetError();
            setCallFormTarget(null);
          }}
          onSubmit={(values) => handleCallOutcomeSubmit(callFormTarget, values)}
        />
      ) : null}

      <StatusLegend />
    </section>
  );
};

function createStatusClassMap(): Record<string, string> {
  return {
    new: 'bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200',
    contacted: 'bg-indigo-50 text-indigo-700 ring-1 ring-inset ring-indigo-200',
    qualified: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200',
    sent_agreement: 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200',
    signed: 'bg-slate-900 text-white',
    lost: 'bg-rose-50 text-rose-700 ring-1 ring-inset ring-rose-200',
    unknown: 'bg-slate-100 text-slate-600',
  };
}

function formatLastOutcome(outcome: string | null, attemptedAt: string | null): string {
  if (!outcome) {
    return 'No outcomes logged yet';
  }
  const label = outcome.replace(/_/g, ' ');
  if (!attemptedAt) {
    return `Last outcome: ${label}`;
  }
  const relative = formatRelativeTime(attemptedAt);
  if (relative) {
    return `Last outcome: ${label} (${relative})`;
  }
  return `Last outcome: ${label} (${formatDateTime(attemptedAt)})`;
}

function formatHighPriorityHelper(): string {
  return `>= $${HIGH_PRIORITY_THRESHOLD.toLocaleString()} judgments`;
}

function formatCaseCount(count: number): string {
  if (!Number.isFinite(count) || count <= 0) {
    return 'No linked cases';
  }
  if (count === 1) {
    return '1 linked case';
  }
  return `${count} linked cases`;
}

function formatLastContact(lastContact: string | null, createdAt: string | null): string {
  if (lastContact) {
    const relative = formatRelativeTime(lastContact);
    if (relative) {
      return `Contacted ${relative}`;
    }
    return `Contacted ${formatDateTime(lastContact)}`;
  }
  if (createdAt) {
    const relative = formatRelativeTime(createdAt);
    if (relative) {
      return `Created ${relative}`;
    }
    return `Created ${formatDateTime(createdAt)}`;
  }
  return 'No contact logged';
}

function formatDaysSinceContact(lastContact: string | null, createdAt: string | null): string {
  const source = lastContact ?? createdAt;
  if (!source) {
    return '—';
  }
  const parsed = new Date(source);
  if (Number.isNaN(parsed.getTime())) {
    return '—';
  }
  const diffMs = Date.now() - parsed.getTime();
  if (diffMs < 0) {
    return '0';
  }
  const days = Math.floor(diffMs / 86_400_000);
  return days <= 0 ? '0' : days.toString();
}

function formatRelativeTime(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return null;
  }
  const diffMs = parsed.getTime() - Date.now();
  if (Math.abs(diffMs) < 45_000) {
    return 'just now';
  }
  const thresholds: Array<{ unit: Intl.RelativeTimeFormatUnit; ms: number }> = [
    { unit: 'day', ms: 86_400_000 },
    { unit: 'hour', ms: 3_600_000 },
    { unit: 'minute', ms: 60_000 },
  ];
  for (const { unit, ms } of thresholds) {
    if (Math.abs(diffMs) >= ms || unit === 'minute') {
      const valueInUnit = Math.round(diffMs / ms);
      return RELATIVE_TIME_FORMAT.format(valueInUnit, unit);
    }
  }
  return null;
}

function SkeletonTable(): React.ReactElement {
  return (
    <div className="animate-pulse rounded-md border border-slate-100">
      <table className="min-w-full divide-y divide-slate-100">
        <thead className="bg-slate-50">
          <tr>
            {Array.from({ length: SKELETON_COLUMNS }).map((_, idx) => (
              <HeaderCell key={idx}> </HeaderCell>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {Array.from({ length: SKELETON_ROWS }).map((_, idx) => (
            <tr key={idx}>
              {Array.from({ length: SKELETON_COLUMNS }).map((__, colIdx) => (
                <BodyCell key={colIdx}>
                  <span className="inline-block h-3 w-full rounded bg-slate-100" />
                </BodyCell>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function EmptyState(): React.ReactElement {
  return (
    <div className="rounded-md border border-dashed border-slate-200 bg-slate-50 py-8 text-center">
      <p className="text-sm font-medium text-slate-600">No plaintiffs currently in the call queue.</p>
      <p className="mt-1 text-xs text-slate-500">Queue updates automatically when new plaintiffs meet the playbook criteria.</p>
    </div>
  );
}

interface CellProps {
  children: React.ReactNode;
  className?: string;
}

function HeaderCell({ children, className = '' }: CellProps): React.ReactElement {
  return (
    <th scope="col" className={`px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-600 ${className}`}>
      {children}
    </th>
  );
}

function BodyCell({ children, className = '' }: CellProps): React.ReactElement {
  return <td className={`px-3 py-2 text-sm text-slate-700 ${className}`}>{children}</td>;
}

interface StatusActionMenuProps {
  onSelect: (status: PlaintiffStatus) => void;
  disabled: boolean;
  isPending: boolean;
}

function QueueStat({ label, value, helper }: { label: string; value: number; helper?: string }): React.ReactElement {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-right shadow-sm">
      <p className="text-xs uppercase tracking-wide text-slate-500">{label}</p>
      <p className="text-xl font-semibold text-slate-900">{value.toLocaleString()}</p>
      {helper ? <p className="text-[11px] text-slate-500">{helper}</p> : null}
    </div>
  );
}

function StatusLegend(): React.ReactElement {
  const entries: Array<{ label: string; description: string }> = [
    { label: 'No answer', description: 'We’ll auto-schedule another attempt later today.' },
    { label: 'Bad number', description: 'Mark it and move on; the queue deprioritizes it.' },
    { label: 'Interested', description: 'Flagged for quick follow-up and agreement prep.' },
    { label: 'Not interested', description: 'We pause outreach unless something changes.' },
    { label: 'Call back later', description: 'Log notes + timing so we can honor the request.' },
  ];
  return (
    <div className="rounded-lg border border-slate-100 bg-slate-50/75 p-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Status legend</p>
      <dl className="mt-2 grid gap-2 text-sm text-slate-700 md:grid-cols-2">
        {entries.map((entry) => (
          <div key={entry.label}>
            <dt className="font-semibold">{entry.label}</dt>
            <dd className="text-slate-600">{entry.description}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function StatusActionMenu({ onSelect, disabled, isPending }: StatusActionMenuProps): React.ReactElement {
  const handleChange = (event: React.ChangeEvent<HTMLSelectElement>) => {
    const value = event.target.value as PlaintiffStatus | '';
    if (!value) {
      return;
    }
    onSelect(value);
    event.target.value = '';
  };

  return (
    <div className="flex items-center justify-end gap-2">
      {isPending ? <InlineSpinner /> : null}
      <select
        defaultValue=""
        disabled={disabled}
        onChange={handleChange}
        className="rounded-full border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 transition hover:border-slate-400 focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200 disabled:cursor-not-allowed disabled:opacity-60"
      >
        <option value="" disabled>
          {disabled ? 'Updating…' : 'Update status…'}
        </option>
        {PLAINTIFF_STATUS_DISPLAY.map((option) => (
          <option key={option.code} value={option.code}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  );
}

interface CallOutcomeFormProps {
  target: PlaintiffCallQueueRow;
  isSubmitting: boolean;
  onSubmit: (values: CallOutcomeFormValues) => void;
  onCancel: () => void;
}

const OUTCOME_OPTIONS: Array<{ value: string; label: string }> = [
  { value: 'no_answer', label: 'No answer' },
  { value: 'left_voicemail', label: 'Left voicemail' },
  { value: 'interested', label: 'Interested' },
  { value: 'not_interested', label: 'Not interested' },
  { value: 'follow_up', label: 'Needs follow-up' },
];

const INTEREST_OPTIONS: Array<{ value: string; label: string }> = [
  { value: '', label: 'Interest level (optional)' },
  { value: 'hot', label: 'Hot' },
  { value: 'warm', label: 'Warm' },
  { value: 'cold', label: 'Cold' },
];

const CallOutcomeForm: React.FC<CallOutcomeFormProps> = ({ target, isSubmitting, onSubmit, onCancel }) => {
  const [outcome, setOutcome] = useState<string>('no_answer');
  const [interestLevel, setInterestLevel] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [nextFollowUpAt, setNextFollowUpAt] = useState<string>('');
  const [assignee, setAssignee] = useState<string>('');

  useEffect(() => {
    setOutcome('no_answer');
    setInterestLevel('');
    setNotes('');
    setNextFollowUpAt('');
    setAssignee('');
  }, [target.plaintiffId]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    void onSubmit({ outcome, interestLevel, notes, nextFollowUpAt, assignee });
  };

  return (
    <form onSubmit={handleSubmit} className="rounded-md border border-slate-200 bg-slate-50 p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <p className="text-sm font-semibold text-slate-900">Log call for {target.plaintiffName}</p>
          <p className="text-xs text-slate-600">{formatLastOutcome(target.lastCallOutcome, target.lastCallAttemptedAt)}</p>
        </div>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-full border border-slate-300 px-3 py-1 text-xs font-medium text-slate-700 hover:border-slate-400"
            disabled={isSubmitting}
          >
            Cancel
          </button>
          <button
            type="submit"
            className="rounded-full bg-slate-900 px-4 py-1 text-xs font-semibold text-white transition hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-70"
            disabled={isSubmitting}
          >
            {isSubmitting ? 'Saving…' : 'Save outcome'}
          </button>
        </div>
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-2">
        <label className="text-xs font-semibold text-slate-600">
          Outcome
          <select
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
            value={outcome}
            onChange={(event) => setOutcome(event.target.value)}
            required
            disabled={isSubmitting}
          >
            {OUTCOME_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        <label className="text-xs font-semibold text-slate-600">
          Interest level
          <select
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
            value={interestLevel}
            onChange={(event) => setInterestLevel(event.target.value)}
            disabled={isSubmitting}
          >
            {INTEREST_OPTIONS.map((option) => (
              <option key={option.label} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <label className="text-xs font-semibold text-slate-600">
          Next follow-up (optional)
          <input
            type="datetime-local"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
            value={nextFollowUpAt}
            onChange={(event) => setNextFollowUpAt(event.target.value)}
            disabled={isSubmitting}
          />
        </label>
        <label className="text-xs font-semibold text-slate-600">
          Assignee (optional)
          <input
            type="text"
            className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
            value={assignee}
            onChange={(event) => setAssignee(event.target.value)}
            disabled={isSubmitting}
            placeholder="Ops user logging the call"
          />
        </label>
      </div>
      <label className="mt-3 block text-xs font-semibold text-slate-600">
        Notes (optional)
        <textarea
          className="mt-1 w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none focus:ring-2 focus:ring-slate-200"
          rows={3}
          value={notes}
          onChange={(event) => setNotes(event.target.value)}
          disabled={isSubmitting}
          placeholder="What happened on the call?"
        />
      </label>
    </form>
  );
};

const RELATIVE_TIME_FORMAT = new Intl.RelativeTimeFormat('en', { numeric: 'auto' });

export default CallQueuePanel;
