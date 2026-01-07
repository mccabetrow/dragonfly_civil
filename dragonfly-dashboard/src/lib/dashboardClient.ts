/**
 * Dashboard Data Client
 * ═══════════════════════════════════════════════════════════════════════════
 *
 * Dual-engine data fetching for dashboard widgets.
 * Supports three modes via VITE_DASHBOARD_SOURCE:
 *   - 'postgrest': Direct Supabase PostgREST (default, fastest)
 *   - 'api': Railway API fallback (bypasses PostgREST)
 *   - 'auto': Try PostgREST first, fallback to API on error
 *
 * This provides resilience during PGRST002 (schema cache stale) incidents.
 */

import { dashboardSource, apiBaseUrl, dragonflyApiKey } from '../config';
import { supabaseClient as supabase } from './supabaseClient';

// ═══════════════════════════════════════════════════════════════════════════
// TYPES
// ═══════════════════════════════════════════════════════════════════════════

/** Standard API response from Railway fallback endpoints */
export interface DashboardApiResponse<T> {
  success: boolean;
  data: T[];
  count: number;
  mode: 'direct_sql';
  timestamp: string;
}

/** Enforcement overview row */
export interface EnforcementOverviewRow {
  enforcement_stage: string;
  collectability_tier: string | null;
  case_count: number;
  total_judgment_amount: string;
}

/** Radar/metrics item */
export interface RadarItem {
  metric_name: string;
  value: number;
  amount?: string;
  period: string;
}

/** Collectability tier row */
export interface CollectabilityRow {
  tier: string;
  case_count: number;
  total_amount: string;
  percentage: number;
}

/** Judgment pipeline row */
export interface JudgmentPipelineRow {
  judgment_id: string;
  case_number: string;
  plaintiff_id: string;
  plaintiff_name: string;
  defendant_name: string;
  judgment_amount: string;
  enforcement_stage: string;
  enforcement_stage_updated_at: string | null;
  collectability_tier: string | null;
  collectability_age_days: number | null;
  last_enriched_at: string | null;
  last_enrichment_status: string | null;
}

/** Plaintiffs overview row */
export interface PlaintiffsOverviewRow {
  plaintiff_id: string;
  plaintiff_name: string;
  firm_name: string | null;
  status: string | null;
  total_judgment_amount: string;
  case_count: number;
}

// ═══════════════════════════════════════════════════════════════════════════
// INTERNAL HELPERS
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Fetch from Railway API fallback endpoint.
 */
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
    throw new Error(`Dashboard API error: ${response.status} ${response.statusText}`);
  }

  const result: DashboardApiResponse<T> = await response.json();
  
  if (!result.success) {
    throw new Error('Dashboard API returned success: false');
  }

  return result.data;
}

/**
 * Fetch from Supabase PostgREST.
 */
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
    // Check for PGRST002 specifically
    const errorCode = (error as { code?: string }).code;
    if (errorCode === 'PGRST002' || error.message?.includes('PGRST002')) {
      console.warn('[DashboardClient] PGRST002 detected - PostgREST schema cache stale');
    }
    throw error;
  }

  return (data as T[]) ?? [];
}

/**
 * Auto-fallback: try PostgREST first, then API on error.
 */
async function fetchWithFallback<T>(
  view: string,
  apiEndpoint: string,
  options?: {
    select?: string;
    order?: string;
    limit?: number;
    filters?: Record<string, unknown>;
    apiParams?: Record<string, string | number>;
  }
): Promise<{ data: T[]; source: 'postgrest' | 'api' }> {
  // Try PostgREST first
  try {
    const data = await fetchFromPostgREST<T>(view, options);
    return { data, source: 'postgrest' };
  } catch (error) {
    console.warn(
      `[DashboardClient] PostgREST failed for ${view}, falling back to API:`,
      error instanceof Error ? error.message : error
    );
    
    // Fallback to Railway API
    const data = await fetchFromApi<T>(apiEndpoint, options?.apiParams);
    return { data, source: 'api' };
  }
}

// ═══════════════════════════════════════════════════════════════════════════
// PUBLIC API
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Fetch enforcement overview data.
 * 
 * @returns Array of enforcement stats by stage and tier
 */
export async function fetchEnforcementOverview(): Promise<{
  data: EnforcementOverviewRow[];
  source: 'postgrest' | 'api';
}> {
  if (dashboardSource === 'api') {
    const data = await fetchFromApi<EnforcementOverviewRow>('overview');
    return { data, source: 'api' };
  }

  if (dashboardSource === 'postgrest') {
    const data = await fetchFromPostgREST<EnforcementOverviewRow>(
      'v_enforcement_overview',
      {
        select: 'enforcement_stage, collectability_tier, case_count, total_judgment_amount',
        order: 'enforcement_stage',
      }
    );
    return { data, source: 'postgrest' };
  }

  // Auto mode
  return fetchWithFallback<EnforcementOverviewRow>(
    'v_enforcement_overview',
    'overview',
    {
      select: 'enforcement_stage, collectability_tier, case_count, total_judgment_amount',
      order: 'enforcement_stage',
    }
  );
}

/**
 * Fetch radar/metrics data.
 * 
 * @returns Array of enforcement metrics
 */
export async function fetchRadarItems(): Promise<{
  data: RadarItem[];
  source: 'postgrest' | 'api';
}> {
  if (dashboardSource === 'api') {
    const data = await fetchFromApi<RadarItem>('radar');
    return { data, source: 'api' };
  }

  if (dashboardSource === 'postgrest') {
    const data = await fetchFromPostgREST<RadarItem>('v_metrics_enforcement');
    return { data, source: 'postgrest' };
  }

  // Auto mode
  return fetchWithFallback<RadarItem>(
    'v_metrics_enforcement',
    'radar'
  );
}

/**
 * Fetch collectability tier distribution.
 * 
 * @returns Array of tier stats
 */
export async function fetchCollectabilityScores(): Promise<{
  data: CollectabilityRow[];
  source: 'postgrest' | 'api';
}> {
  if (dashboardSource === 'api') {
    const data = await fetchFromApi<CollectabilityRow>('collectability');
    return { data, source: 'api' };
  }

  // PostgREST doesn't have a direct view for this, use API
  // Or compute from v_enforcement_overview aggregation
  const data = await fetchFromApi<CollectabilityRow>('collectability');
  return { data, source: 'api' };
}

/**
 * Fetch judgment pipeline data.
 * 
 * @param limit Maximum rows to return (default: 100)
 * @returns Array of judgment pipeline rows
 */
export async function fetchJudgmentPipeline(limit = 100): Promise<{
  data: JudgmentPipelineRow[];
  source: 'postgrest' | 'api';
}> {
  if (dashboardSource === 'api') {
    const data = await fetchFromApi<JudgmentPipelineRow>('pipeline', { limit });
    return { data, source: 'api' };
  }

  if (dashboardSource === 'postgrest') {
    const data = await fetchFromPostgREST<JudgmentPipelineRow>(
      'v_judgment_pipeline',
      {
        order: 'enforcement_stage_updated_at:desc',
        limit,
      }
    );
    return { data, source: 'postgrest' };
  }

  // Auto mode
  return fetchWithFallback<JudgmentPipelineRow>(
    'v_judgment_pipeline',
    'pipeline',
    {
      order: 'enforcement_stage_updated_at:desc',
      limit,
      apiParams: { limit },
    }
  );
}

/**
 * Fetch plaintiffs overview data.
 * 
 * @returns Array of plaintiff stats
 */
export async function fetchPlaintiffsOverview(): Promise<{
  data: PlaintiffsOverviewRow[];
  source: 'postgrest' | 'api';
}> {
  if (dashboardSource === 'api') {
    const data = await fetchFromApi<PlaintiffsOverviewRow>('plaintiffs');
    return { data, source: 'api' };
  }

  if (dashboardSource === 'postgrest') {
    const data = await fetchFromPostgREST<PlaintiffsOverviewRow>(
      'v_plaintiffs_overview',
      {
        order: 'total_judgment_amount:desc',
        limit: 1000,
      }
    );
    return { data, source: 'postgrest' };
  }

  // Auto mode
  return fetchWithFallback<PlaintiffsOverviewRow>(
    'v_plaintiffs_overview',
    'plaintiffs',
    {
      order: 'total_judgment_amount:desc',
      limit: 1000,
    }
  );
}

/**
 * Check health of the fallback API.
 * 
 * @returns Health status of Railway API fallback
 */
export async function checkFallbackHealth(): Promise<{
  is_healthy: boolean;
  latency_ms: number;
  mode: string;
  timestamp: string;
  error?: string;
}> {
  const response = await fetch(`${apiBaseUrl}/api/v1/dashboard/health`, {
    headers: {
      'X-DRAGONFLY-API-KEY': dragonflyApiKey,
      'Accept': 'application/json',
    },
  });

  if (!response.ok) {
    return {
      is_healthy: false,
      latency_ms: 0,
      mode: 'direct_sql',
      timestamp: new Date().toISOString(),
      error: `HTTP ${response.status}`,
    };
  }

  return response.json();
}

/**
 * Get the current dashboard source configuration.
 * 
 * @returns Current source setting
 */
export function getDashboardSource(): 'postgrest' | 'api' | 'auto' {
  return dashboardSource;
}
