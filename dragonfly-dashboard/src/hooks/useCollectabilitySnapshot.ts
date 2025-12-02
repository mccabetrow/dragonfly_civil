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

export interface CollectabilitySnapshotRow {
  case_id: string;
  case_number: string | null;
  judgment_amount: number | null;
  judgment_date: string | null;
  age_days: number | null;
  last_enriched_at: string | null;
  last_enrichment_status: string | null;
  collectability_tier: string;
}

const COLLECTABILITY_LOCK_MESSAGE =
  'Collectability snapshot metrics are hidden in this demo build. Switch to the production console to view plaintiff-level data.';

export function useCollectabilitySnapshot(): MetricsHookResult<CollectabilitySnapshotRow[]> {
  const [snapshot, setSnapshot] = useState<MetricsState<CollectabilitySnapshotRow[]>>(() =>
    buildInitialMetricsState<CollectabilitySnapshotRow[]>(),
  );

  const fetchSnapshot = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<CollectabilitySnapshotRow[]>(COLLECTABILITY_LOCK_MESSAGE));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));
    try {
      const result = await demoSafeSelect<CollectabilitySnapshotRow[] | null>(
        supabaseClient
          .from('v_collectability_snapshot')
          .select('*')
          .order('collectability_tier', { ascending: true })
          .order('judgment_amount', { ascending: false, nullsFirst: false }),
      );

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState(COLLECTABILITY_LOCK_MESSAGE));
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      setSnapshot(buildReadyMetricsState((result.data ?? []) as CollectabilitySnapshotRow[]));
    } catch (err) {
      const friendly = deriveCollectabilityErrorMessage(err);
      const error = err instanceof Error ? err : new Error(friendly);
      setSnapshot(buildErrorMetricsState<CollectabilitySnapshotRow[]>(error, { message: friendly }));
    }
  }, []);

  useEffect(() => {
    void fetchSnapshot();
  }, [fetchSnapshot]);

  return { ...snapshot, state: snapshot, refetch: fetchSnapshot };
}

function deriveCollectabilityErrorMessage(err: unknown): string {
  if (isSchemaCacheMiss(err)) {
    return 'Collectability snapshot view is unavailable. Apply migrations and refresh the schema cache.';
  }
  if (err instanceof Error && err.message.trim().length > 0) {
    return err.message;
  }
  return 'Unable to load collectability snapshot.';
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
