/**
 * useEnforcementEngineData
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Real-time metrics hook for the Enforcement Engine Worker dashboard.
 * Fetches plan creation, packet generation, and worker queue statistics.
 *
 * Features:
 *   - Auto-refresh polling (30s default)
 *   - Manual refetch support
 *   - Demo mode detection
 *   - Type-safe API response
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { apiClient, AuthError, NotFoundError } from '../lib/apiClient';
import { IS_DEMO_MODE } from '../lib/supabaseClient';
import {
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';
import { useOnRefresh } from '../context/RefreshContext';
import type { EnforcementEngineMetrics } from '../types';

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

/** Polling interval in milliseconds (30 seconds) */
const POLL_INTERVAL_MS = 30_000;

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA
// ═══════════════════════════════════════════════════════════════════════════

const DEMO_METRICS: EnforcementEngineMetrics = {
  plans_created_24h: 12,
  plans_created_7d: 67,
  total_plans: 342,
  packets_generated_24h: 8,
  packets_generated_7d: 45,
  total_packets: 218,
  active_workers: 2,
  pending_jobs: 5,
  completed_24h: 18,
  failed_24h: 1,
  generated_at: new Date().toISOString(),
};

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export interface UseEnforcementEngineDataOptions {
  /** Enable auto-refresh polling. Defaults to true. */
  polling?: boolean;
  /** Polling interval in ms. Defaults to 30000 (30s). */
  pollIntervalMs?: number;
}

export function useEnforcementEngineData(
  options: UseEnforcementEngineDataOptions = {}
): MetricsHookResult<EnforcementEngineMetrics> {
  const { polling = true, pollIntervalMs = POLL_INTERVAL_MS } = options;

  const [snapshot, setSnapshot] = useState<MetricsState<EnforcementEngineMetrics>>(() =>
    buildInitialMetricsState<EnforcementEngineMetrics>()
  );

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchData = useCallback(async () => {
    // Demo mode returns mock data
    if (IS_DEMO_MODE) {
      setSnapshot(buildReadyMetricsState(DEMO_METRICS));
      return;
    }

    setSnapshot((previous) => buildLoadingMetricsState(previous));

    try {
      const data = await apiClient.get<EnforcementEngineMetrics>(
        '/api/v1/analytics/enforcement-engine'
      );

      setSnapshot(buildReadyMetricsState(data));
    } catch (err) {
      const isAuth = err instanceof AuthError;
      const isNotFound = err instanceof NotFoundError;
      const message = err instanceof Error ? err.message : 'Unknown error';
      const errorObj = err instanceof Error ? err : new Error(message);

      setSnapshot(
        buildErrorMetricsState<EnforcementEngineMetrics>(errorObj, {
          message,
          isAuthError: isAuth,
          isNotFound,
        })
      );
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    void fetchData();
  }, [fetchData]);

  // Polling setup
  useEffect(() => {
    if (!polling) return;

    pollTimerRef.current = setInterval(() => {
      void fetchData();
    }, pollIntervalMs);

    return () => {
      if (pollTimerRef.current) {
        clearInterval(pollTimerRef.current);
        pollTimerRef.current = null;
      }
    };
  }, [polling, pollIntervalMs, fetchData]);

  // Respond to global refresh bus
  useOnRefresh(fetchData);

  return {
    ...snapshot,
    state: snapshot,
    refetch: fetchData,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPUTED HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Compute derived KPIs from raw enforcement engine metrics.
 */
export function computeEnforcementEngineKPIs(data: EnforcementEngineMetrics | null) {
  if (!data) {
    return {
      planVelocity: 0,
      packetVelocity: 0,
      successRate24h: 100,
      queueHealth: 'idle' as const,
      isHealthy: true,
    };
  }

  const totalProcessed24h = data.completed_24h + data.failed_24h;
  const successRate24h = totalProcessed24h > 0
    ? Math.round((data.completed_24h / totalProcessed24h) * 100)
    : 100;

  // Queue health assessment
  let queueHealth: 'healthy' | 'busy' | 'backlogged' | 'idle';
  if (data.active_workers === 0 && data.pending_jobs === 0) {
    queueHealth = 'idle';
  } else if (data.pending_jobs > 50) {
    queueHealth = 'backlogged';
  } else if (data.pending_jobs > 10 || data.active_workers > 3) {
    queueHealth = 'busy';
  } else {
    queueHealth = 'healthy';
  }

  const isHealthy = data.failed_24h === 0 && queueHealth !== 'backlogged';

  return {
    planVelocity: data.plans_created_7d,
    packetVelocity: data.packets_generated_7d,
    successRate24h,
    queueHealth,
    isHealthy,
  };
}
