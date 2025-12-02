/**
 * MomEnforcementConsolePage - Mom's daily enforcement command center
 *
 * 4 screens in one tabbed interface:
 * 1. Pipeline Overview - Where each judgment sits in the workflow
 * 2. Signature Queue - Documents awaiting attorney signature
 * 3. Call Queue - Today's plaintiff calls (existing OpsConsole functionality)
 * 4. Activity Feed - Recent enforcement actions
 *
 * Designed for clarity: large text, obvious buttons, minimal cognitive load.
 */
import { useCallback, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import {
  Activity,
  FileSignature,
  LayoutDashboard,
  Phone,
  RefreshCw,
  CheckCircle2,
  AlertCircle,
  Clock,
  ArrowUpRight,
} from 'lucide-react';
import MetricsGate from '../components/MetricsGate';
import {
  useEnforcementPipeline,
  STAGE_LABELS,
  STAGE_COLORS,
  STAGE_ORDER,
  type EnforcementPipelineRow,
  type PipelineStage,
  type PipelineFilters,
} from '../hooks/useEnforcementPipeline';
import {
  useSignatureQueue,
  markActionSigned,
  ACTION_TYPE_LABELS,
  ACTION_TYPE_COLORS,
  type SignatureQueueRow,
  type ActionType,
} from '../hooks/useSignatureQueue';
import {
  useActivityFeedEnforcement,
  ACTION_STATUS_COLORS,
  ACTION_TYPE_ICONS,
  type ActivityFeedRow,
} from '../hooks/useActivityFeedEnforcement';
import { useOpsConsole } from '../hooks/useOpsConsole';
import { formatCurrency, formatDateTime } from '../utils/formatters';

type TabId = 'pipeline' | 'signatures' | 'calls' | 'activity';

const TABS: Array<{ id: TabId; label: string; icon: React.ComponentType<{ className?: string }> }> = [
  { id: 'pipeline', label: 'Pipeline', icon: LayoutDashboard },
  { id: 'signatures', label: 'Signatures', icon: FileSignature },
  { id: 'calls', label: 'Call Queue', icon: Phone },
  { id: 'activity', label: 'Activity', icon: Activity },
];

export function MomEnforcementConsolePage() {
  const [activeTab, setActiveTab] = useState<TabId>('pipeline');
  const [filters, setFilters] = useState<PipelineFilters>({
    stage: 'all',
    minScore: null,
    minBalance: null,
  });

  // Data hooks
  const pipeline = useEnforcementPipeline({ filters, limit: 200 });
  const signatures = useSignatureQueue();
  const activity = useActivityFeedEnforcement();
  const callQueue = useOpsConsole({ limit: 50 });

  const handleRefreshAll = useCallback(async () => {
    await Promise.all([
      pipeline.refetch(),
      signatures.refetch(),
      activity.refetch(),
      callQueue.refetch(),
    ]);
  }, [pipeline, signatures, activity, callQueue]);

  const isAnyLoading =
    pipeline.state.status === 'loading' ||
    signatures.state.status === 'loading' ||
    activity.state.status === 'loading' ||
    callQueue.state.status === 'loading';

  // Badge counts for tabs
  const signatureBadge = signatures.urgentCount > 0 ? signatures.urgentCount : null;
  const callsBadge = callQueue.data?.overdue ?? 0;
  const activityBadge = activity.todayCount > 0 ? activity.todayCount : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-slate-900">Mom's Enforcement Console</h1>
          <p className="mt-1 text-sm text-slate-500">
            Pipeline status, signatures, calls, and recent activity
          </p>
        </div>
        <button
          type="button"
          onClick={() => void handleRefreshAll()}
          disabled={isAnyLoading}
          className="inline-flex items-center gap-2 rounded-lg border border-slate-200 bg-white px-4 py-2 text-sm font-medium text-slate-700 shadow-sm transition-colors hover:bg-slate-50 disabled:opacity-50"
        >
          <RefreshCw className={`h-4 w-4 ${isAnyLoading ? 'animate-spin' : ''}`} />
          Refresh All
        </button>
      </div>

      {/* Tab Navigation */}
      <div className="border-b border-slate-200">
        <nav className="-mb-px flex space-x-6">
          {TABS.map((tab) => {
            const Icon = tab.icon;
            const isActive = activeTab === tab.id;
            const badge =
              tab.id === 'signatures' ? signatureBadge :
              tab.id === 'calls' ? (callsBadge > 0 ? callsBadge : null) :
              tab.id === 'activity' ? activityBadge :
              null;

            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={`group relative flex items-center gap-2 border-b-2 px-1 py-4 text-sm font-medium transition-colors ${
                  isActive
                    ? 'border-indigo-500 text-indigo-600'
                    : 'border-transparent text-slate-500 hover:border-slate-300 hover:text-slate-700'
                }`}
              >
                <Icon className="h-4 w-4" />
                {tab.label}
                {badge != null && badge > 0 && (
                  <span
                    className={`ml-1.5 rounded-full px-2 py-0.5 text-xs font-semibold ${
                      tab.id === 'signatures' || tab.id === 'calls'
                        ? 'bg-red-100 text-red-700'
                        : 'bg-indigo-100 text-indigo-700'
                    }`}
                  >
                    {badge}
                  </span>
                )}
              </button>
            );
          })}
        </nav>
      </div>

      {/* Tab Content */}
      <div className="min-h-[600px]">
        {activeTab === 'pipeline' && (
          <PipelineTab
            state={pipeline.state}
            data={pipeline.data ?? []}
            stageCounts={pipeline.stageCounts}
            filters={filters}
            onFiltersChange={setFilters}
            onRefetch={pipeline.refetch}
          />
        )}
        {activeTab === 'signatures' && (
          <SignaturesTab
            state={signatures.state}
            data={signatures.data ?? []}
            totalCount={signatures.totalCount}
            urgentCount={signatures.urgentCount}
            onRefetch={signatures.refetch}
          />
        )}
        {activeTab === 'calls' && (
          <CallsTab
            state={callQueue.state}
            data={callQueue.data}
            onRefetch={callQueue.refetch}
          />
        )}
        {activeTab === 'activity' && (
          <ActivityTab
            state={activity.state}
            data={activity.data ?? []}
            todayCount={activity.todayCount}
            onRefetch={activity.refetch}
          />
        )}
      </div>
    </div>
  );
}

// ============================================================================
// Screen 1: Pipeline Overview
// ============================================================================

interface PipelineTabProps {
  state: ReturnType<typeof useEnforcementPipeline>['state'];
  data: EnforcementPipelineRow[];
  stageCounts: Record<PipelineStage, number>;
  filters: PipelineFilters;
  onFiltersChange: (filters: PipelineFilters) => void;
  onRefetch: () => Promise<void>;
}

function PipelineTab({ state, data, stageCounts, filters, onFiltersChange, onRefetch }: PipelineTabProps) {
  const navigate = useNavigate();

  const handleStageFilter = (stage: PipelineStage | 'all') => {
    onFiltersChange({ ...filters, stage });
  };

  return (
    <div className="space-y-6">
      {/* Stage Summary Cards */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        {STAGE_ORDER.map((stage) => {
          const count = stageCounts[stage];
          const isActive = filters.stage === stage;
          return (
            <button
              key={stage}
              type="button"
              onClick={() => handleStageFilter(isActive ? 'all' : stage)}
              className={`rounded-xl border p-4 text-left transition-all ${
                isActive
                  ? 'border-indigo-300 bg-indigo-50 ring-2 ring-indigo-200'
                  : 'border-slate-200 bg-white hover:border-slate-300 hover:shadow-sm'
              }`}
            >
              <p className="text-2xl font-bold text-slate-900">{count}</p>
              <p className="mt-1 text-xs font-medium text-slate-600">{STAGE_LABELS[stage]}</p>
            </button>
          );
        })}
      </div>

      {/* Filters Row */}
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-200 bg-slate-50 p-4">
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-slate-700">Min Score:</label>
          <input
            type="number"
            min={0}
            max={100}
            placeholder="0"
            value={filters.minScore ?? ''}
            onChange={(e) => onFiltersChange({ ...filters, minScore: e.target.value ? Number(e.target.value) : null })}
            className="w-20 rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm font-medium text-slate-700">Min Balance:</label>
          <input
            type="number"
            min={0}
            placeholder="$0"
            value={filters.minBalance ?? ''}
            onChange={(e) => onFiltersChange({ ...filters, minBalance: e.target.value ? Number(e.target.value) : null })}
            className="w-28 rounded-md border border-slate-300 px-2 py-1 text-sm"
          />
        </div>
        {(filters.stage !== 'all' || filters.minScore != null || filters.minBalance != null) && (
          <button
            type="button"
            onClick={() => onFiltersChange({ stage: 'all', minScore: null, minBalance: null })}
            className="text-sm text-indigo-600 hover:text-indigo-800"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* Pipeline Table */}
      <MetricsGate
        state={state}
        errorTitle="Pipeline unavailable"
        onRetry={() => void onRefetch()}
        ready={
          data.length === 0 ? (
            <EmptyState message="No judgments match current filters" />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full">
                <thead className="border-b border-slate-100 bg-slate-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-3">Case #</th>
                    <th className="px-4 py-3">Debtor</th>
                    <th className="px-4 py-3">Amount</th>
                    <th className="px-4 py-3">Score</th>
                    <th className="px-4 py-3">Stage</th>
                    <th className="px-4 py-3">Actions</th>
                    <th className="px-4 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.slice(0, 100).map((row) => (
                    <tr
                      key={row.judgmentId}
                      className="cursor-pointer transition-colors hover:bg-slate-50"
                      onClick={() => navigate(`/judgments/${row.judgmentId}`)}
                    >
                      <td className="px-4 py-3">
                        <span className="font-mono text-sm text-slate-900">{row.caseIndexNumber}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="font-medium text-slate-900">{row.debtorName}</span>
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">
                        {formatCurrency(row.principalAmount)}
                      </td>
                      <td className="px-4 py-3">
                        <ScoreBadge score={row.collectabilityScore} />
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${STAGE_COLORS[row.pipelineStage]}`}>
                          {STAGE_LABELS[row.pipelineStage]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-sm text-slate-600">
                        {row.totalActions > 0 ? (
                          <span>
                            {row.completedActions}/{row.totalActions} done
                            {row.awaitingSignature > 0 && (
                              <span className="ml-1 text-red-600">({row.awaitingSignature} ✍️)</span>
                            )}
                          </span>
                        ) : (
                          <span className="text-slate-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <ArrowUpRight className="h-4 w-4 text-slate-400" />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )
        }
        loadingFallback={<TableSkeleton rows={8} cols={7} />}
      />
    </div>
  );
}

// ============================================================================
// Screen 2: Signature Queue
// ============================================================================

interface SignaturesTabProps {
  state: ReturnType<typeof useSignatureQueue>['state'];
  data: SignatureQueueRow[];
  totalCount: number;
  urgentCount: number;
  onRefetch: () => Promise<void>;
}

function SignaturesTab({ state, data, totalCount, urgentCount, onRefetch }: SignaturesTabProps) {
  const [processingId, setProcessingId] = useState<string | null>(null);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const handleMarkSigned = useCallback(async (action: SignatureQueueRow) => {
    setProcessingId(action.actionId);
    const result = await markActionSigned(action.actionId);
    setProcessingId(null);

    if (result.success) {
      setToastMessage(`Marked "${action.actionType}" as signed ✓`);
      await onRefetch();
    } else {
      setToastMessage(`Error: ${result.error}`);
    }

    setTimeout(() => setToastMessage(null), 3000);
  }, [onRefetch]);

  return (
    <div className="space-y-6">
      {/* Toast */}
      {toastMessage && (
        <div className="fixed right-6 top-20 z-50 rounded-lg bg-slate-800 px-4 py-2 text-sm font-medium text-white shadow-lg">
          {toastMessage}
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-3xl font-bold text-slate-900">{totalCount}</p>
          <p className="mt-1 text-sm text-slate-500">Pending Signatures</p>
        </div>
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="text-3xl font-bold text-red-700">{urgentCount}</p>
          <p className="mt-1 text-sm text-red-600">Urgent (&gt;3 days)</p>
        </div>
      </div>

      {/* Signature Queue Table */}
      <MetricsGate
        state={state}
        errorTitle="Signature queue unavailable"
        onRetry={() => void onRefetch()}
        ready={
          data.length === 0 ? (
            <EmptyState message="No documents awaiting signature! 🎉" icon={<CheckCircle2 className="h-12 w-12 text-emerald-500" />} />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full">
                <thead className="border-b border-slate-100 bg-slate-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-3">Case #</th>
                    <th className="px-4 py-3">Debtor</th>
                    <th className="px-4 py-3">Amount</th>
                    <th className="px-4 py-3">Action Type</th>
                    <th className="px-4 py-3">Age</th>
                    <th className="px-4 py-3">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {data.map((row) => {
                    const isUrgent = row.ageDays > 3;
                    const isProcessing = processingId === row.actionId;
                    return (
                      <tr
                        key={row.actionId}
                        className={`transition-colors ${isUrgent ? 'bg-red-50/50' : 'hover:bg-slate-50'}`}
                      >
                        <td className="px-4 py-3">
                          <Link
                            to={`/judgments/${row.judgmentId}`}
                            className="font-mono text-sm text-indigo-600 hover:text-indigo-800"
                          >
                            {row.caseIndexNumber}
                          </Link>
                        </td>
                        <td className="px-4 py-3 font-medium text-slate-900">{row.debtorName}</td>
                        <td className="px-4 py-3 text-sm text-slate-600">{formatCurrency(row.principalAmount)}</td>
                        <td className="px-4 py-3">
                          <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-medium ${ACTION_TYPE_COLORS[row.actionType as ActionType] || 'bg-slate-100 text-slate-600'}`}>
                            {ACTION_TYPE_LABELS[row.actionType as ActionType] || row.actionType}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className={`text-sm font-medium ${isUrgent ? 'text-red-600' : 'text-slate-600'}`}>
                            {row.ageDays} day{row.ageDays !== 1 ? 's' : ''}
                            {isUrgent && <AlertCircle className="ml-1 inline h-4 w-4" />}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <button
                            type="button"
                            onClick={() => void handleMarkSigned(row)}
                            disabled={isProcessing}
                            className="inline-flex items-center gap-1.5 rounded-lg bg-emerald-600 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-emerald-700 disabled:opacity-50"
                          >
                            {isProcessing ? (
                              <RefreshCw className="h-4 w-4 animate-spin" />
                            ) : (
                              <CheckCircle2 className="h-4 w-4" />
                            )}
                            Signed & Sent
                          </button>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        }
        loadingFallback={<TableSkeleton rows={5} cols={6} />}
      />
    </div>
  );
}

// ============================================================================
// Screen 3: Call Queue
// ============================================================================

interface CallsTabProps {
  state: ReturnType<typeof useOpsConsole>['state'];
  data: ReturnType<typeof useOpsConsole>['data'];
  onRefetch: () => Promise<void>;
}

function CallsTab({ state, data, onRefetch }: CallsTabProps) {
  const navigate = useNavigate();
  const tasks = data?.tasks ?? [];
  const overdue = data?.overdue ?? 0;
  const dueToday = data?.dueToday ?? 0;

  return (
    <div className="space-y-6">
      {/* Summary Cards */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-xl border border-slate-200 bg-white p-4">
          <p className="text-3xl font-bold text-slate-900">{tasks.length}</p>
          <p className="mt-1 text-sm text-slate-500">Total Calls</p>
        </div>
        <div className="rounded-xl border border-red-200 bg-red-50 p-4">
          <p className="text-3xl font-bold text-red-700">{overdue}</p>
          <p className="mt-1 text-sm text-red-600">Overdue</p>
        </div>
        <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
          <p className="text-3xl font-bold text-amber-700">{dueToday}</p>
          <p className="mt-1 text-sm text-amber-600">Due Today</p>
        </div>
      </div>

      {/* Quick Link to Full Call Queue */}
      <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-4">
        <p className="text-sm text-indigo-800">
          <strong>Tip:</strong> For the full call workflow with outcome logging, use the{' '}
          <Link to="/ops-console" className="font-medium underline">
            Ops Console
          </Link>{' '}
          page.
        </p>
      </div>

      {/* Call Queue Preview */}
      <MetricsGate
        state={state}
        errorTitle="Call queue unavailable"
        onRetry={() => void onRefetch()}
        ready={
          tasks.length === 0 ? (
            <EmptyState message="No calls in the queue right now!" icon={<CheckCircle2 className="h-12 w-12 text-emerald-500" />} />
          ) : (
            <div className="overflow-x-auto rounded-xl border border-slate-200 bg-white">
              <table className="min-w-full">
                <thead className="border-b border-slate-100 bg-slate-50">
                  <tr className="text-left text-xs font-semibold uppercase tracking-wide text-slate-500">
                    <th className="px-4 py-3">Plaintiff</th>
                    <th className="px-4 py-3">Phone</th>
                    <th className="px-4 py-3">Tier</th>
                    <th className="px-4 py-3">Last Contact</th>
                    <th className="px-4 py-3">Status</th>
                    <th className="px-4 py-3">Due</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {tasks.slice(0, 20).map((task) => {
                    const isOverdue = task.dueAt && new Date(task.dueAt) < new Date();
                    return (
                      <tr
                        key={task.taskId}
                        className={`cursor-pointer transition-colors ${isOverdue ? 'bg-red-50/50' : 'hover:bg-slate-50'}`}
                        onClick={() => navigate(`/plaintiffs/${task.plaintiffId}`)}
                      >
                        <td className="px-4 py-3 font-medium text-slate-900">{task.plaintiffName}</td>
                        <td className="px-4 py-3 font-mono text-sm text-slate-600">{task.phone ?? '—'}</td>
                        <td className="px-4 py-3">
                          <TierBadge tier={task.tier} />
                        </td>
                        <td className="px-4 py-3 text-sm text-slate-600">
                          {task.lastContactAt ? formatDateTime(task.lastContactAt) : '—'}
                        </td>
                        <td className="px-4 py-3">
                          <span className="inline-flex rounded-full bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600">
                            {task.status}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-sm">
                          {task.dueAt ? (
                            <span className={isOverdue ? 'font-medium text-red-600' : 'text-slate-600'}>
                              {formatDateTime(task.dueAt)}
                            </span>
                          ) : (
                            '—'
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )
        }
        loadingFallback={<TableSkeleton rows={8} cols={6} />}
      />
    </div>
  );
}

// ============================================================================
// Screen 4: Activity Feed
// ============================================================================

interface ActivityTabProps {
  state: ReturnType<typeof useActivityFeedEnforcement>['state'];
  data: ActivityFeedRow[];
  todayCount: number;
  onRefetch: () => Promise<void>;
}

function ActivityTab({ state, data, todayCount, onRefetch }: ActivityTabProps) {
  return (
    <div className="space-y-6">
      {/* Summary */}
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <p className="text-3xl font-bold text-slate-900">{todayCount}</p>
        <p className="mt-1 text-sm text-slate-500">Actions Today</p>
      </div>

      {/* Activity Feed */}
      <MetricsGate
        state={state}
        errorTitle="Activity feed unavailable"
        onRetry={() => void onRefetch()}
        ready={
          data.length === 0 ? (
            <EmptyState message="No recent enforcement actions" />
          ) : (
            <div className="space-y-3">
              {data.map((row) => (
                <ActivityCard key={row.actionId} row={row} />
              ))}
            </div>
          )
        }
        loadingFallback={<ActivitySkeleton />}
      />
    </div>
  );
}

function ActivityCard({ row }: { row: ActivityFeedRow }) {
  const icon = ACTION_TYPE_ICONS[row.actionType] || '📄';
  const statusColor = ACTION_STATUS_COLORS[row.status] || 'bg-slate-100 text-slate-600';

  return (
    <Link
      to={`/judgments/${row.judgmentId}`}
      className="block rounded-xl border border-slate-200 bg-white p-4 transition-all hover:border-slate-300 hover:shadow-sm"
    >
      <div className="flex items-start gap-3">
        <span className="text-2xl">{icon}</span>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="font-medium text-slate-900">{row.debtorName}</span>
            <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${statusColor}`}>
              {row.status}
            </span>
          </div>
          <p className="mt-1 text-sm text-slate-600">
            {ACTION_TYPE_LABELS[row.actionType as ActionType] || row.actionType} • {row.caseIndexNumber}
          </p>
          {row.notes && (
            <p className="mt-2 text-sm text-slate-500 line-clamp-2">{row.notes}</p>
          )}
          <p className="mt-2 text-xs text-slate-400">
            <Clock className="inline h-3 w-3 mr-1" />
            {formatDateTime(row.createdAt)}
          </p>
        </div>
        <span className="text-sm font-medium text-slate-600">{formatCurrency(row.principalAmount)}</span>
      </div>
    </Link>
  );
}

// ============================================================================
// Shared Components
// ============================================================================

function ScoreBadge({ score }: { score: number | null }) {
  if (score == null) return <span className="text-slate-400">—</span>;

  const color =
    score >= 80 ? 'bg-emerald-100 text-emerald-700' :
    score >= 60 ? 'bg-amber-100 text-amber-700' :
    score >= 40 ? 'bg-orange-100 text-orange-700' :
    'bg-red-100 text-red-700';

  return (
    <span className={`inline-flex rounded-full px-2 py-0.5 text-xs font-semibold ${color}`}>
      {score}
    </span>
  );
}

function TierBadge({ tier }: { tier: string | null }) {
  const tierColor =
    tier === 'A' || tier === '0' ? 'bg-red-100 text-red-700' :
    tier === 'B' || tier === '1' ? 'bg-amber-100 text-amber-700' :
    tier === 'C' || tier === '2' ? 'bg-blue-100 text-blue-700' :
    'bg-slate-100 text-slate-600';

  return (
    <span className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${tierColor}`}>
      Tier {tier ?? '—'}
    </span>
  );
}

function EmptyState({ message, icon }: { message: string; icon?: React.ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center rounded-xl border border-slate-200 bg-white py-16">
      {icon || <Activity className="h-12 w-12 text-slate-300" />}
      <p className="mt-4 text-lg font-medium text-slate-700">{message}</p>
    </div>
  );
}

function TableSkeleton({ rows, cols }: { rows: number; cols: number }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white">
      <div className="border-b border-slate-100 bg-slate-50 p-4">
        <div className="h-4 w-48 animate-pulse rounded bg-slate-200" />
      </div>
      <div className="divide-y divide-slate-100">
        {Array.from({ length: rows }).map((_, i) => (
          <div key={i} className="flex gap-4 p-4">
            {Array.from({ length: cols }).map((__, j) => (
              <div key={j} className="h-4 flex-1 animate-pulse rounded bg-slate-100" />
            ))}
          </div>
        ))}
      </div>
    </div>
  );
}

function ActivitySkeleton() {
  return (
    <div className="space-y-3">
      {Array.from({ length: 5 }).map((_, i) => (
        <div key={i} className="rounded-xl border border-slate-200 bg-white p-4">
          <div className="flex gap-3">
            <div className="h-10 w-10 animate-pulse rounded-lg bg-slate-100" />
            <div className="flex-1 space-y-2">
              <div className="h-4 w-48 animate-pulse rounded bg-slate-100" />
              <div className="h-3 w-32 animate-pulse rounded bg-slate-50" />
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

export default MomEnforcementConsolePage;
