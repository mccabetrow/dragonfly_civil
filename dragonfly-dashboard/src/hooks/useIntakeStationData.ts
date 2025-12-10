/**
 * useIntakeStationData - Unified data hook for Intake Station page
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Combines:
 *   - Intake radar metrics (24h/7d judgment counts, AUM, validity rate)
 *   - Batch history (recent uploads with status) via API
 *   - Real-time polling support (auto-refresh every 30s)
 *
 * Design:
 *   - Skeleton-ready loading states (no spinners)
 *   - Graceful error handling with user-friendly messages
 *   - RefreshContext integration for manual refresh
 */
import { useCallback, useEffect, useState } from 'react';
import { useOnRefresh } from '../context/RefreshContext';
import { supabaseClient, IS_DEMO_MODE } from '../lib/supabaseClient';
import { apiClient } from '../lib/apiClient';

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
}

export interface UseIntakeStationDataResult extends IntakeStationData {
  refetch: () => Promise<void>;
  startPolling: () => void;
  stopPolling: () => void;
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

// API response type from /api/v1/intake/batches
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

const POLLING_INTERVAL_MS = 5_000; // 5 seconds for real-time feel

export function useIntakeStationData(): UseIntakeStationDataResult {
  const [data, setData] = useState<IntakeStationData>({
    radar: null,
    batches: [],
    isLoading: true,
    isPolling: false,
    error: null,
    lastUpdated: null,
  });

  const [pollingEnabled, setPollingEnabled] = useState(false);

  const fetchData = useCallback(async () => {
    // Demo mode - return mock data
    if (IS_DEMO_MODE) {
      setData({
        radar: DEMO_RADAR,
        batches: DEMO_BATCHES,
        isLoading: false,
        isPolling: pollingEnabled,
        error: null,
        lastUpdated: new Date(),
      });
      return;
    }

    try {
      // Fetch radar metrics via Supabase RPC
      const { data: radarData, error: radarError } = await supabaseClient.rpc(
        'intake_radar_metrics_v2'
      );

      if (radarError) {
        console.warn('Intake radar RPC error:', radarError);
      }

      // Fetch batch history via API endpoint (ops schema not exposed via PostgREST)
      let batches: IntakeBatchSummary[] = [];
      try {
        const batchResponse = await apiClient.get<{ batches: ApiBatchRow[] }>('/api/v1/intake/batches?limit=25');
        if (batchResponse.batches) {
          batches = batchResponse.batches.map(normalizeApiBatch);
        }
      } catch (batchErr) {
        console.warn('Intake batches API error:', batchErr);
      }

      // Normalize radar data
      const radarRow = Array.isArray(radarData) && radarData.length > 0 ? radarData[0] : null;
      const radar = radarRow ? normalizeRadar(radarRow) : null;

      setData({
        radar,
        batches,
        isLoading: false,
        isPolling: pollingEnabled,
        error: null,
        lastUpdated: new Date(),
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Failed to load intake data';
      setData((prev) => ({
        ...prev,
        isLoading: false,
        error: message,
      }));
    }
  }, [pollingEnabled]);

  // Initial fetch
  useEffect(() => {
    fetchData();
  }, [fetchData]);

  // Polling interval
  useEffect(() => {
    if (!pollingEnabled) return;

    const interval = setInterval(() => {
      fetchData();
    }, POLLING_INTERVAL_MS);

    return () => clearInterval(interval);
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
