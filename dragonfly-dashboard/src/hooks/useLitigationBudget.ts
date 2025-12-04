/**
 * useLitigationBudget - Hook for CEO litigation budget dashboard
 * 
 * Fetches computed litigation budget from get_litigation_budget() RPC.
 * Includes skip tracing, litigation, marshal, and FOIL budget allocations.
 */
import { useCallback, useEffect, useState } from 'react';
import { IS_DEMO_MODE, supabaseClient } from '../lib/supabaseClient';
import {
  buildDemoLockedState,
  buildErrorMetricsState,
  buildInitialMetricsState,
  buildLoadingMetricsState,
  buildReadyMetricsState,
  type MetricsHookResult,
  type MetricsState,
} from './metricsState';
import { useOnRefresh } from '../context/RefreshContext';

// ============================================================================
// Types
// ============================================================================

export interface BudgetAllocations {
  skiptracing: number;
  litigation: number;
  marshal: number;
  foil: number;
  total_daily: number;
}

export interface RecoveryProjection {
  expected_rate: number;
  projected_30d: number;
}

export interface BacklogMetrics {
  stale_case_count: number;
  avg_days_stale: number;
}

export interface LitigationBudget {
  // Liquidity metrics
  totalLiquidationValue: number;
  tierAPrincipal: number;
  tierBPrincipal: number;
  actionableLiquidity: number;
  
  // Mode flag
  highAggressionMode: boolean;
  
  // Case counts
  tierACount: number;
  tierBCount: number;
  activeEnforcementCount: number;
  pendingFoilCount: number;
  
  // Budget allocations
  budgets: {
    skiptracing: number;
    litigation: number;
    marshal: number;
    foil: number;
    totalDaily: number;
  };
  
  // Recovery projections
  recovery: {
    expectedRate: number;
    projected30d: number;
  };
  
  // Backlog metrics
  backlog: {
    staleCaseCount: number;
    avgDaysStale: number;
  };
  
  // Metadata
  computedAt: string;
}

// Raw response shape from RPC
interface RawLitigationBudgetResponse {
  total_liquidation_value: number;
  tier_a_principal: number;
  tier_b_principal: number;
  actionable_liquidity: number;
  high_aggression_mode: boolean;
  tier_a_count: number;
  tier_b_count: number;
  active_enforcement_count: number;
  pending_foil_count: number;
  budgets: BudgetAllocations;
  recovery: RecoveryProjection;
  backlog: BacklogMetrics;
  computed_at: string;
}

// ============================================================================
// Constants
// ============================================================================

const BUDGET_LOCK_MESSAGE =
  'Litigation budget data is available only in the production enforcement console. This demo hides financial modeling data for safety.';

// ============================================================================
// Normalization
// ============================================================================

function normalizeBudget(raw: RawLitigationBudgetResponse): LitigationBudget {
  return {
    totalLiquidationValue: raw.total_liquidation_value ?? 0,
    tierAPrincipal: raw.tier_a_principal ?? 0,
    tierBPrincipal: raw.tier_b_principal ?? 0,
    actionableLiquidity: raw.actionable_liquidity ?? 0,
    highAggressionMode: raw.high_aggression_mode ?? false,
    tierACount: raw.tier_a_count ?? 0,
    tierBCount: raw.tier_b_count ?? 0,
    activeEnforcementCount: raw.active_enforcement_count ?? 0,
    pendingFoilCount: raw.pending_foil_count ?? 0,
    budgets: {
      skiptracing: raw.budgets?.skiptracing ?? 0,
      litigation: raw.budgets?.litigation ?? 0,
      marshal: raw.budgets?.marshal ?? 0,
      foil: raw.budgets?.foil ?? 0,
      totalDaily: raw.budgets?.total_daily ?? 0,
    },
    recovery: {
      expectedRate: raw.recovery?.expected_rate ?? 0,
      projected30d: raw.recovery?.projected_30d ?? 0,
    },
    backlog: {
      staleCaseCount: raw.backlog?.stale_case_count ?? 0,
      avgDaysStale: raw.backlog?.avg_days_stale ?? 0,
    },
    computedAt: raw.computed_at ?? new Date().toISOString(),
  };
}

// ============================================================================
// Hook: useLitigationBudget
// ============================================================================

export function useLitigationBudget(): MetricsHookResult<LitigationBudget> {
  const [snapshot, setSnapshot] = useState<MetricsState<LitigationBudget>>(() =>
    buildInitialMetricsState<LitigationBudget>()
  );

  const fetchBudget = useCallback(async () => {
    // Demo mode lock
    if (IS_DEMO_MODE) {
      setSnapshot(buildDemoLockedState<LitigationBudget>(BUDGET_LOCK_MESSAGE));
      return;
    }

    setSnapshot((prev) => buildLoadingMetricsState(prev));

    try {
      const { data, error } = await supabaseClient.rpc('get_litigation_budget');

      if (error) {
        console.error('[useLitigationBudget] RPC error:', error);
        setSnapshot(buildErrorMetricsState<LitigationBudget>(error.message));
        return;
      }

      if (!data) {
        console.warn('[useLitigationBudget] No data returned from RPC');
        setSnapshot(buildErrorMetricsState<LitigationBudget>('No budget data available'));
        return;
      }

      const normalized = normalizeBudget(data as RawLitigationBudgetResponse);
      setSnapshot(buildReadyMetricsState(normalized));
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error fetching litigation budget';
      console.error('[useLitigationBudget] Exception:', err);
      setSnapshot(buildErrorMetricsState<LitigationBudget>(message));
    }
  }, []);

  // Initial fetch
  useEffect(() => {
    fetchBudget();
  }, [fetchBudget]);

  // Subscribe to global refresh
  useOnRefresh(fetchBudget);

  return { ...snapshot, state: snapshot, refetch: fetchBudget };
}

// ============================================================================
// Hook: useApproveBudget
// ============================================================================

interface ApprovalResult {
  approvalId: string;
  approvedAt: string;
  status: 'approved' | 'error';
}

export function useApproveBudget() {
  const [isApproving, setIsApproving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const approveBudget = useCallback(async (
    adjustments?: Record<string, number>,
    notes?: string
  ): Promise<ApprovalResult | null> => {
    if (IS_DEMO_MODE) {
      console.log('[useApproveBudget] Demo mode - simulating approval');
      return {
        approvalId: 'demo-approval',
        approvedAt: new Date().toISOString(),
        status: 'approved',
      };
    }

    setIsApproving(true);
    setError(null);

    try {
      const { data, error: rpcError } = await supabaseClient.rpc('approve_daily_budget', {
        _adjustments: adjustments ?? null,
        _notes: notes ?? null,
      });

      if (rpcError) {
        console.error('[useApproveBudget] RPC error:', rpcError);
        setError(rpcError.message);
        return null;
      }

      return {
        approvalId: data?.approval_id ?? '',
        approvedAt: data?.approved_at ?? new Date().toISOString(),
        status: 'approved',
      };
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Unknown error approving budget';
      console.error('[useApproveBudget] Exception:', err);
      setError(message);
      return null;
    } finally {
      setIsApproving(false);
    }
  }, []);

  return { approveBudget, isApproving, error };
}

export default useLitigationBudget;
