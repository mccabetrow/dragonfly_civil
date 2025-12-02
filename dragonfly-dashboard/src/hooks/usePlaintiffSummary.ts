import { useCallback, useEffect, useState } from 'react';
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

export interface PlaintiffSummaryRow {
  plaintiffId: number;
  plaintiffName: string;
  judgmentCount: number;
  totalJudgmentAmount: number;
  latestStatus: string | null;
  latestStatusAt: string | null;
  primaryEmail: string | null;
  primaryPhone: string | null;
}

interface RawPlaintiffSummaryRow {
  plaintiff_id: number;
  plaintiff_name: string | null;
  judgment_count: number | null;
  total_judgment_amount: number | null;
  latest_status: string | null;
  latest_status_at: string | null;
  primary_email: string | null;
  primary_phone: string | null;
}

export type UsePlaintiffSummaryResult = MetricsHookResult<PlaintiffSummaryRow[]>;

function normalizeName(value: string | null): string {
  if (!value) {
    return '—';
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : '—';
}

function normalizeStatus(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const normalized = value.trim();
  if (!normalized) {
    return null;
  }
  return normalized;
}

function normalizeContact(value: string | null): string | null {
  if (!value) {
    return null;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 ? trimmed : null;
}

function coerceNumber(value: number | null): number {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  return 0;
}

export function usePlaintiffSummary(limit: number = 25): UsePlaintiffSummaryResult {
  const [snapshot, setSnapshot] = useState<MetricsState<PlaintiffSummaryRow[]>>(() =>
    buildInitialMetricsState<PlaintiffSummaryRow[]>(),
  );

  const fetchPlaintiffs = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(
        buildDemoLockedState<PlaintiffSummaryRow[]>(
          'Plaintiff summary is hidden in the demo console. Connect to production Supabase to view firm-level intake.',
        ),
      );
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const query = supabaseClient
        .from('v_plaintiff_summary')
        .select(
          'plaintiff_id, plaintiff_name, judgment_count, total_judgment_amount, latest_status, latest_status_at, primary_email, primary_phone',
        )
        .order('total_judgment_amount', { ascending: false, nullsFirst: false })
        .limit(limit);

      const result = await demoSafeSelect<RawPlaintiffSummaryRow[] | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(
          buildDemoLockedState<PlaintiffSummaryRow[]>(
            'Plaintiff summary is hidden in the demo console. Connect to production Supabase to view firm-level intake.',
          ),
        );
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as RawPlaintiffSummaryRow[];
      const mapped = rows.map((row) => ({
        plaintiffId: row.plaintiff_id,
        plaintiffName: normalizeName(row.plaintiff_name),
        judgmentCount: coerceNumber(row.judgment_count),
        totalJudgmentAmount: coerceNumber(row.total_judgment_amount),
        latestStatus: normalizeStatus(row.latest_status),
        latestStatusAt: row.latest_status_at,
        primaryEmail: normalizeContact(row.primary_email),
        primaryPhone: normalizeContact(row.primary_phone),
      }));

      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const normalized = err instanceof Error ? err : new Error('Failed to load plaintiffs');
      setSnapshot(
        buildErrorMetricsState<PlaintiffSummaryRow[]>(normalized, {
          message: normalized.message ?? 'Unable to load plaintiff summary.',
        }),
      );
    }
  }, [limit]);

  useEffect(() => {
    void fetchPlaintiffs();
  }, [fetchPlaintiffs]);

  const refetch = useCallback(() => fetchPlaintiffs(), [fetchPlaintiffs]);

  return {
    ...snapshot,
    state: snapshot,
    refetch,
  } satisfies MetricsHookResult<PlaintiffSummaryRow[]>;
}
