import React, { useCallback, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { DashboardError } from './DashboardError';
import { useOpenTasksQueue } from '../hooks/useOpenTasksQueue';
import { formatDateTime } from '../utils/formatters';
import DemoLockCard from './DemoLockCard';
import { DEFAULT_DEMO_LOCK_MESSAGE } from '../hooks/metricsState';
import SectionHeader from './SectionHeader';
import StatusMessage from './StatusMessage';
import RefreshButton from './RefreshButton';

const SKELETON_ROWS = 6;

const TaskQueuePanel: React.FC = () => {
  const navigate = useNavigate();
  const { state, refetch } = useOpenTasksQueue();

  const rows = state.data ?? [];
  const status = state.status;
  const isLoading = status === 'idle' || status === 'loading';
  const isError = status === 'error';
  const isDemoLocked = status === 'demo_locked';
  const hasRows = status === 'ready' && rows.length > 0;
  const showSkeleton = isLoading && rows.length === 0;
  const showEmpty = status === 'ready' && rows.length === 0;
  const refreshingBanner = isLoading && rows.length > 0;
  const displayError = state.errorMessage ?? (state.error instanceof Error ? state.error.message : null);
  const statusClasses = useMemo(() => createStatusClassMap(), []);

  const handleRefresh = useCallback(() => refetch(), [refetch]);

  const handleNavigate = useCallback(
    (plaintiffId: string) => {
      if (!plaintiffId) {
        return;
      }
      navigate(`/plaintiffs/${encodeURIComponent(plaintiffId)}#plaintiff-tasks`);
    },
    [navigate],
  );

  const handleRowKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTableRowElement>, plaintiffId: string) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        handleNavigate(plaintiffId);
      }
    },
    [handleNavigate],
  );

  return (
    <section className="df-card space-y-4">
      <SectionHeader
        title="Task queue"
        description="Open plaintiff tasks ordered by due date."
        actions={<RefreshButton onClick={handleRefresh} isLoading={isLoading} hasData={rows.length > 0} />}
      />

      {isDemoLocked ? (
        <DemoLockCard description={state.lockMessage ?? DEFAULT_DEMO_LOCK_MESSAGE} />
      ) : (
        <>
          {refreshingBanner ? <StatusMessage tone="info">Refreshing tasks…</StatusMessage> : null}

          {showSkeleton ? (
            <SkeletonTable />
          ) : isError ? (
            <DashboardError
              message={displayError ?? 'Unable to load the task queue.'}
              onRetry={() => void handleRefresh()}
            />
          ) : showEmpty ? (
            <EmptyState />
          ) : hasRows ? (
            <div className="overflow-hidden rounded-md border border-slate-100">
              <table className="min-w-full divide-y divide-slate-100">
                <thead className="bg-slate-50">
                  <tr>
                    <HeaderCell>Plaintiff</HeaderCell>
                    <HeaderCell>Kind</HeaderCell>
                    <HeaderCell>Due</HeaderCell>
                    <HeaderCell>Status</HeaderCell>
                    <HeaderCell>Note</HeaderCell>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 bg-white">
                  {rows.map((row) => (
                    <tr
                      key={row.taskId}
                      className="cursor-pointer hover:bg-slate-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-blue-500/40"
                      onClick={() => handleNavigate(row.plaintiffId)}
                      onKeyDown={(event) => handleRowKeyDown(event, row.plaintiffId)}
                      tabIndex={0}
                    >
                      <BodyCell>
                        <div className="font-medium text-slate-900">{row.plaintiffName}</div>
                        <div className="text-xs text-slate-500">{row.firmName ?? '—'}</div>
                      </BodyCell>
                      <BodyCell>{row.kind}</BodyCell>
                      <BodyCell>{formatDue(row.dueAt, row.createdAt)}</BodyCell>
                      <BodyCell>
                        <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${statusClasses[row.status.toLowerCase()] ?? statusClasses.default}`}>
                          {titleCase(row.status)}
                        </span>
                      </BodyCell>
                      <BodyCell>
                        <span className="line-clamp-2 text-sm text-slate-600" title={row.note ?? undefined}>
                          {row.note ? truncate(row.note, 120) : '—'}
                        </span>
                      </BodyCell>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <StatusMessage tone="info">Loading task queue…</StatusMessage>
          )}
        </>
      )}
    </section>
  );
};

function createStatusClassMap(): Record<string, string> {
  return {
    open: 'bg-blue-50 text-blue-700 ring-1 ring-inset ring-blue-200',
    in_progress: 'bg-amber-50 text-amber-700 ring-1 ring-inset ring-amber-200',
    done: 'bg-emerald-50 text-emerald-700 ring-1 ring-inset ring-emerald-200',
    cancelled: 'bg-slate-200 text-slate-600',
    default: 'bg-slate-100 text-slate-600',
  };
}

function formatDue(dueAt: string | null, createdAt: string | null): string {
  if (dueAt) {
    const formatted = formatDateTime(dueAt);
    return formatted === '—' ? 'No due date' : formatted;
  }
  if (createdAt) {
    const created = formatDateTime(createdAt);
    return created === '—' ? 'Created (unknown)' : `Created ${created}`;
  }
  return 'No due date';
}

function titleCase(value: string): string {
  return value
    .split(/[\s_]+/)
    .map((part) => (part ? part[0].toUpperCase() + part.slice(1) : ''))
    .join(' ');
}

function truncate(value: string, maxLength: number): string {
  if (value.length <= maxLength) {
    return value;
  }
  return `${value.slice(0, maxLength - 1)}…`;
}

function SkeletonTable(): React.ReactElement {
  return (
    <div className="animate-pulse rounded-md border border-slate-100">
      <table className="min-w-full divide-y divide-slate-100">
        <thead className="bg-slate-50">
          <tr>
            {Array.from({ length: 5 }).map((_, idx) => (
              <HeaderCell key={idx}> </HeaderCell>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100 bg-white">
          {Array.from({ length: SKELETON_ROWS }).map((_, idx) => (
            <tr key={idx}>
              {Array.from({ length: 5 }).map((__, colIdx) => (
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
      <p className="text-sm font-medium text-slate-600">No open tasks are queued right now.</p>
      <p className="mt-1 text-xs text-slate-500">Tasks appear when plaintiffs need follow-up activity.</p>
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

export default TaskQueuePanel;
