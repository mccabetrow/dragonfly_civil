import { useCallback, useEffect, useMemo, useState } from 'react';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';

export interface PipelineMetrics {
  simplicityPlaintiffCount: number;
  lifecycleCounts: Record<PipelineLifecycleStatus, number>;
  tierTotals: Record<CollectabilityTier, number>;
  jbi900Summary: Jbi900SummaryMetrics;
}

export interface Jbi900SummaryMetrics {
  totalPlaintiffCount: number;
  totalJudgmentAmount: number;
  entries: Jbi900SummaryEntry[];
}

export interface Jbi900SummaryEntry {
  status: string;
  plaintiffCount: number;
  totalJudgmentAmount: number;
  statusPriority: number;
}

export type PipelineLifecycleStatus = 'new' | 'contacted' | 'qualified' | 'signed';
export type CollectabilityTier = 'A' | 'B' | 'C';

interface RawJbi900SummaryRow {
  status: string | null;
  plaintiff_count: number | null;
  total_judgment_amount: number | null;
  status_priority: number | null;
}

interface PipelineSnapshotRow {
  simplicity_plaintiff_count: number | null;
  lifecycle_counts: Record<string, unknown> | null;
  tier_totals: Record<string, unknown> | null;
  jbi_summary: RawJbi900SummaryRow[] | null;
}

const LIFECYCLE_STATUSES: PipelineLifecycleStatus[] = ['new', 'contacted', 'qualified', 'signed'];
const COLLECTABILITY_TIERS: CollectabilityTier[] = ['A', 'B', 'C'];
export const CALL_QUEUE_LOCK_MESSAGE = 'Call tasks stay locked in this demo until production credentials are configured.';
export const PRIORITY_LOCK_MESSAGE = 'Priority rankings stay hidden in this demo to avoid exposing plaintiff data.';

export function usePipelineMetrics(): MetricsHookResult<PipelineMetrics> {
  const [snapshot, setSnapshot] = useState<MetricsState<PipelineMetrics>>(() =>
    buildInitialMetricsState<PipelineMetrics>(),
  );

  const fetchMetrics = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<PipelineMetrics>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const result = await demoSafeSelect<PipelineSnapshotRow[] | null>(
        supabaseClient
          .from('v_pipeline_snapshot')
          .select('simplicity_plaintiff_count, lifecycle_counts, tier_totals, jbi_summary')
          .limit(1),
      );

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const payload = ((result.data ?? []) as PipelineSnapshotRow[])[0];
      const lifecycleCounts = hydrateLifecycleCounts(payload?.lifecycle_counts ?? null);
      const tierTotals = hydrateTierTotals(payload?.tier_totals ?? null);
      const simplicityPlaintiffCount = parseNumeric(payload?.simplicity_plaintiff_count);
      const jbiSummary = buildJbi900Summary(normalizeJbiSummary(payload?.jbi_summary));

      setSnapshot(
        buildReadyMetricsState<PipelineMetrics>({
          simplicityPlaintiffCount,
          lifecycleCounts,
          tierTotals,
          jbi900Summary: jbiSummary,
        }),
      );
    } catch (err) {
      const friendly = derivePipelineErrorMessage(err);
      const normalizedError = err instanceof Error ? err : new Error(friendly);
      setSnapshot(buildErrorMetricsState<PipelineMetrics>(normalizedError, { message: friendly }));
    }
  }, []);

  useEffect(() => {
    void fetchMetrics();
  }, [fetchMetrics]);

  const refetch = useCallback(() => fetchMetrics(), [fetchMetrics]);

  return { ...snapshot, state: snapshot, refetch };
}

function buildInitialLifecycleCounts(): Record<PipelineLifecycleStatus, number> {
  return {
    new: 0,
    contacted: 0,
    qualified: 0,
    signed: 0,
  } satisfies Record<PipelineLifecycleStatus, number>;
}

function hydrateLifecycleCounts(payload: Record<string, unknown> | null): Record<PipelineLifecycleStatus, number> {
  const counts = buildInitialLifecycleCounts();
  if (!payload) {
    return counts;
  }
  for (const status of LIFECYCLE_STATUSES) {
    counts[status] = parseNumeric(payload[status]);
  }
  return counts;
}

function buildInitialTierTotals(): Record<CollectabilityTier, number> {
  return {
    A: 0,
    B: 0,
    C: 0,
  } satisfies Record<CollectabilityTier, number>;
}

function hydrateTierTotals(payload: Record<string, unknown> | null): Record<CollectabilityTier, number> {
  const totals = buildInitialTierTotals();
  if (!payload) {
    return totals;
  }
  for (const tier of COLLECTABILITY_TIERS) {
    totals[tier] = parseNumeric(payload[tier]);
  }
  return totals;
}

function buildInitialJbi900Summary(): Jbi900SummaryMetrics {
  return {
    totalPlaintiffCount: 0,
    totalJudgmentAmount: 0,
    entries: [],
  } satisfies Jbi900SummaryMetrics;
}

function buildJbi900Summary(rows: RawJbi900SummaryRow[] | null): Jbi900SummaryMetrics {
  if (!rows || rows.length === 0) {
    return buildInitialJbi900Summary();
  }

  const entries: Jbi900SummaryEntry[] = rows
    .map((row) => ({
      status: normalizeText(row.status) ?? 'unspecified',
      plaintiffCount: typeof row.plaintiff_count === 'number' ? row.plaintiff_count : 0,
      totalJudgmentAmount: typeof row.total_judgment_amount === 'number' ? row.total_judgment_amount : 0,
      statusPriority: typeof row.status_priority === 'number' ? row.status_priority : 99,
    }))
    .sort((a, b) => {
      if (a.statusPriority !== b.statusPriority) {
        return a.statusPriority - b.statusPriority;
      }
      return a.status.localeCompare(b.status);
    });

  const totalPlaintiffCount = entries.reduce((sum, entry) => sum + entry.plaintiffCount, 0);
  const totalJudgmentAmount = entries.reduce((sum, entry) => sum + entry.totalJudgmentAmount, 0);

  return {
    totalPlaintiffCount,
    totalJudgmentAmount,
    entries,
  } satisfies Jbi900SummaryMetrics;
}

export interface PipelineTaskRow {
  taskId: string;
  plaintiffId: string;
  plaintiffName: string;
  email: string;
  phone: string;
  status: string;
  dueAt: string | null;
  judgmentTotal: number;
  topTier: string | null;
}

export type UseOpenCallTasksResult = MetricsHookResult<PipelineTaskRow[]>;

interface RawOpenTaskRow {
  task_id: string | null;
  plaintiff_id: string | null;
  plaintiff_name: string | null;
  email: string | null;
  phone: string | null;
  status: string | null;
  due_at: string | null;
  judgment_total: number | null;
  top_collectability_tier: string | null;
  kind: string | null;
  assignee: string | null;
}

export type UsePriorityPipelineResult = MetricsHookResult<PriorityPipelineRow[]>;

export interface PriorityPipelineRow {
  plaintiffName: string;
  judgmentId: string;
  collectabilityTier: string | null;
  priorityLevel: string | null;
  judgmentAmount: number;
  stage: string | null;
  plaintiffStatus: string | null;
  tierRank: number;
}

interface RawPriorityPipelineRow {
  plaintiff_name: string | null;
  judgment_id: string | null;
  collectability_tier: string | null;
  priority_level: string | null;
  judgment_amount: number | null;
  stage: string | null;
  plaintiff_status: string | null;
  tier_rank: number | null;
}

export function useOpenCallTasks(options?: { limit?: number; assignee?: string }): UseOpenCallTasksResult {
  const limit = options?.limit ?? 15;
  const assignee = options?.assignee ?? 'mom_full_name_or_user_id';

  const [snapshot, setSnapshot] = useState<MetricsState<PipelineTaskRow[]>>(() =>
    buildInitialMetricsState<PipelineTaskRow[]>(),
  );

  const fetchTasks = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<PipelineTaskRow[]>(CALL_QUEUE_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      let query = supabaseClient
        .from('v_plaintiff_open_tasks')
        .select('task_id, plaintiff_id, plaintiff_name, email, phone, status, due_at, judgment_total, top_collectability_tier, kind, assignee')
        .eq('kind', 'call');

      if (assignee) {
        query = query.eq('assignee', assignee);
      }

      if (Number.isFinite(limit) && limit > 0) {
        query = query.limit(limit);
      }

      const result = await demoSafeSelect<RawOpenTaskRow[] | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<PipelineTaskRow[]>(CALL_QUEUE_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const mapped = ((result.data ?? []) as RawOpenTaskRow[])
        .map((row) => normalizeOpenTaskRow(row))
        .filter((row): row is PipelineTaskRow => row !== null)
        .sort((a, b) => getDueTimestamp(a.dueAt) - getDueTimestamp(b.dueAt));

      setSnapshot(buildReadyMetricsState<PipelineTaskRow[]>(mapped));
    } catch (err) {
      const friendly = derivePipelineErrorMessage(err);
      const normalizedError = err instanceof Error ? err : new Error(friendly);
      setSnapshot(buildErrorMetricsState<PipelineTaskRow[]>(normalizedError, { message: friendly }));
    }
  }, [assignee, limit]);

  useEffect(() => {
    void fetchTasks();
  }, [fetchTasks]);

  const refetch = useCallback(() => fetchTasks(), [fetchTasks]);

  return { ...snapshot, state: snapshot, refetch } satisfies UseOpenCallTasksResult;
}

function normalizeOpenTaskRow(row: RawOpenTaskRow): PipelineTaskRow | null {
  if (!row.task_id || !row.plaintiff_id) {
    return null;
  }
  return {
    taskId: row.task_id,
    plaintiffId: row.plaintiff_id,
    plaintiffName: normalizeText(row.plaintiff_name) ?? '—',
    email: normalizeText(row.email) ?? '—',
    phone: normalizeText(row.phone) ?? '—',
    status: normalizeText(row.status) ?? 'open',
    dueAt: row.due_at,
    judgmentTotal: typeof row.judgment_total === 'number' ? row.judgment_total : 0,
    topTier: row.top_collectability_tier,
  } satisfies PipelineTaskRow;
}

function normalizeText(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function getDueTimestamp(value: string | null): number {
  if (!value) {
    return Number.POSITIVE_INFINITY;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
}

export function usePriorityPipeline(limit: number = 20): UsePriorityPipelineResult {
  const [snapshot, setSnapshot] = useState<MetricsState<PriorityPipelineRow[]>>(() =>
    buildInitialMetricsState<PriorityPipelineRow[]>(),
  );

  const fetchPipeline = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<PriorityPipelineRow[]>(PRIORITY_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      let query = supabaseClient
        .from('v_priority_pipeline')
        .select(
          'plaintiff_name, judgment_id, collectability_tier, priority_level, judgment_amount, stage, plaintiff_status, tier_rank',
        )
        .order('collectability_tier', { ascending: true })
        .order('priority_level', { ascending: true })
        .order('judgment_amount', { ascending: false });

      if (Number.isFinite(limit) && limit > 0) {
        query = query.limit(limit);
      }

      const result = await demoSafeSelect<RawPriorityPipelineRow[] | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<PriorityPipelineRow[]>(PRIORITY_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const mapped = ((result.data ?? []) as RawPriorityPipelineRow[])
        .map((row) => normalizePriorityRow(row))
        .filter((row): row is PriorityPipelineRow => row !== null);

      setSnapshot(buildReadyMetricsState<PriorityPipelineRow[]>(mapped));
    } catch (err) {
      const friendly = derivePipelineErrorMessage(err);
      const normalizedError = err instanceof Error ? err : new Error(friendly);
      setSnapshot(buildErrorMetricsState<PriorityPipelineRow[]>(normalizedError, { message: friendly }));
    }
  }, [limit]);

  useEffect(() => {
    void fetchPipeline();
  }, [fetchPipeline]);

  const refetch = useCallback(() => fetchPipeline(), [fetchPipeline]);

  return { ...snapshot, state: snapshot, refetch } satisfies UsePriorityPipelineResult;
}

function normalizePriorityRow(row: RawPriorityPipelineRow): PriorityPipelineRow | null {
  if (!row.judgment_id) {
    return null;
  }
  return {
    judgmentId: row.judgment_id,
    plaintiffName: normalizeText(row.plaintiff_name) ?? '—',
    collectabilityTier: row.collectability_tier,
    priorityLevel: row.priority_level,
    judgmentAmount: typeof row.judgment_amount === 'number' ? row.judgment_amount : 0,
    stage: normalizeText(row.stage) ?? '—',
    plaintiffStatus: normalizeText(row.plaintiff_status) ?? '—',
    tierRank: typeof row.tier_rank === 'number' ? row.tier_rank : Number.MAX_SAFE_INTEGER,
  } satisfies PriorityPipelineRow;
}

function derivePipelineErrorMessage(err: unknown): string {
  const message = err instanceof Error ? err.message : null;
  return message && message.trim().length > 0 ? message : 'Unable to load pipeline metrics.';
}

function parseNumeric(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function normalizeJbiSummary(value: unknown): RawJbi900SummaryRow[] | null {
  if (!Array.isArray(value)) {
    return null;
  }
  return value as RawJbi900SummaryRow[];
}

export function usePipelineLoadingState(values: boolean[]): boolean {
  return useMemo(() => values.some((loading) => loading), [values]);
}
