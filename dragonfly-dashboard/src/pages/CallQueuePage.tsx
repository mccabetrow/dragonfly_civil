import React, { useCallback, useEffect, useState } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
import { DashboardError } from '../components/DashboardError';
import DemoLockCard from '../components/DemoLockCard';
import PageHeader from '../components/PageHeader';
import SectionHeader from '../components/SectionHeader';
import RefreshButton from '../components/RefreshButton';
import StatusMessage from '../components/StatusMessage';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  DEFAULT_DEMO_LOCK_MESSAGE,
  deriveErrorMessage,
  type MetricsState,
} from '../hooks/metricsState';
import { demoSafeSelect, supabaseClient } from '../lib/supabaseClient';

/*
 * Manual Call Queue verification (dev env):
 * 1. npm run dev -> http://127.0.0.1:5173/overview
 * 2. Click "Call Queue" nav link (URL should be /call-queue and stay there).
 * 3. In another terminal run:
 *    $env:SUPABASE_MODE='dev'; python -m tools.seed_demo_plaintiffs --reset
 *    $env:SUPABASE_MODE='dev'; python -m tools.run_task_planner --env dev --tier-target tier_a=3 --tier-target tier_b=2 --enable-followups --followup-threshold-days 21
 * 4. Refresh /call-queue, confirm demo tasks load, and logging an outcome stays on the page.
 */

interface CallQueueRow {
  taskId: string;
  plaintiffId: string;
  plaintiffName: string;
  tier: string | null;
  phone: string | null;
  lastContactAt: string | null;
  daysSinceContact: number | null;
  dueAt: string | null;
  notes: string | null;
  status: string | null;
}

interface RawCallQueueRow {
  task_id: string | null;
  plaintiff_id: string | null;
  plaintiff_name: string | null;
  tier: string | null;
  phone: string | null;
  last_contact_at: string | null;
  days_since_contact: number | string | null;
  due_at: string | null;
  notes: string | null;
  status: string | null;
  task_status: string | null;
}

type CallOutcomeValue = 'reached' | 'left_voicemail' | 'no_answer' | 'bad_number' | 'do_not_call';
type InterestLevel = 'hot' | 'warm' | 'cold' | 'none';

interface CallOutcomePayload {
  outcome: CallOutcomeValue;
  interest: InterestLevel;
  notes: string;
  followUp: string;
}

const OUTCOME_OPTIONS: Array<{ value: CallOutcomeValue; label: string }> = [
  { value: 'reached', label: 'Reached' },
  { value: 'left_voicemail', label: 'Left Voicemail' },
  { value: 'no_answer', label: 'No Answer' },
  { value: 'bad_number', label: 'Bad Number' },
  { value: 'do_not_call', label: 'Do Not Call' },
];

const INTEREST_OPTIONS: Array<{ value: InterestLevel; label: string }> = [
  { value: 'hot', label: 'Hot' },
  { value: 'warm', label: 'Warm' },
  { value: 'cold', label: 'Cold' },
  { value: 'none', label: 'None' },
];

const TIER_STYLES: Record<string, string> = {
  A: 'bg-emerald-100 text-emerald-800',
  B: 'bg-amber-100 text-amber-800',
  C: 'bg-slate-200 text-slate-600',
};

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'short',
  timeStyle: 'short',
});

const numberFormatter = new Intl.NumberFormat('en-US', {
  maximumFractionDigits: 0,
});

const CALL_QUEUE_LOCK_TITLE = 'Call Queue Locked in This Demo';
const CALL_QUEUE_LOCK_MESSAGE =
  'Call tasks stay locked in this demo to avoid exposing plaintiff contact details. Sign in to the production console to work the queue.';

const CallQueuePage: React.FC = () => {
  const [queueState, setQueueState] = useState<MetricsState<CallQueueRow[]>>(() =>
    buildLoadingMetricsState<CallQueueRow[]>(),
  );
  const [selectedRow, setSelectedRow] = useState<CallQueueRow | null>(null);
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const fetchQueue = useCallback(async () => {
    setQueueState((previous) => buildLoadingMetricsState(previous));
    try {
      const nowIso = new Date().toISOString();
      let query = supabaseClient
        .from('v_plaintiff_call_queue')
        .select(
          'task_id, plaintiff_id, plaintiff_name, tier, phone, last_contact_at, days_since_contact, due_at, notes, status, task_status',
        )
        .lte('due_at', nowIso)
        .order('due_at', { ascending: true });

      query = query.eq('status', 'open');

      const result = await demoSafeSelect<RawCallQueueRow[] | null>(query);

      if (result.kind === 'demo_locked') {
        setQueueState(buildDemoLockedState<CallQueueRow[]>(CALL_QUEUE_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const records = (result.data ?? []) as RawCallQueueRow[];
      const mapped = records.map((row) => ({
        taskId: safeString(row.task_id),
        plaintiffId: safeString(row.plaintiff_id),
        plaintiffName: safeString(row.plaintiff_name, '—'),
        tier: row.tier ?? null,
        phone: normalizePhone(row.phone),
        lastContactAt: row.last_contact_at ?? null,
        daysSinceContact: normalizeNumber(row.days_since_contact),
        dueAt: row.due_at ?? null,
        notes: row.notes ?? null,
        status: normalizeTaskStatus(row.task_status ?? row.status),
      }));

      const openRows = mapped.filter((row) => row.status === 'open');
      setQueueState(buildReadyMetricsState(openRows));
    } catch (err) {
      console.debug('[CallQueuePage] failed to load queue', err);
      const friendly = renderFriendlyError(err);
      const normalizedError = err instanceof Error ? err : new Error(friendly);
      setQueueState(buildErrorMetricsState<CallQueueRow[]>(normalizedError, { message: friendly }));
    }
  }, []);

  useEffect(() => {
    void fetchQueue();
  }, [fetchQueue]);

  const handleRefresh = useCallback(() => {
    void fetchQueue();
  }, [fetchQueue]);

  useEffect(() => {
    if (!toastMessage) {
      return undefined;
    }
    const handle = window.setTimeout(() => setToastMessage(null), 4000);
    return () => window.clearTimeout(handle);
  }, [toastMessage]);

  const handleOpenDrawer = (row: CallQueueRow) => {
    setFormError(null);
    setSelectedRow(row);
  };

  const handleCloseDrawer = () => {
    if (isSubmitting) {
      return;
    }
    setSelectedRow(null);
    setFormError(null);
  };

  const handleSubmitOutcome = async (payload: CallOutcomePayload) => {
    if (!selectedRow) {
      return;
    }
    setIsSubmitting(true);
    setFormError(null);

    let followUpIso: string | null = null;
    if (payload.followUp) {
      const parsed = Date.parse(payload.followUp);
      if (Number.isNaN(parsed)) {
        setFormError('Follow-up timestamp is invalid.');
        setIsSubmitting(false);
        return;
      }
      followUpIso = new Date(parsed).toISOString();
    }

    try {
      const { error: rpcError } = await supabaseClient.rpc('log_call_outcome', {
        _plaintiff_id: selectedRow.plaintiffId,
        _task_id: selectedRow.taskId,
        _outcome: payload.outcome,
        _interest: payload.interest,
        _notes: payload.notes.trim() ? payload.notes.trim() : null,
        _follow_up_at: followUpIso,
      });

      if (rpcError) {
        throw rpcError;
      }

      setQueueState((prev) => {
        if (prev.status !== 'ready' || !prev.data) {
          return prev;
        }
        return { ...prev, data: prev.data.filter((row) => row.taskId !== selectedRow.taskId) } satisfies MetricsState<CallQueueRow[]>;
      });
      setSelectedRow(null);
      setToastMessage('Outcome logged and task updated.');
    } catch (err) {
      const friendly = err instanceof Error ? err.message : 'Unable to log call outcome.';
      setFormError(friendly);
    } finally {
      setIsSubmitting(false);
    }
  };

  const isLoading = queueState.status === 'loading';
  const isDemoLocked = queueState.status === 'demo_locked';
  const rows = queueState.status === 'ready' && Array.isArray(queueState.data) ? queueState.data : [];
  const hasRows = rows.length > 0;
  const showRefreshing = isLoading && hasRows;
  const emptyState = queueState.status === 'ready' && rows.length === 0;
  const queueErrorMessage =
    queueState.status === 'error'
      ? queueState.errorMessage ?? deriveErrorMessage(queueState.error) ?? 'Unable to load the call queue.'
      : null;

  return (
    <div className="df-page">
      <PageHeader
        eyebrow="Call queue"
        title="Work today's call list"
        subtitle="Supabase production parity"
      >
        <p className="text-sm text-white/80">
          Pulls from <code className="rounded bg-white/20 px-1 py-0.5 text-xs text-white">v_plaintiff_call_queue</code> and only shows due or overdue call tasks.
        </p>
      </PageHeader>

      {toastMessage && <Toast message={toastMessage} />}

      <section className="df-card space-y-4">
        <SectionHeader
          title="Call queue"
          description="Due and overdue call tasks ordered by priority."
          actions={queueErrorMessage || isDemoLocked ? undefined : (
            <RefreshButton onClick={handleRefresh} isLoading={isLoading} hasData={hasRows} />
          )}
        />

        {isLoading && !hasRows ? <QueueSkeleton /> : null}

        {!isLoading && queueErrorMessage ? (
          <DashboardError title="Call queue unavailable" message={queueErrorMessage} onRetry={handleRefresh} />
        ) : null}

        {!queueErrorMessage && isDemoLocked ? (
          <DemoLockCard
            title={CALL_QUEUE_LOCK_TITLE}
            description={queueState.lockMessage ?? CALL_QUEUE_LOCK_MESSAGE ?? DEFAULT_DEMO_LOCK_MESSAGE}
          />
        ) : null}

        {!queueErrorMessage && !isDemoLocked && emptyState ? <EmptyState onRefresh={handleRefresh} /> : null}

        {!queueErrorMessage && !isDemoLocked && hasRows ? (
          <>
            {showRefreshing ? <StatusMessage tone="info">Refreshing call queue…</StatusMessage> : null}
            <QueueTable rows={rows} onLogOutcome={handleOpenDrawer} />
          </>
        ) : null}
      </section>

      <CallOutcomeDrawer
        row={selectedRow}
        isSubmitting={isSubmitting}
        errorMessage={formError}
        onClose={handleCloseDrawer}
        onSubmit={handleSubmitOutcome}
      />
    </div>
  );
};

interface QueueTableProps {
  rows: CallQueueRow[];
  onLogOutcome: (row: CallQueueRow) => void;
}

const QueueTable: React.FC<QueueTableProps> = ({ rows, onLogOutcome }) => {
  return (
    <div className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
      <table className="min-w-full divide-y divide-slate-200 text-sm">
        <thead className="bg-slate-50 text-xs uppercase tracking-wider text-slate-500">
          <tr>
            <th className="px-4 py-3 text-left">Name</th>
            <th className="px-4 py-3 text-left">Tier</th>
            <th className="px-4 py-3 text-left">Phone</th>
            <th className="px-4 py-3 text-left">Days Since Contact</th>
            <th className="px-4 py-3 text-left">Due At</th>
            <th className="px-4 py-3 text-left">Notes</th>
            <th className="px-4 py-3 text-left">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {rows.map((row) => (
            <tr key={row.taskId} className="hover:bg-slate-50">
              <td className="px-4 py-3">
                <p className="font-semibold text-slate-900">{row.plaintiffName}</p>
                <p className="text-xs text-slate-500">Task #{row.taskId.slice(0, 8)}</p>
              </td>
              <td className="px-4 py-3">
                <TierBadge tier={row.tier} />
              </td>
              <td className="px-4 py-3 font-mono text-sm text-slate-800">{row.phone ?? '—'}</td>
              <td className="px-4 py-3 text-slate-900">
                {row.daysSinceContact != null ? numberFormatter.format(row.daysSinceContact) : '—'}
              </td>
              <td className="px-4 py-3 text-slate-900">
                {row.dueAt ? dateTimeFormatter.format(Date.parse(row.dueAt)) : '—'}
              </td>
              <td className="px-4 py-3 text-slate-600">
                <span className="line-clamp-2 text-xs">{row.notes?.trim() || '—'}</span>
              </td>
              <td className="px-4 py-3">
                <button
                  type="button"
                  className="rounded-lg bg-slate-900 px-3 py-2 text-xs font-semibold uppercase tracking-wide text-white shadow-sm transition hover:bg-slate-800"
                  onClick={() => onLogOutcome(row)}
                >
                  Log Outcome
                </button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};

interface CallOutcomeDrawerProps {
  row: CallQueueRow | null;
  isSubmitting: boolean;
  errorMessage: string | null;
  onClose: () => void;
  onSubmit: (payload: CallOutcomePayload) => void | Promise<void>;
}

const CallOutcomeDrawer: React.FC<CallOutcomeDrawerProps> = ({ row, isSubmitting, errorMessage, onClose, onSubmit }) => {
  const [outcome, setOutcome] = useState<CallOutcomeValue>('reached');
  const [interest, setInterest] = useState<InterestLevel>('hot');
  const [notes, setNotes] = useState<string>('');
  const [followUp, setFollowUp] = useState<string>('');

  useEffect(() => {
    if (!row) {
      setNotes('');
      setFollowUp('');
      setOutcome('reached');
      setInterest('hot');
      return;
    }
    setOutcome('reached');
    setInterest('hot');
    setNotes(row.notes ?? '');
    setFollowUp(formatDatetimeLocal(row.dueAt));
  }, [row]);

  const followUpDisabled = outcome === 'do_not_call' || outcome === 'bad_number';
  const interestDisabled = outcome !== 'reached';

  const handleOutcomeChange = (nextOutcome: CallOutcomeValue) => {
    setOutcome(nextOutcome);
    if (nextOutcome !== 'reached') {
      setInterest('none');
    } else if (interest === 'none') {
      setInterest('hot');
    }
    if (nextOutcome === 'do_not_call' || nextOutcome === 'bad_number') {
      setFollowUp('');
    }
  };

  if (!row) {
    return null;
  }

  return (
    <div className="fixed inset-0 z-40 flex items-stretch justify-end">
      <button
        type="button"
        className="h-full flex-1 bg-black/40"
        aria-label="Close call outcome drawer"
        onClick={onClose}
        disabled={isSubmitting}
      />
      <div className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">Log Call Outcome</p>
            <h3 className="text-xl font-semibold text-slate-900">{row.plaintiffName}</h3>
            <p className="text-xs text-slate-500">Tier {row.tier ?? '—'} • {row.phone ?? 'No phone on file'}</p>
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

        <form
          className="mt-6 space-y-4"
          onSubmit={(event) => {
            event.preventDefault();
            onSubmit({ outcome, interest, notes, followUp });
          }}
        >
          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Outcome</label>
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={outcome}
              onChange={(event) => handleOutcomeChange(event.target.value as CallOutcomeValue)}
              disabled={isSubmitting}
            >
              {OUTCOME_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Interest Level</label>
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={interest}
              onChange={(event) => setInterest(event.target.value as InterestLevel)}
              disabled={interestDisabled || isSubmitting}
            >
              {INTEREST_OPTIONS.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </select>
            {interestDisabled && <p className="mt-1 text-xs text-slate-500">Interest only tracked when you reached them.</p>}
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Notes</label>
            <textarea
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              rows={4}
              placeholder="Who you spoke with, commitments, etc."
              value={notes}
              onChange={(event) => setNotes(event.target.value)}
              disabled={isSubmitting}
            />
          </div>

          <div>
            <label className="text-xs font-semibold uppercase tracking-widest text-slate-500">Next Follow-up</label>
            <input
              type="datetime-local"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={followUp}
              onChange={(event) => setFollowUp(event.target.value)}
              disabled={followUpDisabled || isSubmitting}
            />
            {followUpDisabled && <p className="mt-1 text-xs text-slate-500">Follow-up disabled for Bad Number or Do Not Call.</p>}
          </div>

          {errorMessage && <p className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-sm text-rose-700">{errorMessage}</p>}

          <div className="flex flex-col gap-2 sm:flex-row sm:justify-end">
            <button
              type="button"
              className="rounded-lg border border-slate-300 px-4 py-2 text-sm font-semibold text-slate-700"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-60"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Saving…' : 'Save Outcome'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
};

const QueueSkeleton: React.FC = () => (
  <div className="space-y-3 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
    {[0, 1, 2, 3].map((row) => (
      <div key={row} className="h-10 w-full animate-pulse rounded bg-slate-100" />
    ))}
  </div>
);

const EmptyState: React.FC<{ onRefresh: () => void }> = ({ onRefresh }) => (
  <div className="rounded-2xl border border-slate-200 bg-white p-8 text-center">
    <p className="text-sm font-medium text-slate-700">No calls are due. Nice work!</p>
    <button
      type="button"
      className="mt-3 rounded-full border border-slate-300 px-4 py-2 text-xs font-semibold uppercase tracking-wide text-slate-700"
      onClick={onRefresh}
    >
      Refresh
    </button>
  </div>
);

const Toast: React.FC<{ message: string }> = ({ message }) => (
  <div className="fixed right-6 top-24 z-30 rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 shadow-sm">
    {message}
  </div>
);

const TierBadge: React.FC<{ tier: string | null }> = ({ tier }) => {
  if (!tier) {
    return <span className="rounded-full bg-slate-200 px-2 py-1 text-xs font-semibold text-slate-600">Unranked</span>;
  }
  const normalized = tier.trim().toUpperCase();
  const style = TIER_STYLES[normalized] ?? 'bg-slate-200 text-slate-600';
  return (
    <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase tracking-wide ${style}`}>
      Tier {normalized}
    </span>
  );
};

function safeString(value: unknown, fallback: string = ''): string {
  if (typeof value === 'string') {
    return value;
  }
  if (value == null) {
    return fallback;
  }
  return String(value);
}

function normalizeTaskStatus(value: unknown): string {
  if (typeof value !== 'string') {
    return 'open';
  }
  const normalized = value.trim().toLowerCase();
  return normalized.length > 0 ? normalized : 'open';
}

function normalizePhone(value: unknown): string | null {
  if (!value) {
    return null;
  }
  const str = value.toString().trim();
  return str.length > 0 ? str : null;
}

function normalizeNumber(value: unknown): number | null {
  if (value == null) {
    return null;
  }
  const num = typeof value === 'number' ? value : Number(value);
  if (Number.isNaN(num)) {
    return null;
  }
  return num;
}

function renderFriendlyError(err: unknown): string {
  if (!err) {
    return 'Unable to load the call queue.';
  }
  if (typeof err === 'string') {
    return err;
  }
  const pgErr = err as PostgrestError;
  if (pgErr && pgErr.message) {
    return pgErr.message;
  }
  if (err instanceof Error) {
    return err.message;
  }
  return 'Unable to load the call queue.';
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

export default CallQueuePage;
