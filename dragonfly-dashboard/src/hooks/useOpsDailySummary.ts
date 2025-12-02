import { useCallback, useEffect, useMemo, useState } from 'react';
import { demoSafeSelect, IS_DEMO_MODE, supabaseClient } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';

interface RawDailySummaryRow {
  summary_date: string | null;
  new_plaintiffs: number | string | null;
  plaintiffs_contacted: number | string | null;
  calls_made: number | string | null;
  agreements_sent: number | string | null;
  agreements_signed: number | string | null;
}

export interface OpsDailySummary {
  summaryDate: string;
  newPlaintiffs: number;
  plaintiffsContacted: number;
  callsMade: number;
  agreementsSent: number;
  agreementsSigned: number;
}

const VIEW_NAME = 'v_ops_daily_summary';
const DEMO_LOCK_MESSAGE = 'Daily summary is hidden in demo mode. Connect prod Supabase to view live metrics.';

export function useOpsDailySummary(): MetricsHookResult<OpsDailySummary | null> {
  const [snapshot, setSnapshot] = useState<MetricsState<OpsDailySummary | null>>(() =>
    buildInitialMetricsState<OpsDailySummary | null>(),
  );

  const fetchSummary = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<OpsDailySummary | null>(DEMO_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));
    try {
      const result = await demoSafeSelect<RawDailySummaryRow[] | null>(
        supabaseClient.from(VIEW_NAME).select('summary_date, new_plaintiffs, plaintiffs_contacted, calls_made, agreements_sent, agreements_signed').limit(1),
      );

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<OpsDailySummary | null>(DEMO_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        const normalized = result.error instanceof Error ? result.error : new Error('Failed to load daily summary.');
        setSnapshot(buildErrorMetricsState<OpsDailySummary | null>(normalized, { message: normalized.message }));
        return;
      }

      const [row] = (result.data ?? []) as RawDailySummaryRow[];
      const mapped = row ? mapRow(row) : null;
      setSnapshot(buildReadyMetricsState(mapped));
    } catch (err) {
      const normalized = err instanceof Error ? err : new Error('Failed to load daily summary.');
      setSnapshot(buildErrorMetricsState<OpsDailySummary | null>(normalized, { message: normalized.message }));
    }
  }, []);

  useEffect(() => {
    void fetchSummary();
  }, [fetchSummary]);

  const refetch = useCallback(async () => {
    await fetchSummary();
  }, [fetchSummary]);

  return useMemo(
    () => ({
      ...snapshot,
      state: snapshot,
      refetch,
    }),
    [snapshot, refetch],
  );
}

function mapRow(row: RawDailySummaryRow): OpsDailySummary {
  return {
    summaryDate: row.summary_date ?? new Date().toISOString(),
    newPlaintiffs: parseNumber(row.new_plaintiffs),
    plaintiffsContacted: parseNumber(row.plaintiffs_contacted),
    callsMade: parseNumber(row.calls_made),
    agreementsSent: parseNumber(row.agreements_sent),
    agreementsSigned: parseNumber(row.agreements_signed),
  } satisfies OpsDailySummary;
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
