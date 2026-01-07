/**
 * useDashboardData - Circuit Breaker Aware Data Fetching Hook
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Generic data fetching hook that respects the circuit breaker state.
 *
 * Features:
 * - Automatic source selection based on circuit breaker state
 * - Seamless failover on 503/PGRST002 errors
 * - Reports failures to trigger circuit breaker
 * - Type-safe with generics
 * - Loading/error/data state management
 *
 * Usage:
 * ───────────────────────────────────────────────────────────────────────────
 * const { data, isLoading, error, source, refetch } = useDashboardData<MyType>({
 *   view: 'v_enforcement_overview',
 *   apiEndpoint: 'overview',
 *   select: 'enforcement_stage, case_count',
 * });
 * ───────────────────────────────────────────────────────────────────────────
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { supabaseClient as supabase } from '../lib/supabaseClient';
import { apiBaseUrl, dragonflyApiKey } from '../config';
import { useDataSource, isFailoverError, type DataSourceType } from '../context/DataSourceContext';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

export interface UseDashboardDataOptions<T> {
  /** Supabase view/table name for PostgREST path */
  view: string;
  /** Railway API endpoint (e.g., 'overview' -> /api/v1/dashboard/overview) */
  apiEndpoint: string;
  /** PostgREST select clause (default: '*') */
  select?: string;
  /** PostgREST order clause (e.g., 'created_at:desc') */
  order?: string;
  /** Limit number of rows */
  limit?: number;
  /** PostgREST filters (eq filters) */
  filters?: Record<string, unknown>;
  /** API query params */
  apiParams?: Record<string, string | number>;
  /** Skip initial fetch (for manual control) */
  skip?: boolean;
  /** Transform the raw data after fetching */
  transform?: (data: unknown[]) => T[];
  /** Dependencies that trigger refetch when changed */
  deps?: unknown[];
}

export interface UseDashboardDataResult<T> {
  /** The fetched data (null if not yet loaded) */
  data: T[] | null;
  /** Loading state */
  isLoading: boolean;
  /** Error message (null if no error) */
  error: string | null;
  /** Which source served this data */
  source: DataSourceType | null;
  /** Manually trigger a refetch */
  refetch: () => Promise<void>;
  /** Whether we're in circuit breaker failover mode */
  isInFailover: boolean;
}

/** API response shape from Railway backend */
interface DashboardApiResponse<T> {
  success: boolean;
  data: T[];
  count: number;
  mode: string;
  timestamp: string;
}

// ═══════════════════════════════════════════════════════════════════════════
// FETCH HELPERS
// ═══════════════════════════════════════════════════════════════════════════

async function fetchFromApi<T>(
  endpoint: string,
  params?: Record<string, string | number>
): Promise<T[]> {
  const url = new URL(`${apiBaseUrl}/api/v1/dashboard/${endpoint}`);
  
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      url.searchParams.set(key, String(value));
    });
  }

  const response = await fetch(url.toString(), {
    headers: {
      'X-DRAGONFLY-API-KEY': dragonflyApiKey,
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    throw new Error(`API error: ${response.status} ${response.statusText}`);
  }

  const result: DashboardApiResponse<T> = await response.json();
  
  if (!result.success) {
    throw new Error('API returned success: false');
  }

  return result.data;
}

async function fetchFromPostgREST<T>(
  view: string,
  options?: {
    select?: string;
    order?: string;
    limit?: number;
    filters?: Record<string, unknown>;
  }
): Promise<T[]> {
  let query = supabase.from(view).select(options?.select ?? '*');

  if (options?.order) {
    const [column, direction] = options.order.split(':');
    query = query.order(column, { ascending: direction !== 'desc' });
  }

  if (options?.limit) {
    query = query.limit(options.limit);
  }

  if (options?.filters) {
    Object.entries(options.filters).forEach(([key, value]) => {
      query = query.eq(key, value);
    });
  }

  const { data, error } = await query;

  if (error) {
    throw error;
  }

  return (data as T[]) ?? [];
}

// ═══════════════════════════════════════════════════════════════════════════
// HOOK
// ═══════════════════════════════════════════════════════════════════════════

export function useDashboardData<T = unknown>(
  options: UseDashboardDataOptions<T>
): UseDashboardDataResult<T> {
  const {
    view,
    apiEndpoint,
    select,
    order,
    limit,
    filters,
    apiParams,
    skip = false,
    transform,
    deps = [],
  } = options;

  // ─────────────────────────────────────────────────────────────────────────
  // Context & State
  // ─────────────────────────────────────────────────────────────────────────
  
  const { activeSource, reportFailure, isInFailover } = useDataSource();
  
  const [data, setData] = useState<T[] | null>(null);
  const [isLoading, setIsLoading] = useState(!skip);
  const [error, setError] = useState<string | null>(null);
  const [source, setSource] = useState<DataSourceType | null>(null);
  
  // Track mount state to prevent state updates after unmount
  const isMountedRef = useRef(true);
  
  // Track if we've already retried (to prevent infinite loops)
  const hasRetriedRef = useRef(false);

  // ─────────────────────────────────────────────────────────────────────────
  // Fetch Logic
  // ─────────────────────────────────────────────────────────────────────────
  
  const fetchData = useCallback(async (forceSource?: DataSourceType) => {
    if (!isMountedRef.current) return;
    
    setIsLoading(true);
    setError(null);
    
    const targetSource = forceSource ?? activeSource;
    
    try {
      let result: unknown[];
      
      if (targetSource === 'api') {
        // ─────────────────────────────────────────────────────────────────
        // API Path (Railway backend)
        // ─────────────────────────────────────────────────────────────────
        result = await fetchFromApi<unknown>(apiEndpoint, apiParams);
        
        if (isMountedRef.current) {
          setSource('api');
        }
      } else {
        // ─────────────────────────────────────────────────────────────────
        // PostgREST Path (Supabase)
        // ─────────────────────────────────────────────────────────────────
        try {
          result = await fetchFromPostgREST<unknown>(view, {
            select,
            order,
            limit,
            filters,
          });
          
          if (isMountedRef.current) {
            setSource('postgrest');
            hasRetriedRef.current = false; // Reset retry flag on success
          }
        } catch (postgrestError) {
          // ───────────────────────────────────────────────────────────────
          // Check if this is a failover-worthy error
          // ───────────────────────────────────────────────────────────────
          if (isFailoverError(postgrestError)) {
            console.warn(
              `[useDashboardData] PostgREST failed for ${view}, triggering failover`,
              postgrestError
            );
            
            // Report failure to circuit breaker
            const errorCode = (postgrestError as { code?: string }).code ?? '503';
            reportFailure(errorCode);
            
            // Retry immediately with API if we haven't already
            if (!hasRetriedRef.current) {
              hasRetriedRef.current = true;
              
              console.log(`[useDashboardData] Retrying ${apiEndpoint} via API...`);
              result = await fetchFromApi<unknown>(apiEndpoint, apiParams);
              
              if (isMountedRef.current) {
                setSource('api');
              }
            } else {
              throw postgrestError; // Re-throw if retry also failed
            }
          } else {
            // Non-failover error (e.g., 404, bad query)
            throw postgrestError;
          }
        }
      }
      
      // ─────────────────────────────────────────────────────────────────────
      // Apply transform and set data
      // ─────────────────────────────────────────────────────────────────────
      if (isMountedRef.current) {
        const finalData = transform ? transform(result) : (result as T[]);
        setData(finalData);
        setIsLoading(false);
      }
    } catch (err) {
      if (isMountedRef.current) {
        const message = err instanceof Error ? err.message : 'Unknown error';
        console.error(`[useDashboardData] Fetch failed for ${view}:`, message);
        setError(message);
        setIsLoading(false);
      }
    }
  }, [
    activeSource,
    view,
    apiEndpoint,
    select,
    order,
    limit,
    filters,
    apiParams,
    transform,
    reportFailure,
  ]);

  // ─────────────────────────────────────────────────────────────────────────
  // Effects
  // ─────────────────────────────────────────────────────────────────────────
  
  // Track mount state
  useEffect(() => {
    isMountedRef.current = true;
    return () => {
      isMountedRef.current = false;
    };
  }, []);
  
  // Initial fetch and refetch on deps change
  useEffect(() => {
    if (!skip) {
      hasRetriedRef.current = false; // Reset on new fetch
      fetchData();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [skip, activeSource, ...deps]);

  // ─────────────────────────────────────────────────────────────────────────
  // Return
  // ─────────────────────────────────────────────────────────────────────────
  
  return {
    data,
    isLoading,
    error,
    source,
    refetch: fetchData,
    isInFailover,
  };
}

// ═══════════════════════════════════════════════════════════════════════════
// CONVENIENCE HOOKS FOR SPECIFIC ENDPOINTS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Fetch enforcement overview data with circuit breaker.
 */
export function useEnforcementOverview() {
  return useDashboardData({
    view: 'v_enforcement_overview',
    apiEndpoint: 'overview',
    select: 'enforcement_stage, collectability_tier, case_count, total_judgment_amount',
    order: 'enforcement_stage',
  });
}

/**
 * Fetch radar/metrics data with circuit breaker.
 */
export function useRadarMetrics() {
  return useDashboardData({
    view: 'v_metrics_enforcement',
    apiEndpoint: 'radar',
  });
}

/**
 * Fetch collectability snapshot with circuit breaker.
 */
export function useCollectabilityData() {
  return useDashboardData({
    view: 'v_collectability_tiers',
    apiEndpoint: 'collectability',
    order: 'tier',
  });
}

/**
 * Fetch judgment pipeline with circuit breaker.
 */
export function useJudgmentPipeline(options?: { limit?: number }) {
  return useDashboardData({
    view: 'v_judgment_pipeline',
    apiEndpoint: 'pipeline',
    limit: options?.limit ?? 100,
    order: 'enforcement_stage_updated_at:desc',
    apiParams: options?.limit ? { limit: options.limit } : undefined,
    deps: [options?.limit],
  });
}

/**
 * Fetch plaintiffs overview with circuit breaker.
 */
export function usePlaintiffsOverview() {
  return useDashboardData({
    view: 'v_plaintiffs_overview',
    apiEndpoint: 'plaintiffs',
    order: 'plaintiff_name',
  });
}

export default useDashboardData;
