import { useCallback, useEffect, useMemo, useState } from 'react';
import type { PostgrestError } from '@supabase/supabase-js';
import { IS_DEMO_MODE, demoSafeSelect, supabaseClient } from '../lib/supabaseClient';
import { PLAINTIFF_STATUS_DISPLAY, PLAINTIFF_STATUS_ORDER } from '../constants/plaintiffStatus';
import type { PlaintiffStatus } from '../utils/plaintiffStatusClient';
import {
  buildDemoLockedState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  buildErrorMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';

export type FunnelStatusCode = PlaintiffStatus | 'unknown';

export interface PlaintiffFunnelStat {
  status: FunnelStatusCode;
  statusLabel: string;
  plaintiffCount: number;
  totalJudgmentAmount: number;
}

interface RawFunnelRow {
  status: string | null;
  plaintiff_count: number | string | null;
  total_judgment_amount: number | string | null;
}

const UNKNOWN_STATUS_LABEL = 'Untracked';
const FUNNEL_STATS_LOCK_MESSAGE =
  'Plaintiff funnel stats stay hidden in this demo tenant. Connect production Supabase credentials to review the intake pipeline.';

export function usePlaintiffFunnelStats(): MetricsHookResult<PlaintiffFunnelStat[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<PlaintiffFunnelStat[]>>(() =>
    buildInitialMetricsState<PlaintiffFunnelStat[]>(),
  );

  const statusOrder = useMemo(() => [...PLAINTIFF_STATUS_ORDER, 'unknown'] as FunnelStatusCode[], []);

  const fetchStats = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<PlaintiffFunnelStat[]>(FUNNEL_STATS_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const query = supabaseClient
        .from('v_plaintiff_funnel_stats')
        .select('status, plaintiff_count, total_judgment_amount');

      const result = await demoSafeSelect<RawFunnelRow[] | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<PlaintiffFunnelStat[]>(FUNNEL_STATS_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        handleFunnelError(result.error, setSnapshot);
        return;
      }

      const rows = (result.data ?? []) as RawFunnelRow[];
      const mapped = rows.map(mapRowToStat);
      const normalized = mergeWithDefaults(mapped, statusOrder);
      setSnapshot(buildReadyMetricsState(normalized));
    } catch (err) {
      const { normalizedError, friendlyMessage } = buildFunnelErrorPayload(err);
      setSnapshot(buildErrorMetricsState<PlaintiffFunnelStat[]>(normalizedError, { message: friendlyMessage }));
    }
  }, [statusOrder]);

  useEffect(() => {
    void fetchStats();
  }, [fetchStats]);

  const refetch = useCallback(async () => {
    await fetchStats();
  }, [fetchStats]);

  return { ...snapshot, state: snapshot, refetch };
}

function mapRowToStat(row: RawFunnelRow): PlaintiffFunnelStat {
  const statusInfo = normalizeStatus(row.status);
  return {
    status: statusInfo.code,
    statusLabel: statusInfo.label,
    plaintiffCount: parseInteger(row.plaintiff_count),
    totalJudgmentAmount: parseNumber(row.total_judgment_amount),
  } satisfies PlaintiffFunnelStat;
}

function mergeWithDefaults(stats: PlaintiffFunnelStat[], order: FunnelStatusCode[]): PlaintiffFunnelStat[] {
  const lookup = new Map<FunnelStatusCode, PlaintiffFunnelStat>();
  for (const stat of stats) {
    lookup.set(stat.status, stat);
  }
  const result: PlaintiffFunnelStat[] = [];
  for (const status of order) {
    const existing = lookup.get(status);
    if (existing) {
      result.push(existing);
    } else if (status === 'unknown') {
      result.push({
        status: 'unknown',
        statusLabel: UNKNOWN_STATUS_LABEL,
        plaintiffCount: 0,
        totalJudgmentAmount: 0,
      });
    } else {
      const display = PLAINTIFF_STATUS_DISPLAY.find((entry) => entry.code === status);
      result.push({
        status,
        statusLabel: display?.label ?? titleCase(status.replace(/[_-]+/g, ' ')),
        plaintiffCount: 0,
        totalJudgmentAmount: 0,
      });
    }
  }
  return result;
}

function normalizeStatus(value: string | null): { code: FunnelStatusCode; label: string } {
  if (!value) {
    return { code: 'unknown', label: UNKNOWN_STATUS_LABEL };
  }
  const trimmed = value.trim().toLowerCase();
  if (!trimmed) {
    return { code: 'unknown', label: UNKNOWN_STATUS_LABEL };
  }
  const known = PLAINTIFF_STATUS_DISPLAY.find((entry) => entry.code === trimmed);
  if (known) {
    return { code: known.code, label: known.label };
  }
  if (trimmed === 'unknown') {
    return { code: 'unknown', label: UNKNOWN_STATUS_LABEL };
  }
  return {
    code: 'unknown',
    label: titleCase(trimmed.replace(/[_-]+/g, ' ')) || UNKNOWN_STATUS_LABEL,
  };
}

function parseInteger(value: number | string | null): number {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : 0;
  }
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10);
    if (!Number.isNaN(parsed)) {
      return parsed;
    }
  }
  return 0;
}

function parseNumber(value: number | string | null): number {
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

function deriveFunnelErrorMessage(err: unknown): string | null {
  if (!err) {
    return null;
  }
  if (isSchemaCacheMiss(err)) {
    return 'Funnel stats view is unavailable. Apply the latest database migrations and refresh the PostgREST schema cache.';
  }
  return null;
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

function titleCase(value: string): string {
  return value.replace(/\b([a-z])/g, (match) => match.toUpperCase());
}

function handleFunnelError(error: PostgrestError | Error, setSnapshot: (state: MetricsState<PlaintiffFunnelStat[]>) => void) {
  const { normalizedError, friendlyMessage } = buildFunnelErrorPayload(error);
  setSnapshot(buildErrorMetricsState<PlaintiffFunnelStat[]>(normalizedError, { message: friendlyMessage }));
}

function buildFunnelErrorPayload(error: unknown): { normalizedError: Error; friendlyMessage: string } {
  const defaultMessage = 'Unable to load funnel stats.';
  const friendlyMessage = deriveFunnelErrorMessage(error) ?? defaultMessage;
  const normalizedError =
    error instanceof Error
      ? error
      : new Error(typeof friendlyMessage === 'string' ? friendlyMessage : defaultMessage);
  return { normalizedError, friendlyMessage };
}
