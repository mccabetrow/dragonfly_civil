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

export interface EnforcementOverviewRow {
  enforcementStage: string;
  collectabilityTier: string | null;
  caseCount: number;
  totalJudgmentAmount: number;
}

export function useEnforcementOverview(): MetricsHookResult<EnforcementOverviewRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<EnforcementOverviewRow[]>>(() =>
    buildInitialMetricsState<EnforcementOverviewRow[]>(),
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<EnforcementOverviewRow[]>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const query = supabaseClient
        .from('v_enforcement_overview')
        .select('enforcement_stage, collectability_tier, case_count, total_judgment_amount')
        .order('enforcement_stage', { ascending: true, nullsFirst: false })
        .order('collectability_tier', { ascending: true, nullsFirst: true });

      const result = await demoSafeSelect<Array<Record<string, unknown>> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<EnforcementOverviewRow[]>());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as Array<Record<string, unknown>>;
      const normalized = rows.map((row) => ({
        enforcementStage: normalizeStage(row.enforcement_stage),
        collectabilityTier: normalizeTier(row.collectability_tier),
        caseCount: coerceNumber(row.case_count),
        totalJudgmentAmount: coerceNumber(row.total_judgment_amount),
      }));

      setSnapshot(buildReadyMetricsState(normalized));
    } catch (err) {
      const error = err instanceof Error ? err : (typeof err === 'string' ? err : new Error('Unable to load enforcement overview.'));
      const friendly = deriveOverviewErrorMessage(error, 'Unable to load enforcement overview.');
      setSnapshot(buildErrorMetricsState<EnforcementOverviewRow[]>(error, { message: friendly }));
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  const refetch = useCallback(() => fetchData(), [fetchData]);

  return { ...snapshot, state: snapshot, refetch };
}

function coerceNumber(value: unknown): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function normalizeStage(stage: unknown): string {
  if (typeof stage !== 'string') {
    return 'unknown';
  }
  const trimmed = stage.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : 'unknown';
}

function normalizeTier(tier: unknown): string | null {
  if (typeof tier !== 'string') {
    return null;
  }
  const trimmed = tier.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function deriveOverviewErrorMessage(err: unknown, fallback: string): string {
  if (!err) {
    return fallback;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Enforcement overview view is unavailable. Apply migrations and refresh the PostgREST schema cache.';
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
