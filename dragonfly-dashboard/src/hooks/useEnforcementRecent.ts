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

export interface EnforcementRecentRow {
  judgmentId: string;
  caseNumber: string;
  plaintiffName: string;
  plaintiffId: string | null;
  judgmentAmount: number;
  enforcementStage: string;
  updatedAt: string | null;
  collectabilityTier: string | null;
}

const ENFORCEMENT_RECENT_VIEW = 'v_enforcement_recent' as const; // Keep in sync with state/schema_freeze.json

export function useEnforcementRecent(limit: number = 25): MetricsHookResult<EnforcementRecentRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<EnforcementRecentRow[]>>(() =>
    buildInitialMetricsState<EnforcementRecentRow[]>(),
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<EnforcementRecentRow[]>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      let query = supabaseClient
        .from(ENFORCEMENT_RECENT_VIEW)
        .select(
          'judgment_id, case_number, plaintiff_name, plaintiff_id, judgment_amount, enforcement_stage, enforcement_stage_updated_at, collectability_tier',
        )
        .order('enforcement_stage_updated_at', { ascending: false, nullsFirst: false });

      if (Number.isFinite(limit) && limit > 0) {
        query = query.limit(limit);
      }

      const result = await demoSafeSelect<Array<Record<string, unknown>> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<EnforcementRecentRow[]>());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as Array<Record<string, unknown>>;
      const normalized = rows.map((row) => ({
        judgmentId: coerceString(row.judgment_id, ''),
        caseNumber: coerceString(row.case_number, '—'),
        plaintiffName: coerceString(row.plaintiff_name, '—'),
        plaintiffId: coerceString(row.plaintiff_id, '') || null,
        judgmentAmount: coerceNumber(row.judgment_amount),
        enforcementStage: normalizeStage(row.enforcement_stage),
        updatedAt: normalizeIso(row.enforcement_stage_updated_at),
        collectabilityTier: normalizeTier(row.collectability_tier),
      }));

      setSnapshot(buildReadyMetricsState(normalized));
    } catch (err) {
      const error = err instanceof Error ? err : (typeof err === 'string' ? err : new Error('Unable to load enforcement activity.'));
      const friendly = deriveRecentErrorMessage(error, 'Unable to load enforcement activity.');
      setSnapshot(buildErrorMetricsState<EnforcementRecentRow[]>(error, { message: friendly }));
    }
  }, [limit]);

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

function coerceString(value: unknown, fallback = ''): string {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : fallback;
  }
  return fallback;
}

function normalizeStage(stage: unknown): string {
  if (typeof stage !== 'string') {
    return 'unknown';
  }
  const trimmed = stage.trim().toLowerCase();
  return trimmed.length > 0 ? trimmed : 'unknown';
}

function normalizeIso(value: unknown): string | null {
  if (typeof value === 'string' && value.trim().length > 0) {
    return value;
  }
  return null;
}

function normalizeTier(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    return trimmed.length > 0 ? trimmed : null;
  }
  return null;
}

function deriveRecentErrorMessage(err: unknown, fallback: string): string {
  if (!err) {
    return fallback;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Enforcement recent view is unavailable. Apply migrations and refresh the PostgREST schema cache.';
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
