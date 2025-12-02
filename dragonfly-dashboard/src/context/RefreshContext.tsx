/**
 * RefreshContext - Global refresh coordination for dashboard data
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Design Goals:
 * 1. Decouple refresh triggers (header button) from data fetchers (hooks)
 * 2. Allow any hook to "subscribe" to global refresh without prop drilling
 * 3. Track global refresh state for UI feedback (spinner on button)
 * 4. Keep the API minimal and type-safe
 *
 * Usage:
 * ───────────────────────────────────────────────────────────────────────────
 * // In AppShellNew (trigger side):
 * const { triggerRefresh, isRefreshing, refreshCount } = useRefreshBus();
 * <button onClick={triggerRefresh} disabled={isRefreshing}>Refresh</button>
 *
 * // In data hooks (subscriber side):
 * const { refreshCount } = useRefreshSignal();
 * useEffect(() => { refetch(); }, [refreshCount]);
 *
 * // Or use the helper:
 * useOnRefresh(() => fetchData());
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

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

/** State exposed by the refresh context */
export interface RefreshState {
  /** Incremented each time a global refresh is triggered */
  refreshCount: number;
  /** True while any registered fetcher is still loading */
  isRefreshing: boolean;
}

/** Methods to control the refresh bus (for trigger components like AppShellNew) */
export interface RefreshBus extends RefreshState {
  /** Trigger a global refresh - all subscribed hooks will refetch */
  triggerRefresh: () => void;
  /** Register a pending fetch (increments active count) */
  registerPending: () => void;
  /** Mark a fetch as complete (decrements active count) */
  completePending: () => void;
}

/** Minimal signal for subscriber hooks (read-only) */
export interface RefreshSignal {
  /** Current refresh count - hooks can use this in useEffect deps */
  refreshCount: number;
  /** Register this hook's loading state with the bus */
  registerPending: () => void;
  /** Signal this hook has finished loading */
  completePending: () => void;
}

// ═══════════════════════════════════════════════════════════════════════════
// CONTEXT
// ═══════════════════════════════════════════════════════════════════════════

const RefreshContext = createContext<RefreshBus | null>(null);

// ═══════════════════════════════════════════════════════════════════════════
// PROVIDER
// ═══════════════════════════════════════════════════════════════════════════

interface RefreshProviderProps {
  children: ReactNode;
}

export const RefreshProvider: FC<RefreshProviderProps> = ({ children }) => {
  const [refreshCount, setRefreshCount] = useState(0);
  const pendingCountRef = useRef(0);
  const [isRefreshing, setIsRefreshing] = useState(false);

  const triggerRefresh = useCallback(() => {
    setRefreshCount((c) => c + 1);
  }, []);

  const registerPending = useCallback(() => {
    pendingCountRef.current += 1;
    setIsRefreshing(true);
  }, []);

  const completePending = useCallback(() => {
    pendingCountRef.current = Math.max(0, pendingCountRef.current - 1);
    if (pendingCountRef.current === 0) {
      setIsRefreshing(false);
    }
  }, []);

  const value = useMemo<RefreshBus>(
    () => ({
      refreshCount,
      isRefreshing,
      triggerRefresh,
      registerPending,
      completePending,
    }),
    [refreshCount, isRefreshing, triggerRefresh, registerPending, completePending]
  );

  return (
    <RefreshContext.Provider value={value}>{children}</RefreshContext.Provider>
  );
};

// ═══════════════════════════════════════════════════════════════════════════
// HOOKS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * useRefreshBus - For components that TRIGGER refreshes (e.g., header button)
 * Returns the full bus with triggerRefresh() and isRefreshing state.
 */
export function useRefreshBus(): RefreshBus {
  const ctx = useContext(RefreshContext);
  if (!ctx) {
    throw new Error('useRefreshBus must be used within a RefreshProvider');
  }
  return ctx;
}

/**
 * useRefreshSignal - For hooks that SUBSCRIBE to refreshes
 * Returns the refreshCount for useEffect deps, plus pending tracking.
 */
export function useRefreshSignal(): RefreshSignal {
  const ctx = useContext(RefreshContext);
  if (!ctx) {
    // If no provider, return a no-op signal (graceful degradation)
    return {
      refreshCount: 0,
      registerPending: () => {},
      completePending: () => {},
    };
  }
  return {
    refreshCount: ctx.refreshCount,
    registerPending: ctx.registerPending,
    completePending: ctx.completePending,
  };
}

/**
 * useOnRefresh - Convenience hook that runs a callback when global refresh is triggered
 *
 * @param callback - Async function to run on refresh (e.g., refetch)
 * @param deps - Additional dependencies (callback is auto-included)
 *
 * @example
 * useOnRefresh(async () => {
 *   await fetchData();
 * });
 */
export function useOnRefresh(
  callback: () => void | Promise<void>,
  deps: React.DependencyList = []
): void {
  const { refreshCount, registerPending, completePending } = useRefreshSignal();
  const isInitialMount = useRef(true);

  // eslint-disable-next-line react-hooks/exhaustive-deps
  const stableCallback = useCallback(callback, deps);

  useEffect(() => {
    // Skip the initial mount - only respond to actual refresh triggers
    if (isInitialMount.current) {
      isInitialMount.current = false;
      return;
    }

    const run = async () => {
      registerPending();
      try {
        await stableCallback();
      } finally {
        completePending();
      }
    };

    void run();
  }, [refreshCount, stableCallback, registerPending, completePending]);
}

export default RefreshContext;
