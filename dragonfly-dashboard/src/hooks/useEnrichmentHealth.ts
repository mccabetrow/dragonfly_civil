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

export type EnrichmentStatus = 'active' | 'idle' | 'backlog' | 'degraded';

export interface EnrichmentHealthSummary {
  pendingJobs: number;
  processingJobs: number;
  completedJobs: number;
  failedJobs: number;
  lastJobCreatedAt: string | null;
  lastJobUpdatedAt: string | null;
  timeSinceLastActivity: string | null;
  status: EnrichmentStatus;
  statusLabel: string;
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
      // Query the view directly - it returns a single row with aggregated metrics
      const query = supabaseClient
        .from('v_enrichment_health')
        .select('pending_jobs, processing_jobs, failed_jobs, completed_jobs, last_job_created_at, last_job_updated_at, time_since_last_activity')
        .limit(1)
        .single();

      const result = await demoSafeSelect<Record<string, unknown> | null>(query);

      if (result.kind === 'demo_locked') {
        setSnapshot(buildDemoLockedState<EnrichmentHealthSummary>());
        return;
      }

      if (result.kind === 'error') {
        throw result.error;
      }

      const row = result.data;
      const summary = parseHealthRow(row);
      setSnapshot(buildReadyMetricsState(summary));
    } catch (err) {
      // If the view doesn't exist or returns no rows, return a "no data" state
      const errorMessage = err instanceof Error ? err.message : String(err);
      if (
        errorMessage.includes('does not exist') ||
        errorMessage.includes('404') ||
        errorMessage.includes('PGRST116') // single row not found
      ) {
        setSnapshot(
          buildReadyMetricsState<EnrichmentHealthSummary>({
            pendingJobs: 0,
            processingJobs: 0,
            completedJobs: 0,
            failedJobs: 0,
            lastJobCreatedAt: null,
            lastJobUpdatedAt: null,
            timeSinceLastActivity: null,
            status: 'idle',
            statusLabel: 'Idle',
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

function parseHealthRow(row: Record<string, unknown> | null): EnrichmentHealthSummary {
  if (!row) {
    return {
      pendingJobs: 0,
      processingJobs: 0,
      completedJobs: 0,
      failedJobs: 0,
      lastJobCreatedAt: null,
      lastJobUpdatedAt: null,
      timeSinceLastActivity: null,
      status: 'idle',
      statusLabel: 'Idle',
    };
  }

  const pendingJobs = Number(row.pending_jobs ?? 0);
  const processingJobs = Number(row.processing_jobs ?? 0);
  const completedJobs = Number(row.completed_jobs ?? 0);
  const failedJobs = Number(row.failed_jobs ?? 0);
  const lastJobCreatedAt = row.last_job_created_at != null ? String(row.last_job_created_at) : null;
  const lastJobUpdatedAt = row.last_job_updated_at != null ? String(row.last_job_updated_at) : null;
  const timeSinceLastActivity = row.time_since_last_activity != null ? String(row.time_since_last_activity) : null;

  // Determine status based on the priority rules
  let status: EnrichmentStatus;
  let statusLabel: string;

  if (failedJobs > 0) {
    status = 'degraded';
    statusLabel = 'System Degraded';
  } else if (pendingJobs > 100) {
    status = 'backlog';
    statusLabel = 'Backlog High';
  } else if (pendingJobs === 0 && processingJobs === 0) {
    status = 'idle';
    statusLabel = 'Idle';
  } else {
    status = 'active';
    statusLabel = 'Enrichment Active';
  }

  return {
    pendingJobs,
    processingJobs,
    completedJobs,
    failedJobs,
    lastJobCreatedAt,
    lastJobUpdatedAt,
    timeSinceLastActivity,
    status,
    statusLabel,
  };
}

/**
 * Humanize a PostgreSQL interval string (e.g., "00:03:45.123456") to "3m ago"
 */
export function humanizeInterval(interval: string | null): string {
  if (!interval) return 'Never';

  // PostgreSQL interval format: "HH:MM:SS.microseconds" or "X days HH:MM:SS"
  const dayMatch = interval.match(/(\d+)\s*days?\s+(\d+):(\d+):(\d+)/);
  const timeMatch = interval.match(/^(\d+):(\d+):(\d+)/);

  let totalSeconds = 0;

  if (dayMatch) {
    const days = parseInt(dayMatch[1], 10);
    const hours = parseInt(dayMatch[2], 10);
    const minutes = parseInt(dayMatch[3], 10);
    const seconds = parseInt(dayMatch[4], 10);
    totalSeconds = days * 86400 + hours * 3600 + minutes * 60 + seconds;
  } else if (timeMatch) {
    const hours = parseInt(timeMatch[1], 10);
    const minutes = parseInt(timeMatch[2], 10);
    const seconds = parseInt(timeMatch[3], 10);
    totalSeconds = hours * 3600 + minutes * 60 + seconds;
  } else {
    return interval; // Return as-is if we can't parse
  }

  if (totalSeconds < 60) {
    return `${totalSeconds}s ago`;
  } else if (totalSeconds < 3600) {
    const mins = Math.floor(totalSeconds / 60);
    return `${mins}m ago`;
  } else if (totalSeconds < 86400) {
    const hours = Math.floor(totalSeconds / 3600);
    const mins = Math.floor((totalSeconds % 3600) / 60);
    return mins > 0 ? `${hours}h ${mins}m ago` : `${hours}h ago`;
  } else {
    const days = Math.floor(totalSeconds / 86400);
    const hours = Math.floor((totalSeconds % 86400) / 3600);
    return hours > 0 ? `${days}d ${hours}h ago` : `${days}d ago`;
  }
}
