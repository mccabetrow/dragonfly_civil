/**
 * CaseDetailDrawer - Slide-out panel for viewing case details
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Uses the Drawer UI primitive and useJudgmentDetail hook to show:
 * - Case overview (plaintiff, defendant, amount, tier)
 * - Enforcement history
 * - Task list
 * - Priority timeline
 *
 * Features:
 * - Smooth slide animation
 * - Escape key to close
 * - Skeleton loading states
 * - Error handling
 */

import { type FC, useMemo } from 'react';
import { Drawer } from '../ui/Drawer';
import { TierBadge, Badge } from '../ui/Badge';
import { Skeleton, SkeletonText } from '../ui/Skeleton';
import { useJudgmentDetail } from '../../hooks/useJudgmentDetail';
import { AlertCircle, Calendar, User, DollarSign, Briefcase, CheckCircle2, Clock, XCircle } from 'lucide-react';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface CaseDetailDrawerProps {
  /** Case/judgment ID to display */
  caseId: string | null;
  /** Handler to close the drawer */
  onClose: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// FORMATTERS
// ═══════════════════════════════════════════════════════════════════════════

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  maximumFractionDigits: 0,
});

const dateFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
});

const dateTimeFormatter = new Intl.DateTimeFormat('en-US', {
  dateStyle: 'medium',
  timeStyle: 'short',
});

function formatCurrency(value: number | null | undefined): string {
  if (typeof value !== 'number') return '—';
  return currencyFormatter.format(value);
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return dateFormatter.format(parsed);
}

function formatDateTime(value: string | null | undefined): string {
  if (!value) return '—';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return '—';
  return dateTimeFormatter.format(parsed);
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

const CaseDetailDrawer: FC<CaseDetailDrawerProps> = ({ caseId, onClose }) => {
  const isOpen = Boolean(caseId);
  const { state, data, error, lockMessage } = useJudgmentDetail(caseId);

  const isLoading = state === 'idle' || state === 'loading';
  const isError = state === 'error';
  const isNotFound = state === 'not-found';
  const isDemoLocked = state === 'demo_locked';

  // Summary data with fallbacks
  const summary = data?.summary;
  const title = summary?.caseNumber ?? 'Case Details';
  const subtitle = summary?.plaintiffName ?? '';

  return (
    <Drawer
      isOpen={isOpen}
      onClose={onClose}
      title={isLoading ? 'Loading...' : title}
      description={isLoading ? undefined : subtitle}
      size="xl"
      position="right"
    >
      {/* Loading State */}
      {isLoading && <DrawerSkeleton />}

      {/* Error State */}
      {isError && (
        <div className="rounded-xl border border-rose-200 bg-rose-50 p-6 text-center">
          <AlertCircle className="mx-auto h-10 w-10 text-rose-400" />
          <p className="mt-3 font-semibold text-rose-700">Failed to load case</p>
          <p className="mt-1 text-sm text-rose-600">{error}</p>
        </div>
      )}

      {/* Not Found State */}
      {isNotFound && (
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-6 text-center">
          <AlertCircle className="mx-auto h-10 w-10 text-amber-400" />
          <p className="mt-3 font-semibold text-amber-700">Case not found</p>
          <p className="mt-1 text-sm text-amber-600">
            This case may have been archived, merged with another case, or the ID is incorrect. 
            Try searching for it on the Cases page.
          </p>
        </div>
      )}

      {/* Demo Locked State */}
      {isDemoLocked && (
        <div className="rounded-xl border border-slate-200 bg-slate-50 p-6 text-center">
          <p className="font-semibold text-slate-700">Demo Mode</p>
          <p className="mt-1 text-sm text-slate-600">{lockMessage}</p>
        </div>
      )}

      {/* Ready State - Full Content */}
      {state === 'ready' && data && (
        <div className="space-y-6">
          {/* Overview Card */}
          <OverviewCard summary={data.summary} />

          {/* Tasks Section */}
          {data.tasks.length > 0 && (
            <TasksSection tasks={data.tasks} />
          )}

          {/* Enforcement History */}
          {data.enforcementHistory.length > 0 && (
            <HistorySection
              title="Enforcement History"
              entries={data.enforcementHistory.map((e) => ({
                id: e.id,
                title: e.stageLabel ?? e.stage ?? 'Unknown',
                subtitle: e.note ?? undefined,
                timestamp: e.changedAt,
                actor: e.changedBy,
              }))}
            />
          )}

          {/* Priority History */}
          {data.priorityHistory.length > 0 && (
            <HistorySection
              title="Priority Changes"
              entries={data.priorityHistory.map((e) => ({
                id: e.id,
                title: e.priorityLabel ?? e.priorityLevel ?? 'Unknown',
                subtitle: e.note ?? undefined,
                timestamp: e.changedAt,
                actor: e.changedBy,
              }))}
            />
          )}
        </div>
      )}
    </Drawer>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// SUB-COMPONENTS
// ═══════════════════════════════════════════════════════════════════════════

/** Loading skeleton for drawer content */
const DrawerSkeleton: FC = () => (
  <div className="space-y-6">
    <div className="rounded-xl border border-slate-200 p-6 space-y-4">
      <Skeleton className="h-4 w-24" />
      <SkeletonText lines={4} />
    </div>
    <div className="rounded-xl border border-slate-200 p-6 space-y-4">
      <Skeleton className="h-4 w-32" />
      <SkeletonText lines={3} />
    </div>
  </div>
);

/** Overview card showing key case information */
interface OverviewCardProps {
  summary: NonNullable<ReturnType<typeof useJudgmentDetail>['data']>['summary'];
}

const OverviewCard: FC<OverviewCardProps> = ({ summary }) => {
  const tier = summary.collectabilityTier?.toUpperCase() ?? null;

  return (
    <article className="rounded-xl border border-slate-200 bg-white">
      <header className="flex items-start justify-between gap-4 border-b border-slate-100 px-6 py-4">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Case Overview</p>
          <h3 className="mt-1 text-lg font-semibold text-slate-900">
            {summary.caseNumber ?? '—'}
          </h3>
        </div>
        {tier && ['A', 'B', 'C'].includes(tier) && (
          <TierBadge tier={tier} />
        )}
      </header>

      <div className="grid grid-cols-1 gap-4 p-6 sm:grid-cols-2">
        <DetailItem icon={User} label="Plaintiff" value={summary.plaintiffName} />
        <DetailItem icon={User} label="Defendant" value={summary.defendantName ?? '—'} />
        <DetailItem
          icon={DollarSign}
          label="Judgment Amount"
          value={formatCurrency(summary.judgmentAmount)}
        />
        <DetailItem
          icon={Calendar}
          label="Age"
          value={typeof summary.collectabilityAgeDays === 'number'
            ? `${summary.collectabilityAgeDays.toLocaleString()} days`
            : '—'}
        />
        <DetailItem
          icon={Briefcase}
          label="Enforcement Stage"
          value={summary.enforcementStageLabel ?? summary.enforcementStage ?? 'Pre-enforcement'}
        />
        <DetailItem
          icon={Clock}
          label="Stage Updated"
          value={formatDateTime(summary.enforcementStageUpdatedAt)}
        />
        <DetailItem
          icon={AlertCircle}
          label="Priority"
          value={summary.priorityLabel ?? summary.priorityLevel ?? 'Normal'}
        />
        <DetailItem
          icon={Calendar}
          label="Last Enriched"
          value={formatDateTime(summary.lastEnrichedAt)}
        />
      </div>
    </article>
  );
};

/** Single detail item in the overview card */
interface DetailItemProps {
  icon: typeof User;
  label: string;
  value: string;
}

const DetailItem: FC<DetailItemProps> = ({ icon: Icon, label, value }) => (
  <div className="flex items-start gap-3">
    <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-slate-100">
      <Icon className="h-4 w-4 text-slate-500" />
    </div>
    <div className="min-w-0">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-sm font-medium text-slate-900 truncate">{value}</p>
    </div>
  </div>
);

/** Tasks section showing pending work items */
interface TasksSectionProps {
  tasks: NonNullable<ReturnType<typeof useJudgmentDetail>['data']>['tasks'];
}

const TasksSection: FC<TasksSectionProps> = ({ tasks }) => {
  // Group tasks by status
  const pendingTasks = useMemo(() => tasks.filter((t) => t.status === 'pending'), [tasks]);
  const completedTasks = useMemo(() => tasks.filter((t) => t.status === 'completed'), [tasks]);

  return (
    <article className="rounded-xl border border-slate-200 bg-white">
      <header className="border-b border-slate-100 px-6 py-4">
        <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">Tasks</p>
        <div className="mt-1 flex items-center gap-2">
          <Badge variant="warning" size="sm">{pendingTasks.length} pending</Badge>
          <Badge variant="success" size="sm">{completedTasks.length} completed</Badge>
        </div>
      </header>

      <ul className="divide-y divide-slate-100">
        {tasks.slice(0, 10).map((task) => (
          <li key={task.id} className="flex items-center gap-3 px-6 py-3">
            {task.status === 'completed' ? (
              <CheckCircle2 className="h-5 w-5 shrink-0 text-emerald-500" />
            ) : task.status === 'failed' ? (
              <XCircle className="h-5 w-5 shrink-0 text-rose-500" />
            ) : (
              <Clock className="h-5 w-5 shrink-0 text-amber-500" />
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate text-sm font-medium text-slate-900">{task.label}</p>
              {task.dueAt && (
                <p className="text-xs text-slate-500">Due: {formatDate(task.dueAt)}</p>
              )}
            </div>
          </li>
        ))}
      </ul>
    </article>
  );
};

/** Generic history timeline section */
interface HistoryEntry {
  id: string;
  title: string;
  subtitle?: string;
  timestamp: string | null;
  actor?: string | null;
}

interface HistorySectionProps {
  title: string;
  entries: HistoryEntry[];
}

const HistorySection: FC<HistorySectionProps> = ({ title, entries }) => (
  <article className="rounded-xl border border-slate-200 bg-white">
    <header className="border-b border-slate-100 px-6 py-4">
      <p className="text-xs font-semibold uppercase tracking-wide text-slate-500">{title}</p>
    </header>

    <ol className="divide-y divide-slate-100">
      {entries.slice(0, 10).map((entry, index) => (
        <li key={entry.id} className="relative flex gap-4 px-6 py-4">
          {/* Timeline dot */}
          <div className="relative">
            <span
              className={`flex h-3 w-3 items-center justify-center rounded-full ${
                index === 0 ? 'bg-blue-500' : 'bg-slate-300'
              }`}
            />
            {index < entries.length - 1 && (
              <span className="absolute left-1/2 top-3 h-full w-px -translate-x-1/2 bg-slate-200" />
            )}
          </div>

          <div className="min-w-0 flex-1 pb-2">
            <p className="text-sm font-medium text-slate-900">{entry.title}</p>
            {entry.subtitle && (
              <p className="mt-0.5 text-sm text-slate-600">{entry.subtitle}</p>
            )}
            <p className="mt-1 text-xs text-slate-500">
              {formatDateTime(entry.timestamp)}
              {entry.actor && ` · ${entry.actor}`}
            </p>
          </div>
        </li>
      ))}
    </ol>
  </article>
);

export default CaseDetailDrawer;
