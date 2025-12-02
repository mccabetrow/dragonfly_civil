import { useCallback, useEffect, useState } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
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

export interface IntakeMetricRow {
  activityDate: string;
  sourceSystem: string;
  importCount: number;
  plaintiffCount: number;
  judgmentCount: number;
  totalJudgmentAmount: number;
}

export interface PipelineMetricRow {
  enforcementStage: string;
  collectabilityTier: string;
  judgmentCount: number;
  totalJudgmentAmount: number;
  averageJudgmentAmount: number;
  latestStageUpdate: string | null;
}

export interface EnforcementMetricRow {
  bucketWeek: string;
  casesOpened: number;
  openedJudgmentAmount: number;
  casesClosed: number;
  closedJudgmentAmount: number;
  activeCaseCount: number;
  activeJudgmentAmount: number;
}

export function useIntakeMetrics(limit = 90): MetricsHookResult<IntakeMetricRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<IntakeMetricRow[]>>(() =>
    buildInitialMetricsState<IntakeMetricRow[]>(),
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<IntakeMetricRow[]>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));
    try {
      let query = supabaseClient
        .from('v_metrics_intake_daily')
        .select('activity_date, source_system, import_count, plaintiff_count, judgment_count, total_judgment_amount')
        .order('activity_date', { ascending: false })
        .order('source_system', { ascending: true });

      if (limit > 0) {
        query = query.limit(limit);
      }

      const result = await demoSafeSelect<Array<Record<string, unknown>> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as Array<Record<string, unknown>>;
      const mapped = rows.map((row) => ({
        activityDate: normalizeDate(row.activity_date),
        sourceSystem: normalizeString(row.source_system, 'unknown'),
        importCount: normalizeNumber(row.import_count),
        plaintiffCount: normalizeNumber(row.plaintiff_count),
        judgmentCount: normalizeNumber(row.judgment_count),
        totalJudgmentAmount: normalizeNumber(row.total_judgment_amount),
      }));

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const friendly = deriveViewError('v_metrics_intake_daily', err, 'Unable to load intake metrics.');
      const normalizedError = err instanceof Error ? err : new Error(friendly);
      setSnapshot(buildErrorMetricsState<IntakeMetricRow[]>(normalizedError, { message: friendly }));
    }
  }, [limit]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return { ...snapshot, state: snapshot, refetch: fetchData };
}

export function usePipelineMetrics(): MetricsHookResult<PipelineMetricRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<PipelineMetricRow[]>>(() =>
    buildInitialMetricsState<PipelineMetricRow[]>(),
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<PipelineMetricRow[]>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));
    try {
      const query = supabaseClient
        .from('v_metrics_pipeline')
        .select('enforcement_stage, collectability_tier, judgment_count, total_judgment_amount, average_judgment_amount, latest_stage_update')
        .order('enforcement_stage', { ascending: true })
        .order('collectability_tier', { ascending: true });

      const result = await demoSafeSelect<Array<Record<string, unknown>> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as Array<Record<string, unknown>>;
      const mapped = rows.map((row) => ({
        enforcementStage: normalizeString(row.enforcement_stage, 'unknown'),
        collectabilityTier: normalizeString(row.collectability_tier, 'unscored'),
        judgmentCount: normalizeNumber(row.judgment_count),
        totalJudgmentAmount: normalizeNumber(row.total_judgment_amount),
        averageJudgmentAmount: normalizeNumber(row.average_judgment_amount),
        latestStageUpdate: normalizeTimestamp(row.latest_stage_update),
      }));

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const friendly = deriveViewError('v_metrics_pipeline', err, 'Unable to load pipeline metrics.');
      const normalizedError = err instanceof Error ? err : new Error(friendly);
      setSnapshot(buildErrorMetricsState<PipelineMetricRow[]>(normalizedError, { message: friendly }));
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return { ...snapshot, state: snapshot, refetch: fetchData };
}

export function useEnforcementMetrics(limit = 12): MetricsHookResult<EnforcementMetricRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<EnforcementMetricRow[]>>(() =>
    buildInitialMetricsState<EnforcementMetricRow[]>(),
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<EnforcementMetricRow[]>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));
    try {
      let query = supabaseClient
        .from('v_metrics_enforcement')
        .select('bucket_week, cases_opened, opened_judgment_amount, cases_closed, closed_judgment_amount, active_case_count, active_judgment_amount')
        .order('bucket_week', { ascending: false });

      if (limit > 0) {
        query = query.limit(limit);
      }

      const result = await demoSafeSelect<Array<Record<string, unknown>> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as Array<Record<string, unknown>>;
      const mapped = rows.map((row) => ({
        bucketWeek: normalizeDate(row.bucket_week),
        casesOpened: normalizeNumber(row.cases_opened),
        openedJudgmentAmount: normalizeNumber(row.opened_judgment_amount),
        casesClosed: normalizeNumber(row.cases_closed),
        closedJudgmentAmount: normalizeNumber(row.closed_judgment_amount),
        activeCaseCount: normalizeNumber(row.active_case_count),
        activeJudgmentAmount: normalizeNumber(row.active_judgment_amount),
      }));

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const friendly = deriveViewError('v_metrics_enforcement', err, 'Unable to load enforcement metrics.');
      const normalizedError = err instanceof Error ? err : new Error(friendly);
      setSnapshot(buildErrorMetricsState<EnforcementMetricRow[]>(normalizedError, { message: friendly }));
    }
  }, [limit]);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  return { ...snapshot, state: snapshot, refetch: fetchData };
}

function normalizeNumber(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  if (typeof value === 'string' && value.trim().length > 0) {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function normalizeString(value: unknown, fallback: string): string {
  if (typeof value !== 'string') {
    return fallback;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : fallback;
}

function normalizeDate(value: unknown): string {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value.slice(0, 10);
  }
  return '';
}

function normalizeTimestamp(value: unknown): string | null {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value;
  }
  return null;
}

function deriveViewError(viewName: string, err: unknown, fallback: string): string {
  if (!err) {
    return fallback;
  }
  if (isSchemaCacheMiss(err)) {
    return `${viewName} is unavailable. Apply the latest migrations and reload the PostgREST schema cache.`;
  }
  return fallback;
}

function isSchemaCacheMiss(err: unknown): err is PostgrestError | (Partial<PostgrestError> & { status?: number }) {
  if (!err || typeof err !== 'object') {
    return false;
  }
  const maybe = err as Partial<PostgrestError> & { status?: number };
  if (maybe.code === '42P01' || maybe.code === 'PGRST116') {
    return true;
  }
  if (maybe.status === 404) {
    return true;
  }
  const message = (maybe.message ?? '').toLowerCase();
  const details = (maybe.details ?? '').toLowerCase();
  const hint = (maybe.hint ?? '').toLowerCase();
  return message.includes('schema cache') || details.includes('schema cache') || hint.includes('schema cache');
}
