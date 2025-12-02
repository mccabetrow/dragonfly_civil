import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient, type DemoSafeResult } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';
import { buildDashboardError } from '../utils/dashboardErrors';

const DEFAULT_POLL_MS = 30000;
const CALL_QUEUE_LIMIT = 50;
const OPS_CONSOLE_LOCK_MESSAGE =
  'The Ops Console hides plaintiff-level calls in demo mode. Connect the production tenant to work the live queue.';
const CALL_QUEUE_VIEW = 'v_plaintiff_call_queue' as const;
const ENFORCEMENT_OVERVIEW_VIEW = 'v_enforcement_overview' as const;

type RawCallQueueRow = {
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
};

type RawOverviewRow = {
  enforcement_stage: string | null;
  case_count: number | string | null;
  total_judgment_amount: number | string | null;
};

export interface OpsCallTask {
  taskId: string;
  plaintiffId: string;
  plaintiffName: string;
  tier: string | null;
  phone: string | null;
  lastContactAt: string | null;
  daysSinceContact: number | null;
  dueAt: string | null;
  notes: string | null;
  status: string;
  priorityScore: number;
  queueIndex: number;
}

export interface OpsPipelineMetric {
  stage: string;
  label: string;
  caseCount: number;
  totalJudgmentAmount: number;
}

export interface OpsConsoleSnapshot {
  tasks: OpsCallTask[];
  nextBestTask: OpsCallTask | null;
  pipelineMetrics: OpsPipelineMetric[];
  dueToday: number;
  overdue: number;
}

export type UseOpsConsoleResult = MetricsHookResult<OpsConsoleSnapshot> & {
  lastUpdated: string | null;
  removeTask: (taskId: string) => void;
};

interface UseOpsConsoleOptions {
  autoRefreshMs?: number;
  limit?: number;
}

export function useOpsConsole(options: UseOpsConsoleOptions = {}): UseOpsConsoleResult {
  const autoRefreshMs = options.autoRefreshMs ?? DEFAULT_POLL_MS;
  const queueLimit = options.limit ?? CALL_QUEUE_LIMIT;
  const [state, setState] = useState<MetricsState<OpsConsoleSnapshot>>(() =>
    buildInitialMetricsState<OpsConsoleSnapshot>(),
  );
  const [lastUpdated, setLastUpdated] = useState<string | null>(null);
  const pollingRef = useRef<number | null>(null);
  const mountedRef = useRef(true);

  const loadOpsConsoleSnapshot = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setState(buildDemoLockedState<OpsConsoleSnapshot>(OPS_CONSOLE_LOCK_MESSAGE));
      return;
    }

    setState((previous) => buildLoadingMetricsState(previous));

    try {
      const [rawTasks, rawMetrics] = await Promise.all([fetchCallQueue(queueLimit), fetchPipelineMetrics()]);

      const now = new Date();
      const tasks = rawTasks
        .map((row) => mapCallTask(row, now))
        .filter((task): task is OpsCallTask => task !== null)
        .sort((a, b) => b.priorityScore - a.priorityScore)
        .map((task, index) => ({ ...task, queueIndex: index + 1 }));

      const pipelineMetrics = aggregatePipelineMetrics(rawMetrics);
      const { dueToday, overdue } = summarizeTaskDeadlines(tasks, now);

      const snapshot: OpsConsoleSnapshot = {
        tasks,
        nextBestTask: tasks[0] ?? null,
        pipelineMetrics,
        dueToday,
        overdue,
      };

      if (!mountedRef.current) {
        return;
      }

      setState(buildReadyMetricsState(snapshot));
      setLastUpdated(new Date().toISOString());
    } catch (err) {
      if (!mountedRef.current) {
        return;
      }

      console.debug('[useOpsConsole] failed to load ops console snapshot', err);
      const { error: normalizedError, message } = buildDashboardError(err, {
        viewName: 'Ops console queue + metrics',
      });
      setState(buildErrorMetricsState<OpsConsoleSnapshot>(normalizedError, { message }));
    }
  }, [queueLimit]);

  useEffect(() => {
    mountedRef.current = true;
    void loadOpsConsoleSnapshot();

    if (!IS_DEMO_MODE && autoRefreshMs > 0) {
      pollingRef.current = window.setInterval(() => {
        void loadOpsConsoleSnapshot();
      }, autoRefreshMs);
    }

    return () => {
      mountedRef.current = false;
      if (pollingRef.current) {
        window.clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [autoRefreshMs, loadOpsConsoleSnapshot]);

  const refetch = useCallback(async () => {
    await loadOpsConsoleSnapshot();
  }, [loadOpsConsoleSnapshot]);

  const removeTask = useCallback((taskId: string) => {
    setState((previous) => {
      if (previous.status !== 'ready' || !previous.data) {
        return previous;
      }

      const remaining = previous.data.tasks
        .filter((task) => task.taskId !== taskId)
        .map((task, index) => ({ ...task, queueIndex: index + 1 }));
      const { dueToday, overdue } = summarizeTaskDeadlines(remaining, new Date());

      return {
        ...previous,
        data: {
          ...previous.data,
          tasks: remaining,
          nextBestTask: remaining[0] ?? null,
          dueToday,
          overdue,
        },
      } satisfies MetricsState<OpsConsoleSnapshot>;
    });
  }, []);

  return useMemo(
    () => ({
      ...state,
      state,
      refetch,
      lastUpdated,
      removeTask,
    }),
    [state, refetch, lastUpdated, removeTask],
  );
}

async function fetchCallQueue(limit: number): Promise<RawCallQueueRow[]> {
  const endOfToday = new Date();
  endOfToday.setHours(23, 59, 59, 999);
  const result = await demoSafeSelect<RawCallQueueRow[] | null>(
    supabaseClient
      .from(CALL_QUEUE_VIEW)
      .select(
        'task_id, plaintiff_id, plaintiff_name, tier, phone, last_contact_at, days_since_contact, due_at, notes, status, task_status',
      )
      .lte('due_at', endOfToday.toISOString())
      .order('due_at', { ascending: true, nullsFirst: false })
      .limit(limit),
  );
  return unwrapArrayResult(result);
}

async function fetchPipelineMetrics(): Promise<RawOverviewRow[]> {
  const result = await demoSafeSelect<RawOverviewRow[] | null>(
    supabaseClient
      .from(ENFORCEMENT_OVERVIEW_VIEW)
      .select('enforcement_stage, case_count, total_judgment_amount')
      .order('enforcement_stage', { ascending: true, nullsFirst: false }),
  );
  return unwrapArrayResult(result);
}

function mapCallTask(row: RawCallQueueRow, now: Date): OpsCallTask | null {
  const taskId = safeString(row.task_id);
  const plaintiffId = safeString(row.plaintiff_id);
  if (!taskId || !plaintiffId) {
    return null;
  }

  const normalized = {
    taskId,
    plaintiffId,
    plaintiffName: safeString(row.plaintiff_name, '—'),
    tier: normalizeTier(row.tier),
    phone: normalizePhone(row.phone),
    lastContactAt: row.last_contact_at ?? null,
    daysSinceContact: parseNullableNumber(row.days_since_contact),
    dueAt: row.due_at ?? null,
    notes: row.notes ?? null,
    status: normalizeStatus(row.task_status ?? row.status),
  } satisfies Omit<OpsCallTask, 'priorityScore' | 'queueIndex'>;

  return {
    ...normalized,
    priorityScore: computePriorityScore(normalized, now),
    queueIndex: 0,
  } satisfies OpsCallTask;
}

function computePriorityScore(task: Omit<OpsCallTask, 'priorityScore' | 'queueIndex'>, now: Date): number {
  const tierScore = (() => {
    switch ((task.tier ?? '').toUpperCase()) {
      case 'A':
        return 120;
      case 'B':
        return 80;
      case 'C':
        return 50;
      default:
        return 20;
    }
  })();

  const recencyScore = Math.min(Math.max(task.daysSinceContact ?? 0, 0), 90) * 1.5;
  const dueScore = (() => {
    if (!task.dueAt) {
      return 0;
    }
    const due = Date.parse(task.dueAt);
    if (Number.isNaN(due)) {
      return 0;
    }
    const hoursUntilDue = (due - now.getTime()) / (1000 * 60 * 60);
    if (hoursUntilDue <= 0) {
      return 60;
    }
    if (hoursUntilDue < 6) {
      return 40;
    }
    if (hoursUntilDue < 24) {
      return 25;
    }
    return 10;
  })();

  const availabilityScore = task.phone ? 15 : -25;
  return tierScore + recencyScore + dueScore + availabilityScore;
}

function aggregatePipelineMetrics(rows: RawOverviewRow[]): OpsPipelineMetric[] {
  const stageMap = new Map<string, OpsPipelineMetric>();
  for (const row of rows) {
    const stage = normalizeStageCode(row.enforcement_stage);
    if (!stage) {
      continue;
    }
    const bucket = stageMap.get(stage) ?? {
      stage,
      label: describeStage(stage),
      caseCount: 0,
      totalJudgmentAmount: 0,
    };
    bucket.caseCount += parseNumber(row.case_count);
    bucket.totalJudgmentAmount += parseNumber(row.total_judgment_amount);
    stageMap.set(stage, bucket);
  }

  return Array.from(stageMap.values()).sort((a, b) => stageOrder(a.stage) - stageOrder(b.stage));
}

function summarizeTaskDeadlines(tasks: OpsCallTask[], now: Date): { dueToday: number; overdue: number } {
  let dueToday = 0;
  let overdue = 0;
  for (const task of tasks) {
    if (isOverdue(task.dueAt, now)) {
      overdue += 1;
    } else if (isDueToday(task.dueAt, now)) {
      dueToday += 1;
    }
  }
  return { dueToday, overdue };
}

function normalizeStageCode(stage: string | null): string | null {
  if (!stage) {
    return null;
  }
  const normalized = stage.trim().toLowerCase();
  return normalized.length === 0 ? null : normalized;
}

function describeStage(stage: string): string {
  switch (stage) {
    case 'pre_enforcement':
      return 'Outreach';
    case 'paperwork_filed':
      return 'Planning filed';
    case 'levy_issued':
      return 'Levy active';
    case 'payment_plan':
      return 'Payment plan';
    case 'waiting_payment':
      return 'Waiting payment';
    case 'collected':
      return 'Collected';
    case 'closed_no_recovery':
      return 'Closed (no recovery)';
    default:
      return stage.replace(/[_-]+/g, ' ');
  }
}

function stageOrder(stage: string): number {
  const order: Record<string, number> = {
    pre_enforcement: 1,
    paperwork_filed: 2,
    levy_issued: 3,
    payment_plan: 4,
    waiting_payment: 5,
    collected: 6,
    closed_no_recovery: 7,
  };
  return order[stage] ?? 99;
}

function isDueToday(dueAt: string | null, now: Date): boolean {
  if (!dueAt) {
    return false;
  }
  const due = new Date(dueAt);
  if (Number.isNaN(due.getTime())) {
    return false;
  }
  return due.toDateString() === now.toDateString();
}

function isOverdue(dueAt: string | null, now: Date): boolean {
  if (!dueAt) {
    return false;
  }
  const due = Date.parse(dueAt);
  if (Number.isNaN(due)) {
    return false;
  }
  return due < now.getTime();
}

function safeString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') {
    return value;
  }
  if (value == null) {
    return fallback;
  }
  return String(value);
}

function normalizeTier(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed.toUpperCase() : null;
}

function normalizePhone(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function parseNullableNumber(value: unknown): number | null {
  if (value == null) {
    return null;
  }
  const parsed = typeof value === 'number' ? value : Number(value);
  if (Number.isNaN(parsed)) {
    return null;
  }
  return parsed;
}

function parseNumber(value: number | string | null): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    return Number.isNaN(parsed) ? 0 : parsed;
  }
  return 0;
}

function normalizeStatus(value: string | null): string {
  if (!value) {
    return 'open';
  }
  const trimmed = value.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : 'open';
}

function unwrapArrayResult<TRow>(result: DemoSafeResult<TRow[] | null>): TRow[] {
  if (result.kind === 'demo_locked') {
    throw new Error('Demo locked');
  }
  if (result.kind === 'error') {
    throw result.error;
  }
  return (result.data ?? []) as TRow[];
}
