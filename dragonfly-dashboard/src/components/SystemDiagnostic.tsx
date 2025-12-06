import { type FC, useState, useEffect, useCallback, useRef } from 'react';
import { apiClient, API_BASE_URL, type HealthCheckResult } from '../lib/apiClient';
import { cn } from '../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

interface HealthState {
  loading: boolean;
  ok: boolean;
  status?: number;
  environment?: string;
  error?: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

/** Health check polling interval in ms (60 seconds) */
const POLL_INTERVAL_MS = 60_000;

/**
 * Mask a URL for display: show protocol + host prefix + ellipsis + domain suffix.
 * Example: https://dragonflycivil-production-d57a…railway.app
 */
function maskUrl(url: string): string {
  try {
    const parsed = new URL(url);
    const host = parsed.host;
    // If host is short, show it all
    if (host.length <= 40) {
      return `${parsed.protocol}//${host}`;
    }
    // Otherwise truncate middle
    const prefix = host.slice(0, 30);
    const suffix = host.slice(-15);
    return `${parsed.protocol}//${prefix}…${suffix}`;
  } catch {
    return url.slice(0, 50) + (url.length > 50 ? '…' : '');
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

/**
 * SystemDiagnostic
 *
 * A small pill badge that shows live backend status:
 * - Green dot + "System Online (Prod/Dev)" when healthy
 * - Red dot + "Backend Disconnected" when unhealthy
 * - Gray dot while loading
 *
 * Polls /api/health every 60 seconds. Hovering shows the masked API URL and HTTP status.
 */
const SystemDiagnostic: FC = () => {
  const [health, setHealth] = useState<HealthState>({ loading: true, ok: false });
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const checkHealth = useCallback(async () => {
    try {
      const result: HealthCheckResult = await apiClient.checkHealth();
      setHealth({
        loading: false,
        ok: result.ok,
        status: result.status,
        environment: result.environment,
        error: result.ok ? undefined : 'Health check failed',
      });
    } catch (err) {
      setHealth({
        loading: false,
        ok: false,
        status: 0,
        environment: undefined,
        error: err instanceof Error ? err.message : 'Unknown error',
      });
    }
  }, []);

  // Initial check + polling
  useEffect(() => {
    checkHealth();
    const interval = setInterval(checkHealth, POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [checkHealth]);

  // Cleanup tooltip timeout on unmount
  useEffect(() => {
    return () => {
      if (tooltipTimeoutRef.current) {
        clearTimeout(tooltipTimeoutRef.current);
      }
    };
  }, []);

  const handleMouseEnter = () => {
    if (tooltipTimeoutRef.current) {
      clearTimeout(tooltipTimeoutRef.current);
    }
    setShowTooltip(true);
  };

  const handleMouseLeave = () => {
    tooltipTimeoutRef.current = setTimeout(() => {
      setShowTooltip(false);
    }, 150);
  };

  // Determine dot color
  const dotColor = health.loading
    ? 'bg-slate-400'
    : health.ok
      ? 'bg-emerald-400'
      : 'bg-red-400';

  // Determine dot animation (pulse when loading or error)
  const dotAnimation = health.loading
    ? 'animate-pulse'
    : !health.ok
      ? 'animate-pulse'
      : '';

  // Status text
  const envLabel = health.environment
    ? health.environment.charAt(0).toUpperCase() + health.environment.slice(1).toLowerCase()
    : 'Unknown';

  const statusText = health.loading
    ? 'Checking…'
    : health.ok
      ? `System Online (${envLabel})`
      : 'Backend Disconnected';

  return (
    <div className="relative">
      {/* Main pill badge */}
      <button
        type="button"
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onClick={checkHealth}
        className={cn(
          'flex items-center gap-2 rounded-full px-3 py-1.5 text-xs font-medium transition-all',
          'bg-slate-800/60 border border-slate-700/50',
          health.ok
            ? 'text-emerald-300 hover:bg-slate-800 hover:border-emerald-500/30'
            : 'text-slate-300 hover:bg-slate-800 hover:border-slate-600',
          'focus:outline-none focus:ring-2 focus:ring-indigo-500/50'
        )}
        aria-label={`System status: ${statusText}. Click to refresh.`}
      >
        {/* Status dot */}
        <span className="relative flex h-2 w-2">
          <span
            className={cn(
              'absolute inline-flex h-full w-full rounded-full opacity-75',
              dotColor,
              dotAnimation
            )}
          />
          <span
            className={cn(
              'relative inline-flex h-2 w-2 rounded-full',
              dotColor
            )}
          />
        </span>
        {/* Status text */}
        <span>{statusText}</span>
      </button>

      {/* Tooltip/Popover */}
      {showTooltip && (
        <div
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
          className={cn(
            'absolute bottom-full left-0 mb-2 w-64 rounded-lg border border-slate-600/50',
            'bg-slate-800 p-3 shadow-xl shadow-slate-900/50',
            'text-xs text-slate-300',
            'z-50'
          )}
        >
          <div className="space-y-2">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                API Endpoint
              </p>
              <p className="mt-0.5 break-all font-mono text-slate-400">
                {maskUrl(API_BASE_URL)}
              </p>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  HTTP Status
                </p>
                <p className="mt-0.5 font-mono">
                  {health.status ? health.status : '—'}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Environment
                </p>
                <p className="mt-0.5 font-mono">
                  {health.environment ?? '—'}
                </p>
              </div>
            </div>
            {health.error && (
              <div className="mt-2 rounded bg-red-900/30 px-2 py-1 text-red-300">
                {health.error}
              </div>
            )}
            <p className="mt-2 text-[10px] text-slate-500">
              Click badge to refresh • Auto-checks every 60s
            </p>
          </div>
          {/* Tooltip arrow */}
          <div
            className="absolute -bottom-1.5 left-4 h-3 w-3 rotate-45 border-b border-r border-slate-600/50 bg-slate-800"
            aria-hidden="true"
          />
        </div>
      )}
    </div>
  );
};

export default SystemDiagnostic;
