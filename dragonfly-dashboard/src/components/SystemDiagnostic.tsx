import { type FC, useState, useEffect, useCallback, useRef } from 'react';
import { motion } from 'framer-motion';
import { apiClient, API_BASE_URL, type HealthCheckResult, type HealthErrorCategory } from '../lib/apiClient';
import { cn } from '../lib/design-tokens';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

type SystemStatus = 'healthy' | 'degraded' | 'critical' | 'loading';

interface HealthState {
  loading: boolean;
  ok: boolean;
  status?: number;
  environment?: string;
  error?: string;
  systemStatus: SystemStatus;
  category: HealthErrorCategory;
  endpoint?: string;
  checkedAt?: Date;
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

function formatCategory(category: HealthErrorCategory | undefined): string {
  switch (category) {
    case 'none':
      return 'None';
    case 'auth':
      return 'Auth (401/403)';
    case 'cors':
      return 'CORS / Browser blocked';
    case 'timeout':
      return 'Timeout';
    case 'network':
      return 'Network';
    case 'server':
      return 'Server 5xx';
    case 'unknown':
    default:
      return 'Unknown';
  }
}

function deriveSystemStatus(result: HealthCheckResult): SystemStatus {
  if (result.ok) {
    return 'healthy';
  }

  if (
    result.category === 'server' ||
    result.category === 'auth' ||
    result.category === 'network' ||
    result.category === 'timeout' ||
    result.category === 'cors'
  ) {
    return 'critical';
  }

  if (result.status >= 400) {
    return 'degraded';
  }

  return 'critical';
}

// ═══════════════════════════════════════════════════════════════════════════
// COMPONENT
// ═══════════════════════════════════════════════════════════════════════════

/**
 * SystemDiagnostic
 *
 * A small pill badge that shows live backend status:
 * - Green dot + "System Online (Prod/Dev)" when healthy (with subtle pulse)
 * - Amber dot + "System Degraded" when slow/degraded (slower pulse)
 * - Red dot + "Backend Disconnected" when unhealthy (strong pulse)
 * - Gray dot while loading
 *
 * Polls /api/health every 60 seconds. Hovering shows the masked API URL and HTTP status.
 */
const SystemDiagnostic: FC = () => {
  const [health, setHealth] = useState<HealthState>({
    loading: true,
    ok: false,
    systemStatus: 'loading',
    category: 'unknown',
  });
  const [showTooltip, setShowTooltip] = useState(false);
  const tooltipTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const checkHealth = useCallback(async () => {
    try {
      const result: HealthCheckResult = await apiClient.checkHealth();
      const systemStatus = deriveSystemStatus(result);
      setHealth({
        loading: false,
        ok: result.ok,
        status: result.status,
        environment: result.environment,
        error: result.ok ? undefined : (result.error ?? 'Health check failed'),
        systemStatus,
        category: result.category,
        endpoint: result.endpoint,
        checkedAt: new Date(result.checkedAt),
      });
    } catch (err) {
      setHealth({
        loading: false,
        ok: false,
        status: 0,
        environment: undefined,
        error: err instanceof Error ? err.message : 'Unknown error',
        systemStatus: 'critical',
        category: 'unknown',
        endpoint: undefined,
        checkedAt: new Date(),
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

  // Determine dot color and animation based on system status
  const getStatusConfig = () => {
    switch (health.systemStatus) {
      case 'healthy':
        return {
          dotColor: 'bg-emerald-400',
          glowColor: 'shadow-emerald-400/50',
          pulseVariant: 'subtle' as const,
          statusText: `System Online (${health.environment?.charAt(0).toUpperCase()}${health.environment?.slice(1).toLowerCase() ?? 'Unknown'})`,
          tooltipText: 'All systems operational',
        };
      case 'degraded':
        return {
          dotColor: 'bg-amber-400',
          glowColor: 'shadow-amber-400/50',
          pulseVariant: 'slow' as const,
          statusText: 'System Degraded',
          tooltipText: 'Performance may be impacted',
        };
      case 'critical':
        return {
          dotColor: 'bg-red-400',
          glowColor: 'shadow-red-400/50',
          pulseVariant: 'strong' as const,
          statusText: 'Backend Disconnected',
          tooltipText: 'Unable to connect to backend',
        };
      default:
        return {
          dotColor: 'bg-slate-400',
          glowColor: '',
          pulseVariant: 'none' as const,
          statusText: 'Checking…',
          tooltipText: 'Checking system health...',
        };
    }
  };

  const config = getStatusConfig();

  // Framer motion variants for the pulse animation
  const pulseVariants = {
    subtle: {
      opacity: [0.4, 0.8, 0.4],
      scale: [1, 1.2, 1],
      transition: {
        duration: 2,
        repeat: Infinity,
        ease: 'easeInOut' as const,
      },
    },
    slow: {
      opacity: [0.5, 1, 0.5],
      scale: [1, 1.4, 1],
      transition: {
        duration: 1.5,
        repeat: Infinity,
        ease: 'easeInOut' as const,
      },
    },
    strong: {
      opacity: [0.6, 1, 0.6],
      scale: [1, 1.6, 1],
      transition: {
        duration: 0.8,
        repeat: Infinity,
        ease: 'easeInOut' as const,
      },
    },
    none: {},
  };

  // Status text (for backwards compat)
  const statusText = config.statusText;

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
            : health.systemStatus === 'degraded'
              ? 'text-amber-300 hover:bg-slate-800 hover:border-amber-500/30'
              : 'text-slate-300 hover:bg-slate-800 hover:border-slate-600',
          'focus:outline-none focus:ring-2 focus:ring-indigo-500/50'
        )}
        aria-label={`System status: ${statusText}. Click to refresh.`}
      >
        {/* Animated Status dot with pulse */}
        <span className="relative flex h-2.5 w-2.5">
          {/* Outer pulse ring - animated with framer-motion */}
          {config.pulseVariant !== 'none' && (
            <motion.span
              className={cn(
                'absolute inset-0 rounded-full',
                config.dotColor,
              )}
              animate={pulseVariants[config.pulseVariant]}
            />
          )}
          {/* Inner solid dot */}
          <span
            className={cn(
              'relative inline-flex h-2.5 w-2.5 rounded-full shadow-lg',
              config.dotColor,
              config.glowColor
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
          {/* Status summary */}
          <div className="mb-2 pb-2 border-b border-slate-700">
            <p className="font-medium text-white">{config.tooltipText}</p>
          </div>
          <div className="space-y-2">
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                API Endpoint
              </p>
              <p className="mt-0.5 break-all font-mono text-slate-400">
                {maskUrl(API_BASE_URL)}
              </p>
              {health.endpoint && (
                <p className="mt-0.5 text-[10px] text-slate-500/80">
                  Path: <span className="font-mono text-slate-300">{health.endpoint}</span>
                </p>
              )}
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
                  Error Category
                </p>
                <p className="mt-0.5 font-mono text-slate-300">
                  {formatCategory(health.category)}
                </p>
              </div>
            </div>
            <div className="flex items-center justify-between">
              <div>
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Environment
                </p>
                <p className="mt-0.5 font-mono">
                  {health.environment ?? '—'}
                </p>
              </div>
              <div className="text-right">
                <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                  Last Checked
                </p>
                <p className="mt-0.5 font-mono">
                  {health.checkedAt ? health.checkedAt.toLocaleTimeString() : '—'}
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
