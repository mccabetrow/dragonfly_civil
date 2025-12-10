/**
 * useSystemHealth - Hook for polling system health status
 *
 * Polls /api/health every 60 seconds and provides:
 * - isOnline: boolean (true if backend is responding)
 * - environment: string (prod/dev/staging)
 * - latencyMs: number (response time in milliseconds)
 * - status: 'loading' | 'online' | 'offline'
 * - lastChecked: Date | null
 *
 * Used by:
 * - Sidebar system status indicator
 * - Topbar environment badge
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { apiClient, type HealthCheckResult } from '../lib/apiClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface SystemHealthState {
  status: 'loading' | 'online' | 'offline';
  isOnline: boolean;
  environment: string;
  latencyMs: number | null;
  lastChecked: Date | null;
  error: string | null;
}

export interface UseSystemHealthOptions {
  /** Polling interval in milliseconds (default: 60000) */
  pollIntervalMs?: number;
  /** Whether to start polling immediately (default: true) */
  enabled?: boolean;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

const DEFAULT_POLL_INTERVAL_MS = 60_000; // 60 seconds

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useSystemHealth(options: UseSystemHealthOptions = {}): SystemHealthState {
  const { pollIntervalMs = DEFAULT_POLL_INTERVAL_MS, enabled = true } = options;

  const [state, setState] = useState<SystemHealthState>({
    status: 'loading',
    isOnline: false,
    environment: 'unknown',
    latencyMs: null,
    lastChecked: null,
    error: null,
  });

  const isCheckingRef = useRef(false);

  const checkHealth = useCallback(async () => {
    // Prevent concurrent checks
    if (isCheckingRef.current) return;
    isCheckingRef.current = true;

    const startTime = performance.now();

    try {
      const result: HealthCheckResult = await apiClient.checkHealth();
      const latency = Math.round(performance.now() - startTime);

      setState({
        status: result.ok ? 'online' : 'offline',
        isOnline: result.ok,
        environment: result.environment ?? 'unknown',
        latencyMs: latency,
        lastChecked: new Date(),
        error: result.ok ? null : (result.error ?? 'Health check failed'),
      });
    } catch (err) {
      const latency = Math.round(performance.now() - startTime);

      setState((prev) => ({
        ...prev,
        status: 'offline',
        isOnline: false,
        latencyMs: latency,
        lastChecked: new Date(),
        error: err instanceof Error ? err.message : 'Unknown error',
      }));
    } finally {
      isCheckingRef.current = false;
    }
  }, []);

  // Initial check on mount
  useEffect(() => {
    if (enabled) {
      checkHealth();
    }
  }, [enabled, checkHealth]);

  // Polling interval
  useEffect(() => {
    if (!enabled || pollIntervalMs <= 0) return;

    const interval = setInterval(checkHealth, pollIntervalMs);
    return () => clearInterval(interval);
  }, [enabled, pollIntervalMs, checkHealth]);

  // Re-check on visibility change (when user returns to tab)
  useEffect(() => {
    if (!enabled) return;

    const handleVisibilityChange = () => {
      if (document.visibilityState === 'visible') {
        checkHealth();
      }
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => document.removeEventListener('visibilitychange', handleVisibilityChange);
  }, [enabled, checkHealth]);

  return state;
}

export default useSystemHealth;
