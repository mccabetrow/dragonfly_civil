/**
 * useIntakeStationData - Unified data hook for Intake Station page
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * PR-2: UI State Machine & Polling Fallback
 *
 * Architecture:
 *   - PRIMARY: Polling Timer (fetch /intake/state every 5s) - never stops
 *   - SECONDARY: Realtime subscription (triggers immediate refetch on events)
 *   - Resilience: If Realtime fails/reconnects, Polling continues uninterrupted
 *
 * Combines:
 *   - Intake radar metrics (24h/7d judgment counts, AUM, validity rate)
 *   - Batch history (recent uploads with status) via API
 *   - Degraded mode detection from PR-1 envelope
 *
 * Design:
 *   - Skeleton-ready loading states (no spinners)
 *   - Graceful error handling with user-friendly messages
 *   - RefreshContext integration for manual refresh
 *   - Green flash animation on realtime updates
 */
import { useCallback, useEffect, useState, useRef } from 'react';
import { useOnRefresh } from '../context/RefreshContext';
import { supabaseClient, IS_DEMO_MODE } from '../lib/supabaseClient';
import { apiClient } from '../lib/apiClient';
import { useJobQueueRealtime, useJudgmentRealtime } from './useRealtimeSubscription';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface IntakeRadarMetrics {
  judgmentsIngested24h: number;
  judgmentsIngested7d: number;
  newAum24h: number;
  validityRate24h: number;
  queueDepthPending: number;
  criticalFailures24h: number;
  avgProcessingTimeSeconds: number;
}

export interface IntakeBatchSummary {
  id: string;
  filename: string;
  source: string;
  status: 'pending' | 'processing' | 'completed' | 'failed';
  totalRows: number;
  validRows: number;
  errorRows: number;
  successRate: number;
  healthStatus: 'healthy' | 'warning' | 'critical';
  createdAt: string;
  completedAt: string | null;
  durationSeconds: number | null;
}

export interface IntakeStationData {
  radar: IntakeRadarMetrics | null;
  batches: IntakeBatchSummary[];
  isLoading: boolean;
  isPolling: boolean;
  error: string | null;
  lastUpdated: Date | null;
  /** True when a realtime update just occurred (for flash animation) */
  isFlashing: boolean;
  /** Whether connected to realtime channel */
  isRealtimeConnected: boolean;
  /** True if backend returned degraded: true (partial data, downstream failure) */
  isDegraded: boolean;
}

export interface UseIntakeStationDataResult extends IntakeStationData {
  refetch: () => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
  /** Number of realtime events received this session */
  realtimeEventCount: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// DEMO DATA
// ═══════════════════════════════════════════════════════════════════════════

const DEMO_RADAR: IntakeRadarMetrics = {
  judgmentsIngested24h: 47,
  judgmentsIngested7d: 312,
  newAum24h: 1_850_000,
  validityRate24h: 94.2,
  queueDepthPending: 12,
  criticalFailures24h: 2,
  avgProcessingTimeSeconds: 3.4,
};

const DEMO_BATCHES: IntakeBatchSummary[] = [
  {
    id: 'demo-batch-001',
    filename: 'simplicity_export_dec09.csv',
    source: 'simplicity',
    status: 'completed',
    totalRows: 150,
    validRows: 142,
    errorRows: 8,
    successRate: 94.7,
    healthStatus: 'healthy',
    createdAt: new Date(Date.now() - 2 * 60 * 60 * 1000).toISOString(),
    completedAt: new Date(Date.now() - 1.9 * 60 * 60 * 1000).toISOString(),
    durationSeconds: 4.2,
  },
  {
    id: 'demo-batch-002',
    filename: 'jbi_weekly_batch.csv',
    source: 'jbi',
    status: 'completed',
    totalRows: 89,
    validRows: 89,
    errorRows: 0,
    successRate: 100,
    healthStatus: 'healthy',
    createdAt: new Date(Date.now() - 24 * 60 * 60 * 1000).toISOString(),
    completedAt: new Date(Date.now() - 23.9 * 60 * 60 * 1000).toISOString(),
    durationSeconds: 2.1,
  },
  {
    id: 'demo-batch-003',
    filename: 'manual_intake.csv',
    source: 'manual',
    status: 'failed',
    totalRows: 25,
    validRows: 0,
    errorRows: 25,
    successRate: 0,
    healthStatus: 'critical',
    createdAt: new Date(Date.now() - 48 * 60 * 60 * 1000).toISOString(),
    completedAt: new Date(Date.now() - 47.9 * 60 * 60 * 1000).toISOString(),
    durationSeconds: 0.5,
  },
];

// ═══════════════════════════════════════════════════════════════════════════
// NORMALIZERS
// ═══════════════════════════════════════════════════════════════════════════

interface RawRadarRow {
  judgments_ingested_24h?: number | null;
  judgments_ingested_7d?: number | null;
  new_aum_24h?: number | string | null;
  validity_rate_24h?: number | null;
  queue_depth_pending?: number | null;
  critical_failures_24h?: number | null;
  avg_processing_time_seconds?: number | null;
}

function normalizeRadar(raw: RawRadarRow): IntakeRadarMetrics {
  return {
    judgmentsIngested24h: raw.judgments_ingested_24h ?? 0,
    judgmentsIngested7d: raw.judgments_ingested_7d ?? 0,
    newAum24h:
      typeof raw.new_aum_24h === 'string'
        ? parseFloat(raw.new_aum_24h)
        : raw.new_aum_24h ?? 0,
    validityRate24h: raw.validity_rate_24h ?? 0,
    queueDepthPending: raw.queue_depth_pending ?? 0,
    criticalFailures24h: raw.critical_failures_24h ?? 0,
    avgProcessingTimeSeconds: raw.avg_processing_time_seconds ?? 0,
  };
}

// PR-1 Envelope: API responses wrap data in { ok, data, degraded, error, meta }
interface ApiEnvelope<T> {
  ok: boolean;
  data: T | null;
  degraded?: boolean;
  error?: string | null;
  meta?: {
    trace_id: string;
    timestamp: string;
  };
}

// API response type from /api/v1/intake/batches (inside envelope.data)
interface ApiBatchRow {
  id: string;
  filename: string;
  source: string;
  status: string;
  total_rows: number;
  valid_rows: number;
  error_rows: number;
  success_rate: number;
  health_status: string;
  created_at: string;
  completed_at: string | null;
  duration_seconds: number | null;
}

interface ApiBatchesData {
  batches: ApiBatchRow[];
}

function normalizeApiBatch(raw: ApiBatchRow): IntakeBatchSummary {
  const status = (raw.status ?? 'pending') as IntakeBatchSummary['status'];
  const healthStatus = (raw.health_status ?? 'healthy') as IntakeBatchSummary['healthStatus'];

  return {
    id: raw.id ?? '',
    filename: raw.filename ?? 'Unknown file',
    source: raw.source ?? 'unknown',
    status,
    totalRows: raw.total_rows ?? 0,
    validRows: raw.valid_rows ?? 0,
    errorRows: raw.error_rows ?? 0,
    successRate: raw.success_rate ?? 0,
    healthStatus,
    createdAt: raw.created_at ?? new Date().toISOString(),
    completedAt: raw.completed_at ?? null,
    durationSeconds: raw.duration_seconds ?? null,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

const POLLING_INTERVAL_MS = 5_000; // 5 seconds - PRIMARY data source
const FLASH_DURATION_MS = 1500; // Duration of green flash animation

export function useIntakeStationData(): UseIntakeStationDataResult {
  const [data, setData] = useState<IntakeStationData>({
    radar: null,
    batches: [],
    isLoading: true,
    isPolling: false,
    error: null,
    lastUpdated: null,
    isFlashing: false,
    isRealtimeConnected: false,
    isDegraded: false,
  });

  // Polling is ALWAYS enabled by default - never depends on realtime
  const [pollingEnabled, setPollingEnabled] = useState(true);
  const flashTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Flash animation handler
  const triggerFlash = useCallback(() => {
    setData((prev) => ({ ...prev, isFlashing: true }));
    
    if (flashTimeoutRef.current) {
      clearTimeout(flashTimeoutRef.current);
    }
    
    flashTimeoutRef.current = setTimeout(() => {
      setData((prev) => ({ ...prev, isFlashing: false }));
    }, FLASH_DURATION_MS);
  }, []);

  // Cleanup flash timeout on unmount
  useEffect(() => {
    return () => {
      if (flashTimeoutRef.current) {
        clearTimeout(flashTimeoutRef.current);
      }
    };
  }, []);

  const fetchData = useCallback(async () => {
    // Demo mode - return mock data
    if (IS_DEMO_MODE) {
      setData((prev) => ({
        ...prev,
        radar: DEMO_RADAR,
        batches: DEMO_BATCHES,
        isLoading: false,
        isPolling: pollingEnabled,
        error: null,
        lastUpdated: new Date(),
        isDegraded: false,
      }));
      return;
    }

    let isDegraded = false;

    try {
      // Fetch radar metrics via Supabase RPC
      const { data: radarData, error: radarError } = await supabaseClient.rpc(
        'intake_radar_metrics_v2'
      );

      if (radarError) {
        console.warn('Intake radar RPC error:', radarError);
      }

      // Fetch batch history via API endpoint (PR-1 envelope format)
      let batches: IntakeBatchSummary[] = [];
      try {
        // API now returns envelope: { ok, data: { batches }, degraded, error, meta }
        const envelope = await apiClient.get<ApiEnvelope<ApiBatchesData>>('/api/v1/intake/batches?limit=25');
        
        // Check for degraded mode from PR-1 envelope
        if (envelope.degraded) {
          isDegraded = true;
          console.warn('[useIntakeStationData] API returned degraded mode:', envelope.error);
        }
        
        // Extract batches from envelope.data
        if (envelope.ok && envelope.data?.batches) {
          batches = envelope.data.batches.map(normalizeApiBatch);
        } else if (!envelope.ok) {
          console.warn('[useIntakeStationData] API error:', envelope.error);
        }
      } catch (batchErr) {
        console.warn('Intake batches API error:', batchErr);
        // Don't set global error - polling should continue
      }

      // Normalize radar data
      const radarRow = Array.isArray(radarData) && radarData.length > 0 ? radarData[0] : null;
      const radar = radarRow ? normalizeRadar(radarRow) : null;

      setData((prev) => ({
        ...prev,
        radar,
        batches,
        isLoading: false,
        isPolling: pollingEnabled,
        error: null,
        lastUpdated: new Date(),
        isDegraded,
      }));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load intake data';
      setData((prev) => ({
        ...prev,
        isLoading: false,
        error: message,
        isDegraded: true,
      }));
    }
  }, [pollingEnabled]);

  // ═══════════════════════════════════════════════════════════════════════════
  // REALTIME SUBSCRIPTIONS (SECONDARY - enhancement, not dependency)
  // Realtime events trigger immediate refetch, but polling continues regardless
  // ═══════════════════════════════════════════════════════════════════════════

  // Subscribe to job queue updates (job completions trigger refetch)
  const jobRealtime = useJobQueueRealtime({
    onJobComplete: (_jobId, status) => {
      if (status === 'completed' || status === 'failed') {
        // Realtime is an enhancement - trigger immediate refetch
        fetchData();
      }
    },
    onFlash: triggerFlash,
    enabled: !IS_DEMO_MODE,
  });

  // Subscribe to new judgment ingestions
  const judgmentRealtime = useJudgmentRealtime({
    onJudgmentIngested: () => {
      // Realtime is an enhancement - trigger immediate refetch
      fetchData();
    },
    onFlash: triggerFlash,
    enabled: !IS_DEMO_MODE,
  });

  // Update realtime connection status (informational only - doesn't affect polling)
  useEffect(() => {
    const isConnected = jobRealtime.isConnected || judgmentRealtime.isConnected;
    setData((prev) => {
      if (prev.isRealtimeConnected !== isConnected) {
        return { ...prev, isRealtimeConnected: isConnected };
      }
      return prev;
    });
  }, [jobRealtime.isConnected, judgmentRealtime.isConnected]);

  // Initial fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // ═══════════════════════════════════════════════════════════════════════════
  // POLLING TIMER (PRIMARY - always runs, never depends on realtime)
  // ═══════════════════════════════════════════════════════════════════════════
  useEffect(() => {
    if (!pollingEnabled) {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
      return;
    }

    // Start polling interval - runs independently of realtime status
    pollingRef.current = setInterval(() => {
      fetchData();
    }, POLLING_INTERVAL_MS);

    return () => {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [pollingEnabled, fetchData]);

  // Listen for global refresh events
  useOnRefresh(() => {
    fetchData();
  });

  const startPolling = useCallback(() => {
    setPollingEnabled(true);
  }, []);

  const stopPolling = useCallback(() => {
    setPollingEnabled(false);
  }, []);

  return {
    ...data,
    refetch: fetchData,
    startPolling,
    stopPolling,
    realtimeEventCount: jobRealtime.eventCount + judgmentRealtime.eventCount,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// CONVENIENCE HOOKS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Hook for just the radar metrics (lighter weight).
 */
export function useIntakeRadarMetrics(): {
  data: IntakeRadarMetrics | null;
  isLoading: boolean;
  error: string | null;
  refetch: () => Promise<void>;
} {
  const [data, setData] = useState<IntakeRadarMetrics | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchRadar = useCallback(async () => {
    if (IS_DEMO_MODE) {
      setData(DEMO_RADAR);
      setIsLoading(false);
      return;
    }

    try {
      setIsLoading(true);
      const { data: radarData, error: radarError } = await supabaseClient.rpc(
        'intake_radar_metrics_v2'
      );

      if (radarError) throw radarError;

      const row = Array.isArray(radarData) && radarData.length > 0 ? radarData[0] : null;
      setData(row ? normalizeRadar(row) : null);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load radar metrics');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchRadar();
  }, [fetchRadar]);

  useOnRefresh(() => {
    fetchRadar();
  });

  return { data, isLoading, error, refetch: fetchRadar };
}
