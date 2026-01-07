/**
 * DataSourceContext - Circuit Breaker Pattern for Dashboard Data
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Implements a "sticky latch" circuit breaker:
 * - Default: Use PostgREST (fastest path)
 * - On failure (503/PGRST002): Switch to API fallback for 5 minutes
 * - After cooldown: Probe PostgREST to check if it's healthy again
 *
 * This prevents UI stutter from repeatedly retrying a broken endpoint.
 *
 * Usage:
 * ───────────────────────────────────────────────────────────────────────────
 * // Wrap your app:
 * <DataSourceProvider>
 *   <App />
 * </DataSourceProvider>
 *
 * // In data fetching code:
 * const { activeSource, reportFailure, isInFailover } = useDataSource();
 *
 * // In UI to show source indicator:
 * const { activeSource, isInFailover, failoverTimeRemaining } = useDataSource();
 * {isInFailover && <Badge color="orange">Failover Active</Badge>}
 * ───────────────────────────────────────────────────────────────────────────
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FC,
  type ReactNode,
} from 'react';
import { dashboardSource as configuredSource } from '../config';

// ═══════════════════════════════════════════════════════════════════════════
// CONSTANTS
// ═══════════════════════════════════════════════════════════════════════════

/** How long to stay in failover mode (5 minutes) */
const FAILOVER_DURATION_MS = 5 * 60 * 1000;

/** LocalStorage key for persisting failover state across page reloads */
const STORAGE_KEY = 'dragonfly:dataSourceFailover';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export type DataSourceType = 'postgrest' | 'api';

export interface DataSourceState {
  /** The currently active data source */
  activeSource: DataSourceType;
  /** Timestamp when failover will expire (null if not in failover) */
  failoverUntil: number | null;
  /** Whether we're currently in failover mode */
  isInFailover: boolean;
  /** Seconds remaining in failover (0 if not in failover) */
  failoverTimeRemaining: number;
  /** The source configured in env (for reference) */
  configuredSource: 'postgrest' | 'api' | 'auto';
}

export interface DataSourceActions {
  /**
   * Report a failure from PostgREST.
   * Triggers the circuit breaker - switches to API for FAILOVER_DURATION_MS.
   * 
   * @param errorCode - Optional error code (e.g., 'PGRST002', '503')
   */
  reportFailure: (errorCode?: string) => void;
  
  /**
   * Manually reset to PostgREST (for admin/debug purposes).
   */
  resetToPostgREST: () => void;
  
  /**
   * Force switch to API mode (for testing).
   */
  forceApiMode: () => void;
}

export type DataSourceContextValue = DataSourceState & DataSourceActions;

// ═══════════════════════════════════════════════════════════════════════════
// CONTEXT
// ═══════════════════════════════════════════════════════════════════════════

const DataSourceContext = createContext<DataSourceContextValue | null>(null);

// ═══════════════════════════════════════════════════════════════════════════
// STORAGE HELPERS
// ═══════════════════════════════════════════════════════════════════════════

interface StoredFailoverState {
  failoverUntil: number;
  timestamp: number;
}

function loadFailoverState(): number | null {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    
    const parsed: StoredFailoverState = JSON.parse(raw);
    
    // Check if failover is still valid
    if (Date.now() < parsed.failoverUntil) {
      return parsed.failoverUntil;
    }
    
    // Expired - clean up
    localStorage.removeItem(STORAGE_KEY);
    return null;
  } catch {
    return null;
  }
}

function saveFailoverState(failoverUntil: number): void {
  try {
    const state: StoredFailoverState = {
      failoverUntil,
      timestamp: Date.now(),
    };
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // Ignore storage errors
  }
}

function clearFailoverState(): void {
  try {
    localStorage.removeItem(STORAGE_KEY);
  } catch {
    // Ignore storage errors
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// PROVIDER
// ═══════════════════════════════════════════════════════════════════════════

interface DataSourceProviderProps {
  children: ReactNode;
  /** Override failover duration for testing (default: 5 minutes) */
  failoverDurationMs?: number;
}

export const DataSourceProvider: FC<DataSourceProviderProps> = ({
  children,
  failoverDurationMs = FAILOVER_DURATION_MS,
}) => {
  // ─────────────────────────────────────────────────────────────────────────
  // State
  // ─────────────────────────────────────────────────────────────────────────
  
  const [failoverUntil, setFailoverUntil] = useState<number | null>(() => {
    // Check for persisted failover state on mount
    return loadFailoverState();
  });
  
  const [timeRemaining, setTimeRemaining] = useState<number>(0);
  
  // Track if we've logged the failover activation (to avoid spam)
  const hasLoggedFailover = useRef(false);

  // ─────────────────────────────────────────────────────────────────────────
  // Derived State
  // ─────────────────────────────────────────────────────────────────────────
  
  const isInFailover = failoverUntil !== null && Date.now() < failoverUntil;
  
  // Determine active source based on config + failover state
  const activeSource: DataSourceType = useMemo(() => {
    // If configured to always use API, respect that
    if (configuredSource === 'api') return 'api';
    
    // If configured to always use PostgREST, respect that (no failover)
    if (configuredSource === 'postgrest') return 'postgrest';
    
    // Auto mode: use failover logic
    return isInFailover ? 'api' : 'postgrest';
  }, [isInFailover]);

  // ─────────────────────────────────────────────────────────────────────────
  // Actions
  // ─────────────────────────────────────────────────────────────────────────
  
  const reportFailure = useCallback((errorCode?: string) => {
    // Only activate failover in 'auto' mode
    if (configuredSource !== 'auto') {
      console.log(
        `[DataSource] Failure reported but source is locked to "${configuredSource}", not switching`
      );
      return;
    }
    
    // Don't re-activate if already in failover
    if (failoverUntil !== null && Date.now() < failoverUntil) {
      return;
    }
    
    const newFailoverUntil = Date.now() + failoverDurationMs;
    setFailoverUntil(newFailoverUntil);
    saveFailoverState(newFailoverUntil);
    
    if (!hasLoggedFailover.current) {
      console.warn(
        `⚠️ [DataSource] Failover activated for ${failoverDurationMs / 60000} minutes.`,
        errorCode ? `Error: ${errorCode}` : ''
      );
      hasLoggedFailover.current = true;
    }
  }, [failoverUntil, failoverDurationMs]);
  
  const resetToPostgREST = useCallback(() => {
    setFailoverUntil(null);
    clearFailoverState();
    hasLoggedFailover.current = false;
    console.log('[DataSource] Reset to PostgREST mode');
  }, []);
  
  const forceApiMode = useCallback(() => {
    const newFailoverUntil = Date.now() + failoverDurationMs;
    setFailoverUntil(newFailoverUntil);
    saveFailoverState(newFailoverUntil);
    console.log(`[DataSource] Forced to API mode for ${failoverDurationMs / 60000} minutes`);
  }, [failoverDurationMs]);

  // ─────────────────────────────────────────────────────────────────────────
  // Effects
  // ─────────────────────────────────────────────────────────────────────────
  
  // Update time remaining countdown
  useEffect(() => {
    if (!failoverUntil) {
      setTimeRemaining(0);
      return;
    }
    
    const updateRemaining = () => {
      const remaining = Math.max(0, failoverUntil - Date.now());
      setTimeRemaining(Math.ceil(remaining / 1000));
      
      // Auto-reset when failover expires
      if (remaining <= 0) {
        setFailoverUntil(null);
        clearFailoverState();
        hasLoggedFailover.current = false;
        console.log('[DataSource] Failover expired, resetting to PostgREST');
      }
    };
    
    // Update immediately
    updateRemaining();
    
    // Then update every second
    const interval = setInterval(updateRemaining, 1000);
    return () => clearInterval(interval);
  }, [failoverUntil]);

  // ─────────────────────────────────────────────────────────────────────────
  // Context Value
  // ─────────────────────────────────────────────────────────────────────────
  
  const value: DataSourceContextValue = useMemo(
    () => ({
      activeSource,
      failoverUntil,
      isInFailover,
      failoverTimeRemaining: timeRemaining,
      configuredSource,
      reportFailure,
      resetToPostgREST,
      forceApiMode,
    }),
    [
      activeSource,
      failoverUntil,
      isInFailover,
      timeRemaining,
      reportFailure,
      resetToPostgREST,
      forceApiMode,
    ]
  );

  return (
    <DataSourceContext.Provider value={value}>
      {children}
    </DataSourceContext.Provider>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// HOOKS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Hook to access the data source context.
 * 
 * @returns The full data source context (state + actions)
 * @throws Error if used outside of DataSourceProvider
 */
export function useDataSource(): DataSourceContextValue {
  const context = useContext(DataSourceContext);
  
  if (!context) {
    throw new Error(
      'useDataSource must be used within a DataSourceProvider. ' +
      'Wrap your app with <DataSourceProvider>.'
    );
  }
  
  return context;
}

/**
 * Lightweight hook for just reading the active source.
 * Useful for components that just need to display source status.
 * 
 * @returns Just the read-only state (no actions)
 */
export function useDataSourceStatus(): DataSourceState {
  const { activeSource, failoverUntil, isInFailover, failoverTimeRemaining, configuredSource } =
    useDataSource();
  
  return {
    activeSource,
    failoverUntil,
    isInFailover,
    failoverTimeRemaining,
    configuredSource,
  };
}

/**
 * Hook for checking if a specific error should trigger failover.
 * 
 * @param error - The error to check
 * @returns true if this error should trigger failover
 */
export function isFailoverError(error: unknown): boolean {
  if (!error) return false;
  
  // Check for HTTP status codes
  if (error instanceof Response && (error.status === 503 || error.status === 502)) {
    return true;
  }
  
  // Check for error objects with status
  if (typeof error === 'object' && error !== null) {
    const err = error as Record<string, unknown>;
    
    // Check status code
    if (err.status === 503 || err.status === 502) {
      return true;
    }
    
    // Check for PGRST002 in code
    if (err.code === 'PGRST002') {
      return true;
    }
    
    // Check for PGRST002 in message
    if (typeof err.message === 'string' && err.message.includes('PGRST002')) {
      return true;
    }
  }
  
  // Check for Error with message
  if (error instanceof Error) {
    if (error.message.includes('PGRST002')) return true;
    if (error.message.includes('503')) return true;
    if (error.message.includes('Service Unavailable')) return true;
  }
  
  return false;
}

// ═══════════════════════════════════════════════════════════════════════════
// EXPORTS
// ═══════════════════════════════════════════════════════════════════════════

export { DataSourceContext };
export default DataSourceProvider;
