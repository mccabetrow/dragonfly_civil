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

export const FOIL_RECENT_WINDOW_DAYS = 30;
const FOIL_ENABLED = false;

interface FoilLatestRow {
  agency: string | null;
  received_date: string | null;
  created_at: string | null;
}

export interface FoilSummary {
  total: number;
  recent: number;
  uniqueAgencies: number;
  latestAgency: string | null;
  latestDate: string | null;
}

export const FOIL_LOCK_MESSAGE = 'FOIL stats stay locked until production credentials are configured.';

export function useFoilActivity(): MetricsHookResult<FoilSummary> {
  if (IS_DEMO_MODE || !FOIL_ENABLED) {
    const locked = buildDemoLockedState<FoilSummary>(FOIL_LOCK_MESSAGE);
    return { ...locked, state: locked, refetch: async () => {} } satisfies MetricsHookResult<FoilSummary>;
  }

  return useFoilActivityEnabled();
}

function useFoilActivityEnabled(): MetricsHookResult<FoilSummary> {
  const [snapshot, setSnapshot] = useState<MetricsState<FoilSummary>>(() =>
    buildInitialMetricsState<FoilSummary>(),
  );

  const fetchFoil = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<FoilSummary>(FOIL_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const cutoffDate = new Date(Date.now() - FOIL_RECENT_WINDOW_DAYS * 24 * 60 * 60 * 1000)
        .toISOString()
        .slice(0, 10);

      const [totalResult, recentResult, latestResult, agencyResult] = await Promise.all([
        demoSafeSelect<null>(supabaseClient.from('foil_responses').select('id', { count: 'exact', head: true })),
        demoSafeSelect<null>(
          supabaseClient.from('foil_responses').select('id', { count: 'exact', head: true }).gte('received_date', cutoffDate),
        ),
        demoSafeSelect<FoilLatestRow[] | null>(
          supabaseClient
            .from('foil_responses')
            .select('agency, received_date, created_at')
            .order('received_date', { ascending: false })
            .order('created_at', { ascending: false })
            .limit(1),
        ),
        demoSafeSelect<{ agency: string | null }[] | null>(
          supabaseClient.from('foil_responses').select('agency').not('agency', 'is', null),
        ),
      ]);

      const results = [totalResult, recentResult, latestResult, agencyResult];
      if (results.some((result) => result.kind === 'demo_locked')) {
        setSnapshot(buildDemoLockedState<FoilSummary>(FOIL_LOCK_MESSAGE));
        return;
      }

      const errored = results.find((result) => result.kind === 'error') as
        | { kind: 'error'; error: PostgrestError }
        | undefined;
      if (errored) {
        throw errored.error;
      }

      if (
        totalResult.kind !== 'ok' ||
        recentResult.kind !== 'ok' ||
        latestResult.kind !== 'ok' ||
        agencyResult.kind !== 'ok'
      ) {
        throw new Error('Unexpected FOIL metrics state.');
      }

      const latest = ((latestResult.data ?? []) as FoilLatestRow[])[0];
      const agencies = ((agencyResult.data ?? []) as { agency: string | null }[])
        .map((row) => row.agency?.trim() ?? '')
        .filter((value) => value.length > 0);
      const uniqueAgencies = new Set(agencies).size;

      setSnapshot(
        buildReadyMetricsState<FoilSummary>({
          total: totalResult.count ?? 0,
          recent: recentResult.count ?? 0,
          uniqueAgencies,
          latestAgency: latest?.agency ?? null,
          latestDate: latest?.received_date ?? latest?.created_at ?? null,
        }),
      );
    } catch (err) {
      if (isFoilAccessDenied(err)) {
        setSnapshot(buildDemoLockedState<FoilSummary>(FOIL_LOCK_MESSAGE));
        return;
      }

      const normalized = err instanceof Error ? err : new Error('We could not load FOIL activity.');
      const friendly = deriveFoilErrorMessage(normalized);
      setSnapshot(buildErrorMetricsState<FoilSummary>(normalized, { message: friendly }));
    }
  }, []);

  useEffect(() => {
    void fetchFoil();
  }, [fetchFoil]);

  const refetch = useCallback(() => fetchFoil(), [fetchFoil]);

  return { ...snapshot, state: snapshot, refetch } satisfies MetricsHookResult<FoilSummary>;
}

function isFoilAccessDenied(error: unknown): boolean {
  if (!error || typeof error !== 'object') {
    return false;
  }

  const maybePostgrest = error as Partial<PostgrestError> & { status?: number };
  const code = typeof maybePostgrest.code === 'string' ? maybePostgrest.code.toLowerCase() : '';
  if (code.includes('401') || code === '42501' || code === 'pgrst301' || code === 'pgrst302') {
    return true;
  }

  const status = typeof maybePostgrest.status === 'number' ? maybePostgrest.status : null;
  if (status === 401) {
    return true;
  }

  const message = [maybePostgrest.message, maybePostgrest.details, maybePostgrest.hint]
    .filter((value): value is string => typeof value === 'string' && value.length > 0)
    .join(' ')
    .toLowerCase();

  if (!message) {
    return false;
  }

  return (
    message.includes('jwt') ||
    message.includes('token') ||
    message.includes('unauthorized') ||
    message.includes('permission denied') ||
    message.includes('access denied')
  );
}

function deriveFoilErrorMessage(error: Error): string {
  const message = error.message?.trim();
  return message && message.length > 0 ? message : 'We could not load FOIL activity.';
}
