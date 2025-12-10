/**
 * useOpsAlerts - Hook for fetching system health alerts
 *
 * Returns:
 * - queue_failed_24h: Failed jobs in last 24h
 * - ingest_failures_24h: Failed ingestion batches in last 24h
 * - stalled_workflows: Pending jobs older than 7 days
 * - system_status: 'Healthy' or 'Critical'
 * - isCritical: boolean for quick checks
 */

import { useState, useEffect, useCallback } from "react";
import { apiClient } from "../lib/apiClient";

export interface OpsAlertsData {
  queue_failed_24h: number;
  ingest_failures_24h: number;
  stalled_workflows: number;
  system_status: "Healthy" | "Critical";
  computed_at: string;
}

export interface UseOpsAlertsResult {
  data: OpsAlertsData | null;
  loading: boolean;
  error: string | null;
  isCritical: boolean;
  refresh: () => void;
}

export function useOpsAlerts(pollIntervalMs = 60000): UseOpsAlertsResult {
  const [data, setData] = useState<OpsAlertsData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchAlerts = useCallback(async () => {
    try {
      const response = await apiClient.get<OpsAlertsData>(
        "/api/v1/analytics/ops-alerts"
      );
      setData(response);
      setError(null);
    } catch (err) {
      const message =
        err instanceof Error ? err.message : "Failed to fetch ops alerts";
      setError(message);
      console.error("[useOpsAlerts] Fetch error:", err);
    } finally {
      setLoading(false);
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchAlerts();
  }, [fetchAlerts]);

  // Polling
  useEffect(() => {
    if (pollIntervalMs <= 0) return;

    const interval = setInterval(fetchAlerts, pollIntervalMs);
    return () => clearInterval(interval);
  }, [fetchAlerts, pollIntervalMs]);

  return {
    data,
    loading,
    error,
    isCritical: data?.system_status === "Critical",
    refresh: fetchAlerts,
  };
}

export default useOpsAlerts;
