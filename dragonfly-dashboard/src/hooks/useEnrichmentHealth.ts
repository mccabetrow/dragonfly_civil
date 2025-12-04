/**
 * useEnrichmentHealth
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Supabase hook for the ops.v_enrichment_health view.
 * Monitors worker health and queue status.
 */
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
import { useOnRefresh } from '../context/RefreshContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface EnrichmentHealthRow {
  metric: string;
  value: number;
  asOf: string | null;
}

export interface EnrichmentHealthSummary {
  queuedCount: number;
  processingCount: number;
  completedCount: number;
  failedCount: number;
  lastProcessed: string | null;
  isHealthy: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useEnrichmentHealth(): MetricsHookResult<EnrichmentHealthSummary> {
  const [snapshot, setSnapshot] = useState<MetricsState<EnrichmentHealthSummary>>(() =>
    buildInitialMetricsState<EnrichmentHealthSummary>()
  );

  const fetchData = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<EnrichmentHealthSummary>());
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const query = supabaseClient
        .from('v_enrichment_health')
        .select('metric, value, as_of');

      const result = await demoSafeSelect<Array<Record<string, unknown>> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<EnrichmentHealthSummary>());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const rows = (result.data ?? []) as Array<Record<string, unknown>>;
      
      // Parse the health metrics into a summary
      const summary = parseHealthMetrics(rows);
      setSnapshot(buildReadyMetricsState(summary));
    } catch (err) {
      // If the view doesn't exist, return a "no data" state rather than error
      const errorMessage = err instanceof Error ? err.message : String(err);
      if (errorMessage.includes('does not exist') || errorMessage.includes('404')) {
        setSnapshot(
          buildReadyMetricsState<EnrichmentHealthSummary>({
            queuedCount: 0,
            processingCount: 0,
            completedCount: 0,
            failedCount: 0,
            lastProcessed: null,
            isHealthy: true, // No queue = healthy
          })
        );
        return;
      }

      const error =
        err instanceof Error
          ? err
          : typeof err === 'string'
          ? err
          : new Error('Unable to load enrichment health.');
      setSnapshot(
        buildErrorMetricsState<EnrichmentHealthSummary>(error, {
          message: 'Unable to load enrichment health metrics.',
        })
      );
    }
  }, []);

  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  // Subscribe to global refresh
  useOnRefresh(() => fetchData());

  const refetch = useCallback(() => fetchData(), [fetchData]);

  return { ...snapshot, state: snapshot, refetch };
}

// ═══════════════════════════════════════════════════════════════════════════
// HELPERS
// ═══════════════════════════════════════════════════════════════════════════

function parseHealthMetrics(rows: Array<Record<string, unknown>>): EnrichmentHealthSummary {
  const metricsMap = new Map<string, { value: number; asOf: string | null }>();

  for (const row of rows) {
    const metric = String(row.metric ?? '');
    const value = Number(row.value ?? 0);
    const asOf = row.as_of != null ? String(row.as_of) : null;
    metricsMap.set(metric, { value, asOf });
  }

  const queuedCount = metricsMap.get('queued')?.value ?? 0;
  const processingCount = metricsMap.get('processing')?.value ?? 0;
  const completedCount = metricsMap.get('completed')?.value ?? 0;
  const failedCount = metricsMap.get('failed')?.value ?? 0;
  const lastProcessed = metricsMap.get('completed')?.asOf ?? null;

  // Healthy if no failed jobs and queue isn't backing up excessively
  const isHealthy = failedCount === 0 && queuedCount < 100;

  return {
    queuedCount,
    processingCount,
    completedCount,
    failedCount,
    lastProcessed,
    isHealthy,
  };
}
