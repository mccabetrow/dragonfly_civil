/**
 * OpsConsolePage - Mom's daily command center
 *
 * Layout: Today's Progress → Call Queue → Recent Activity
 * Designed for clarity and minimal cognitive load.
 */
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Phone, RefreshCw } from 'lucide-react';
import { TodayProgressCard } from '../components/TodayProgressCard';
import CallQueueStatusBar from '../components/CallQueueStatusBar';
import MetricsGate from '../components/MetricsGate';
import { useOpsConsole } from '../hooks/useOpsConsole';
import type { OpsCallTask } from '../hooks/useOpsConsole';
import { useOpsPlaintiffProfile } from '../hooks/useOpsPlaintiffProfile';
import { supabaseClient } from '../lib/supabaseClient';
import { formatDateTime } from '../utils/formatters';
import { useOpsDailySummary } from '../hooks/useOpsDailySummary';

const QUICK_ACTIONS: Array<{
  key: string;
  label: string;
  outcome: CallOutcomeValue;
  followUpDays?: number;
}> = [
  { key: 'reached', label: 'Reached', outcome: 'reached' },
  { key: 'no_answer', label: 'No answer', outcome: 'no_answer' },
  { key: 'bad_number', label: 'Wrong #', outcome: 'bad_number' },
  { key: 'follow_up', label: 'Follow-up', outcome: 'left_voicemail', followUpDays: 2 },
];

const CALL_OUTCOME_OPTIONS: Array<{ value: CallOutcomeValue; label: string }> = [
  { value: 'reached', label: 'Reached' },
  { value: 'left_voicemail', label: 'Left voicemail' },
  { value: 'no_answer', label: 'No answer' },
  { value: 'bad_number', label: 'Wrong number' },
  { value: 'do_not_call', label: 'Do not call' },
];

const INTEREST_OPTIONS: Array<{ value: InterestLevel; label: string }> = [
  { value: 'hot', label: 'Hot' },
  { value: 'warm', label: 'Warm' },
  { value: 'cold', label: 'Cold' },
  { value: 'none', label: 'None' },
];

type CallOutcomeValue = 'reached' | 'left_voicemail' | 'no_answer' | 'bad_number' | 'do_not_call';
type InterestLevel = 'hot' | 'warm' | 'cold' | 'none';

type CallOutcomePayload = {
  outcome: CallOutcomeValue;
  interest: InterestLevel;
  notes: string;
  followUp: string;
};

export function OpsConsolePage() {
  const { state, data, refetch, lastUpdated, removeTask } = useOpsConsole();
  const dailySummary = useOpsDailySummary();
  const tasks = data?.tasks ?? [];
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [drawerPreset, setDrawerPreset] = useState<{ outcome?: CallOutcomeValue; followUp?: string }>({});
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const selectedTask: OpsCallTask | null = useMemo(() => {
    if (selectedTaskId) {
      return tasks.find((task) => task.taskId === selectedTaskId) ?? null;
    }
    return data?.nextBestTask ?? tasks[0] ?? null;
  }, [tasks, selectedTaskId, data]);

  useEffect(() => {
    if (state.status === 'ready' && data?.nextBestTask && !selectedTaskId) {
      setSelectedTaskId(data.nextBestTask.taskId);
    }
  }, [state.status, data, selectedTaskId]);

  useEffect(() => {
    if (selectedTaskId && tasks.every((task) => task.taskId !== selectedTaskId)) {
      setSelectedTaskId(tasks[0]?.taskId ?? null);
    }
  }, [tasks, selectedTaskId]);

  const profile = useOpsPlaintiffProfile(selectedTask?.plaintiffId ?? null);

  const openDrawer = useCallback(
    (task: OpsCallTask, preset?: { outcome?: CallOutcomeValue; followUp?: string }) => {
      setSelectedTaskId(task.taskId);
      setDrawerPreset(preset ?? {});
      setFormError(null);
      setDrawerOpen(true);
    },
    [],
  );

  const closeDrawer = useCallback(() => {
    if (isSubmitting) return;
    setDrawerOpen(false);
    setFormError(null);
    setDrawerPreset({});
  }, [isSubmitting]);

  const handleSubmitOutcome = useCallback(
    async (payload: CallOutcomePayload) => {
      if (!selectedTask) return;

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
        const { error } = await supabaseClient.rpc('log_call_outcome', {
          _plaintiff_id: selectedTask.plaintiffId,
          _task_id: selectedTask.taskId,
          _outcome: payload.outcome,
          _interest: payload.interest,
          _notes: payload.notes.trim() || null,
          _follow_up_at: followUpIso,
        });

        if (error) throw error;

        removeTask(selectedTask.taskId);
        await Promise.all([refetch(), profile.refetch()]);
        setDrawerOpen(false);
        setDrawerPreset({});
        setToastMessage('Call logged ✓');
      } catch (err) {
        setFormError(err instanceof Error ? err.message : 'Unable to log call outcome.');
      } finally {
        setIsSubmitting(false);
      }
    },
    [selectedTask, removeTask, refetch, profile],
  );

  useEffect(() => {
    if (!toastMessage) return undefined;
    const timer = window.setTimeout(() => setToastMessage(null), 3000);
    return () => window.clearTimeout(timer);
  }, [toastMessage]);

  const handleQuickAction = useCallback(
    (task: OpsCallTask, action: { outcome: CallOutcomeValue; followUpDays?: number }) => {
      const presetFollowUp = action.followUpDays ? formatDatetimeLocal(addDays(action.followUpDays)) : undefined;
      openDrawer(task, { outcome: action.outcome, followUp: presetFollowUp });
    },
    [openDrawer],
  );

  const handleRefreshAll = useCallback(async () => {
    await Promise.all([refetch(), dailySummary.refetch()]);
  }, [refetch, dailySummary]);

  // Derive queue metrics
  const queueMetrics = useMemo(() => {
    const overdue = data?.overdue ?? 0;
    const dueToday = data?.dueToday ?? 0;
    const highPriority = tasks.filter((t) => t.priorityScore >= 80).length;
    return { overdue, dueToday, highPriority, total: tasks.length };
  }, [data, tasks]);

  const isLoading = state.status === 'loading' || state.status === 'idle';
  const summaryLoading = dailySummary.state.status === 'loading' || dailySummary.state.status === 'idle';

  return (
    <div className="space-y-6">
      {/* Toast notification */}
      {toastMessage && (
        <div className="fixed right-6 top-20 z-50 rounded-lg bg-emerald-600 px-4 py-2 text-sm font-medium text-white shadow-lg">
          {toastMessage}
        </div>
      )}

      {/* Header with refresh */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Ops Console</h1>
          <p className="mt-1 text-sm text-slate-500">
            Today's calls, agreements, and tasks in one place
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleRefreshAll()}
          disabled={isLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${isLoading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      {/* Today's Progress Card */}
      <TodayProgressCard summary={dailySummary.state.data} isLoading={summaryLoading} />

      {/* Call Queue Section */}
      <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-100 px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-violet-100 text-violet-600">
                <Phone className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-lg font-semibold text-slate-900">Call Queue</h2>
                <p className="text-sm text-slate-500">Start at the top, work down</p>
              </div>
            </div>
            {lastUpdated && (
              <span className="text-xs text-slate-400">Updated {formatDateTime(lastUpdated)}</span>
            )}
          </div>
        </div>

        <div className="p-4">
          <CallQueueStatusBar
            totalCalls={queueMetrics.total}
            overdueCalls={queueMetrics.overdue}
            dueTodayCalls={queueMetrics.dueToday}
            highPriorityCalls={queueMetrics.highPriority}
          />
        </div>

        <MetricsGate
          state={state}
          errorTitle="Call queue unavailable"
          onRetry={() => void refetch()}
          ready={
            <CallQueueTable
              tasks={tasks}
              selectedTaskId={selectedTask?.taskId ?? null}
              onSelectTask={setSelectedTaskId}
              onQuickAction={handleQuickAction}
            />
          }
          loadingFallback={<CallQueueSkeleton />}
        />
      </section>

      {/* Selected Plaintiff Panel */}
      {selectedTask && (
        <SelectedPlaintiffPanel
          task={selectedTask}
          profile={profile}
          onOpenForm={(preset) => openDrawer(selectedTask, preset)}
        />
      )}

      {/* Call Outcome Drawer */}
      <CallOutcomeDrawer
        isOpen={drawerOpen && !!selectedTask}
        task={selectedTask}
        presetOutcome={drawerPreset.outcome}
        presetFollowUp={drawerPreset.followUp}
        isSubmitting={isSubmitting}
        errorMessage={formError}
        onClose={closeDrawer}
        onSubmit={handleSubmitOutcome}
      />
    </div>
  );
}

// --- Sub-components ---

interface CallQueueTableProps {
  tasks: OpsCallTask[];
  selectedTaskId: string | null;
  onSelectTask: (taskId: string) => void;
  onQuickAction: (task: OpsCallTask, action: { outcome: CallOutcomeValue; followUpDays?: number }) => void;
}

function CallQueueTable({ tasks, selectedTaskId, onSelectTask, onQuickAction }: CallQueueTableProps) {
  if (tasks.length === 0) {
    return (
      <div className="px-6 py-12 text-center">
        <p className="text-lg font-medium text-slate-700">All caught up!</p>
        <p className="mt-1 text-sm text-slate-500">No calls in the queue right now.</p>
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-full">
        <thead className="border-b border-t border-slate-100 bg-slate-50/50">
          <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
            <th className="px-6 py-3">Plaintiff / Phone</th>
            <th className="px-4 py-3">Tier</th>
            <th className="px-4 py-3">Last Contact</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Actions</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {tasks.map((task) => (
            <tr
              key={task.taskId}
              onClick={() => onSelectTask(task.taskId)}
              className={`cursor-pointer transition-colors ${
                selectedTaskId === task.taskId
                  ? 'bg-indigo-50/50'
                  : 'hover:bg-slate-50'
              }`}
            >
              <td className="px-6 py-4">
                <p className="font-medium text-slate-900">{task.plaintiffName}</p>
                <p className="font-mono text-sm text-slate-500">{task.phone ?? 'No phone'}</p>
              </td>
              <td className="px-4 py-4">
                <TierBadge tier={task.tier} />
              </td>
              <td className="px-4 py-4 text-sm text-slate-600">
                {task.lastContactAt ? formatDateTime(task.lastContactAt) : (
                  <span className="text-slate-400">Never contacted</span>
                )}
              </td>
              <td className="px-4 py-4">
                <StatusChip status={task.status} />
              </td>
              <td className="px-4 py-4">
                <div className="flex flex-wrap gap-1.5">
                  {QUICK_ACTIONS.map((action) => (
                    <button
                      key={action.key}
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onQuickAction(task, action);
                      }}
                      className="rounded-md bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-700 transition-colors hover:bg-slate-200"
                    >
                      {action.label}
                    </button>
                  ))}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function CallQueueSkeleton() {
  return (
    <div className="p-6">
      <div className="space-y-3">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="flex items-center gap-4">
            <div className="h-10 w-10 animate-pulse rounded-lg bg-slate-100" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-48 animate-pulse rounded bg-slate-100" />
              <div className="h-3 w-32 animate-pulse rounded bg-slate-50" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

interface SelectedPlaintiffPanelProps {
  task: OpsCallTask;
  profile: ReturnType<typeof useOpsPlaintiffProfile>;
  onOpenForm: (preset?: { outcome?: CallOutcomeValue; followUp?: string }) => void;
}

function SelectedPlaintiffPanel({ task, profile, onOpenForm }: SelectedPlaintiffPanelProps) {
  const profileData = profile.data;

  return (
    <section className="rounded-2xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-100 px-6 py-4">
        <h2 className="text-lg font-semibold text-slate-900">
          {task.plaintiffName}
        </h2>
        <p className="text-sm text-slate-500">
          Tier {task.tier ?? '—'} • {task.phone ?? 'No phone on file'}
        </p>
      </div>

      <div className="grid gap-6 p-6 lg:grid-cols-2">
        {/* Quick log buttons */}
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Log this call</h3>
          <div className="grid grid-cols-2 gap-2">
            {QUICK_ACTIONS.map((action) => (
              <button
                key={action.key}
                type="button"
                onClick={() =>
                  onOpenForm({
                    outcome: action.outcome,
                    followUp: action.followUpDays ? formatDatetimeLocal(addDays(action.followUpDays)) : undefined,
                  })
                }
                className="rounded-lg border border-slate-200 bg-white px-4 py-3 text-left text-sm font-medium text-slate-700 transition-colors hover:bg-slate-50"
              >
                {action.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => onOpenForm()}
            className="mt-3 w-full rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-800"
          >
            Open full form
          </button>
        </div>

        {/* Recent history */}
        <div>
          <h3 className="mb-3 text-sm font-semibold text-slate-700">Recent history</h3>
          {profile.state.status === 'loading' ? (
            <div className="space-y-2">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded-lg bg-slate-50" />
              ))}
            </div>
          ) : profileData?.callAttempts.length ? (
            <ul className="space-y-2">
              {profileData.callAttempts.slice(0, 4).map((attempt) => (
                <li key={attempt.id} className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm">
                  <span className="font-medium text-slate-700">{attempt.outcome}</span>
                  <span className="ml-2 text-slate-500">
                    {attempt.attemptedAt ? formatDateTime(attempt.attemptedAt) : ''}
                  </span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-slate-500">No call history yet.</p>
          )}
        </div>
      </div>
    </section>
  );
}

interface TierBadgeProps {
  tier: string | null;
}

function TierBadge({ tier }: TierBadgeProps) {
  if (!tier) {
    return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-xs font-medium text-slate-500">—</span>;
  }
  const normalized = tier.trim().toUpperCase();
  const colors: Record<string, string> = {
    A: 'bg-emerald-100 text-emerald-700',
    B: 'bg-amber-100 text-amber-700',
    C: 'bg-slate-100 text-slate-600',
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${colors[normalized] ?? colors.C}`}>
      {normalized}
    </span>
  );
}

interface StatusChipProps {
  status: string;
}

function StatusChip({ status }: StatusChipProps) {
  const normalized = (status ?? '').toLowerCase().replace(/_/g, ' ');
  const labelMap: Record<string, { label: string; color: string }> = {
    pending: { label: 'Pending', color: 'bg-amber-100 text-amber-700' },
    scheduled: { label: 'Scheduled', color: 'bg-blue-100 text-blue-700' },
    overdue: { label: 'Overdue', color: 'bg-rose-100 text-rose-700' },
    completed: { label: 'Done', color: 'bg-emerald-100 text-emerald-700' },
    'in progress': { label: 'In Progress', color: 'bg-indigo-100 text-indigo-700' },
  };
  const { label, color } = labelMap[normalized] ?? { label: status || '—', color: 'bg-slate-100 text-slate-600' };
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>
      {label}
    </span>
  );
}

interface CallOutcomeDrawerProps {
  isOpen: boolean;
  task: OpsCallTask | null;
  presetOutcome?: CallOutcomeValue;
  presetFollowUp?: string;
  isSubmitting: boolean;
  errorMessage: string | null;
  onClose: () => void;
  onSubmit: (payload: CallOutcomePayload) => Promise<void> | void;
}

function CallOutcomeDrawer({
  isOpen,
  task,
  presetOutcome,
  presetFollowUp,
  isSubmitting,
  errorMessage,
  onClose,
  onSubmit,
}: CallOutcomeDrawerProps) {
  const [outcome, setOutcome] = useState<CallOutcomeValue>('reached');
  const [interest, setInterest] = useState<InterestLevel>('hot');
  const [notes, setNotes] = useState('');
  const [followUp, setFollowUp] = useState('');

  useEffect(() => {
    if (!isOpen || !task) return;
    setOutcome(presetOutcome ?? 'reached');
    setInterest(presetOutcome && presetOutcome !== 'reached' ? 'none' : 'hot');
    setNotes(task.notes ?? '');
    setFollowUp(presetFollowUp ?? formatDatetimeLocal(task.dueAt));
  }, [isOpen, task, presetOutcome, presetFollowUp]);

  if (!isOpen || !task) return null;

  const interestDisabled = outcome !== 'reached';
  const followUpDisabled = outcome === 'do_not_call' || outcome === 'bad_number';

  return (
    <div className="fixed inset-0 z-50 flex items-stretch justify-end">
      <button
        type="button"
        className="h-full flex-1 bg-black/40"
        aria-label="Close"
        onClick={onClose}
        disabled={isSubmitting}
      />
      <div className="h-full w-full max-w-md overflow-y-auto bg-white p-6 shadow-2xl">
        <div className="flex items-start justify-between">
          <div>
            <p className="text-xs font-semibold uppercase tracking-widest text-slate-400">Log Call</p>
            <h3 className="mt-1 text-xl font-semibold text-slate-900">{task.plaintiffName}</h3>
            <p className="text-sm text-slate-500">Tier {task.tier ?? '—'} • {task.phone ?? 'No phone'}</p>
          </div>
          <button
            type="button"
            className="text-sm font-medium text-slate-500 hover:text-slate-700"
            onClick={onClose}
            disabled={isSubmitting}
          >
            Close
          </button>
        </div>

        <form
          className="mt-6 space-y-5"
          onSubmit={(e) => {
            e.preventDefault();
            void onSubmit({ outcome, interest, notes, followUp });
          }}
        >
          <div>
            <label className="block text-sm font-medium text-slate-700">Outcome</label>
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={outcome}
              onChange={(e) => {
                const next = e.target.value as CallOutcomeValue;
                setOutcome(next);
                if (next !== 'reached') setInterest('none');
                else if (interest === 'none') setInterest('hot');
                if (next === 'bad_number' || next === 'do_not_call') setFollowUp('');
              }}
              disabled={isSubmitting}
            >
              {CALL_OUTCOME_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700">Interest level</label>
            <select
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={interest}
              onChange={(e) => setInterest(e.target.value as InterestLevel)}
              disabled={interestDisabled || isSubmitting}
            >
              {INTEREST_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
            {interestDisabled && (
              <p className="mt-1 text-xs text-slate-500">Only captured when you reached them.</p>
            )}
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700">Notes</label>
            <textarea
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              rows={3}
              placeholder="Who you spoke with, what was discussed…"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              disabled={isSubmitting}
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-slate-700">Next follow-up</label>
            <input
              type="datetime-local"
              className="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-sm"
              value={followUp}
              onChange={(e) => setFollowUp(e.target.value)}
              disabled={followUpDisabled || isSubmitting}
            />
            {followUpDisabled && (
              <p className="mt-1 text-xs text-slate-500">No follow-up for wrong number / do not call.</p>
            )}
          </div>

          {errorMessage && (
            <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{errorMessage}</p>
          )}

          <div className="flex gap-3 pt-2">
            <button
              type="button"
              className="flex-1 rounded-lg border border-slate-300 px-4 py-2.5 text-sm font-medium text-slate-700"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancel
            </button>
            <button
              type="submit"
              className="flex-1 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-medium text-white disabled:opacity-50"
              disabled={isSubmitting}
            >
              {isSubmitting ? 'Saving…' : 'Save'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// --- Helpers ---

function formatDatetimeLocal(value: string | null): string {
  if (!value) return '';
  const parsed = Date.parse(value);
  if (Number.isNaN(parsed)) return '';
  return new Date(parsed).toISOString().slice(0, 16);
}

function addDays(days: number): string {
  const now = new Date();
  now.setDate(now.getDate() + days);
  return now.toISOString();
}

export default OpsConsolePage;
