import { memo, useCallback, useMemo, useState } from 'react';
import { DashboardError } from './DashboardError';
import { InlineSpinner } from './InlineSpinner';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import { isTaskOpen, usePlaintiffTasks, type PlaintiffTask } from '../hooks/usePlaintiffTasks';
import { supabaseClient } from '../lib/supabaseClient';
import { formatDateTime } from '../utils/formatters';

interface PlaintiffTasksSectionProps {
  plaintiffId: string;
}

function PlaintiffTasksSection({ plaintiffId }: PlaintiffTasksSectionProps) {
  const normalizedId = useMemo(() => (plaintiffId ?? '').trim(), [plaintiffId]);
  const { data, status, error, errorMessage, lockMessage, refetch } = usePlaintiffTasks(
    normalizedId.length > 0 ? normalizedId : null,
  );
  const tasks = data ?? [];
  const isLoading = status === 'loading' || status === 'idle';
  const isError = status === 'error';
  const isDemoLocked = status === 'demo_locked';
  const taskProblem = errorMessage ?? (typeof error === 'string' ? error : error?.message) ?? null;
  const [actionError, setActionError] = useState<string | null>(null);
  const [updatingTaskId, setUpdatingTaskId] = useState<string | null>(null);

  const openTasks = useMemo(() => tasks.filter((task) => isTaskOpen(task.status)), [tasks]);
  const closedTasks = useMemo(() => tasks.filter((task) => !isTaskOpen(task.status)), [tasks]);

  const handleRefresh = useCallback(() => {
    void refetch();
  }, [refetch]);

  const handleMarkDone = useCallback(
    async (task: PlaintiffTask) => {
      if (!task?.id) {
        return;
      }
      setActionError(null);
      setUpdatingTaskId(task.id);
      try {
        const { error: updateError } = await supabaseClient
          .from('plaintiff_tasks')
          .update({ status: 'done', completed_at: new Date().toISOString() })
          .eq('id', task.id);
        if (updateError) {
          throw updateError;
        }
        await refetch();
      } catch (err) {
        console.error('[PlaintiffTasksSection] failed to mark task done', err);
        const message = err instanceof Error && err.message ? err.message : 'Failed to update task.';
        setActionError(message);
      } finally {
        setUpdatingTaskId(null);
      }
    },
    [refetch],
  );

  return (
    <section id="plaintiff-tasks" className="rounded-3xl border border-slate-200 bg-white shadow-sm">
      <header className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Tasks</h2>
          <p className="text-xs text-slate-500">Manage call and follow-up work linked to this plaintiff.</p>
        </div>
        <button
          type="button"
          onClick={handleRefresh}
          disabled={isLoading}
          className="inline-flex items-center rounded-full border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 transition hover:bg-slate-100 disabled:opacity-60"
        >
          {isLoading ? (
            <span className="flex items-center gap-2">
              <InlineSpinner />
              Loading…
            </span>
          ) : (
            'Refresh'
          )}
        </button>
      </header>

      <div className="space-y-5 px-5 py-5">
        {actionError ? <p className="text-sm text-rose-600">{actionError}</p> : null}

        {isDemoLocked ? (
          <p className="rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-600">
            {lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE}
          </p>
        ) : isError ? (
          <DashboardError message={taskProblem ?? 'Unable to load tasks for this plaintiff.'} onRetry={handleRefresh} />
        ) : (
          <>
            {isLoading && tasks.length === 0 ? (
              <div className="flex items-center gap-3 rounded-2xl border border-dashed border-slate-200 bg-slate-50 px-4 py-6 text-sm text-slate-600">
                <InlineSpinner />
                <span>Loading tasks…</span>
              </div>
            ) : null}

            {!isLoading && openTasks.length === 0 && closedTasks.length === 0 ? (
              <p className="text-sm text-slate-500">No tasks have been captured for this plaintiff yet.</p>
            ) : null}

            {openTasks.length > 0 ? (
              <div className="overflow-x-auto rounded-2xl border border-slate-100">
                <table className="min-w-full divide-y divide-slate-100 text-left">
                  <thead className="bg-slate-50 text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <tr>
                      <th scope="col" className="px-4 py-3 text-left">
                        Kind
                      </th>
                      <th scope="col" className="px-4 py-3 text-left">
                        Status
                      </th>
                      <th scope="col" className="px-4 py-3 text-left">
                        Due
                      </th>
                      <th scope="col" className="px-4 py-3 text-left">
                        Note
                      </th>
                      <th scope="col" className="px-4 py-3 text-left">
                        Created
                      </th>
                      <th scope="col" className="px-4 py-3 text-right">
                        Action
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
                    {openTasks.map((task) => (
                      <tr key={task.id}>
                        <td className="px-4 py-3">{task.kind}</td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${taskStatusClass(task.status)}`}
                          >
                            {formatTaskStatus(task.status)}
                          </span>
                        </td>
                        <td className="px-4 py-3">{formatTaskDue(task)}</td>
                        <td className="px-4 py-3">
                          <span className="line-clamp-2" title={task.note ?? undefined}>
                            {task.note ?? '—'}
                          </span>
                        </td>
                        <td className="px-4 py-3">{formatDateTime(task.createdAt)}</td>
                        <td className="px-4 py-3 text-right">
                          <button
                            type="button"
                            onClick={() => void handleMarkDone(task)}
                            disabled={updatingTaskId === task.id}
                            className="inline-flex items-center rounded-full border border-emerald-600 px-3 py-1 text-xs font-semibold text-emerald-700 transition hover:bg-emerald-50 disabled:opacity-60"
                          >
                            {updatingTaskId === task.id ? (
                              <span className="flex items-center gap-2">
                                <InlineSpinner />
                                Updating…
                              </span>
                            ) : (
                              'Mark done'
                            )}
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : null}

            {!isLoading && openTasks.length === 0 && closedTasks.length > 0 ? (
              <p className="text-sm text-slate-500">No open tasks right now.</p>
            ) : null}

            {closedTasks.length > 0 ? (
              <details className="overflow-hidden rounded-2xl border border-slate-100 bg-slate-50" data-testid="completed-task-list">
                <summary className="cursor-pointer select-none px-4 py-3 text-sm font-semibold text-slate-700">
                  Completed tasks ({closedTasks.length})
                </summary>
                <div className="overflow-x-auto border-t border-slate-100 px-4 py-4">
                  <table className="min-w-full divide-y divide-slate-100 text-left">
                    <thead className="bg-slate-100 text-xs font-semibold uppercase tracking-wide text-slate-500">
                      <tr>
                        <th scope="col" className="px-4 py-3 text-left">
                          Kind
                        </th>
                        <th scope="col" className="px-4 py-3 text-left">
                          Status
                        </th>
                        <th scope="col" className="px-4 py-3 text-left">
                          Completed
                        </th>
                        <th scope="col" className="px-4 py-3 text-left">
                          Note
                        </th>
                        <th scope="col" className="px-4 py-3 text-left">
                          Created
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-slate-100 text-sm text-slate-700">
                      {closedTasks.map((task) => (
                        <tr key={task.id}>
                          <td className="px-4 py-3">{task.kind}</td>
                          <td className="px-4 py-3">
                            <span
                              className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold ${taskStatusClass(task.status)}`}
                            >
                              {formatTaskStatus(task.status)}
                            </span>
                          </td>
                          <td className="px-4 py-3">{task.completedAt ? formatDateTime(task.completedAt) : '—'}</td>
                          <td className="px-4 py-3">
                            <span className="line-clamp-2" title={task.note ?? undefined}>
                              {task.note ?? '—'}
                            </span>
                          </td>
                          <td className="px-4 py-3">{formatDateTime(task.createdAt)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            ) : null}
          </>
        )}
      </div>
    </section>
  );
}

function taskStatusClass(status: PlaintiffTask['status']): string {
  switch (status) {
    case 'open':
      return 'bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200';
    case 'in_progress':
      return 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200';
    case 'done':
      return 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200';
    case 'cancelled':
      return 'bg-slate-200 text-slate-600';
    default:
      return 'bg-slate-100 text-slate-600';
  }
}

function formatTaskStatus(status: PlaintiffTask['status']): string {
  return status
    .split(/[\s_]+/)
    .map((segment) => (segment ? segment[0].toUpperCase() + segment.slice(1) : ''))
    .join(' ');
}

function formatTaskDue(task: PlaintiffTask): string {
  if (task.dueAt) {
    const formatted = formatDateTime(task.dueAt);
    return formatted === '—' ? 'No due date' : formatted;
  }
  if (task.createdAt) {
    const created = formatDateTime(task.createdAt);
    return created === '—' ? 'Created (unknown)' : `Created ${created}`;
  }
  return 'No due date';
}

export default memo(PlaintiffTasksSection);
