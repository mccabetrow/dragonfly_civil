-- ============================================================================
-- 0307_litigation_budget_engine.sql
-- Litigation Budget Engine: Financial modeling for daily enforcement spend
-- ============================================================================
-- NOTE (2025-12-03): This migration was applied manually in Supabase SQL Editor
-- against project ejiddanxtqcleyswqvkc as role `postgres`.
-- ============================================================================
--
-- PURPOSE:
--   Calculate how much Dad should approve daily for:
--   - Skip tracing
--   - Wage garnishments (income execution)
--   - Bank levies
--   - Marshal fees
--   - FOIL costs
--
-- BUSINESS RULES:
--   1. "Actionable Liquidity" = sum of Tier A + B principal amounts
--   2. If liquidity > $50k → enable "High Aggression Mode"
--   3. Budget Allocations:
--      - Skip tracing: 1% of liquidity
--      - Litigation (garnishments + levies): 2% of liquidity
--      - Marshals: fixed $35 per case in active enforcement
--      - FOIL: fixed $25 per pending FOIL request
--
-- INPUTS:
--   - core_judgments with tier (0-3)
--   - enforcement_actions for case counts
--   - foil_responses for pending FOIL count
--
-- ============================================================================
-- ============================================================================
-- TYPE: litigation_budget_result
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'litigation_budget_result'
) THEN CREATE TYPE public.litigation_budget_result AS (
    -- Liquidity metrics
    total_liquidation_value numeric(14, 2),
    tier_a_principal numeric(14, 2),
    tier_b_principal numeric(14, 2),
    actionable_liquidity numeric(14, 2),
    -- Mode flag
    high_aggression_mode boolean,
    -- Case counts
    tier_a_count int,
    tier_b_count int,
    active_enforcement_count int,
    pending_foil_count int,
    -- Budget allocations
    skiptracing_budget numeric(10, 2),
    litigation_budget numeric(10, 2),
    marshal_budget numeric(10, 2),
    foil_budget numeric(10, 2),
    total_daily_budget numeric(10, 2),
    -- Recovery projections
    expected_recovery_rate numeric(5, 2),
    projected_recovery_30d numeric(14, 2),
    -- Backlog metrics
    stale_case_count int,
    backlog_days_avg numeric(5, 1),
    -- Metadata
    computed_at timestamptz
);
END IF;
END $$;
COMMENT ON TYPE public.litigation_budget_result IS 'Return type for compute_litigation_budget() with full financial modeling output.';
-- ============================================================================
-- FUNCTION: compute_litigation_budget()
-- ============================================================================
-- Core budget computation logic. Called by the RPC wrapper.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.compute_litigation_budget() RETURNS public.litigation_budget_result LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE result public.litigation_budget_result;
-- Constants
SKIPTRACING_RATE constant numeric := 0.01;
-- 1% of liquidity
LITIGATION_RATE constant numeric := 0.02;
-- 2% of liquidity
MARSHAL_FEE_PER_CASE constant numeric := 35.00;
FOIL_COST_PER_REQUEST constant numeric := 25.00;
HIGH_AGGRESSION_THRESHOLD constant numeric := 50000.00;
DEFAULT_RECOVERY_RATE constant numeric := 0.15;
-- 15% baseline
STALE_THRESHOLD_DAYS constant int := 30;
BEGIN -- ========================================================================
-- 1. Calculate Total Liquidation Value (all active judgments)
-- ========================================================================
SELECT COALESCE(SUM(principal_amount), 0) INTO result.total_liquidation_value
FROM public.core_judgments
WHERE status IN ('unsatisfied', 'partially_satisfied')
    AND (
        judgment_expiry_date IS NULL
        OR judgment_expiry_date > CURRENT_DATE
    );
-- ========================================================================
-- 2. Calculate Tier A metrics (tier = 3, Strategic/Priority)
-- ========================================================================
SELECT COALESCE(SUM(principal_amount), 0),
    COUNT(*) INTO result.tier_a_principal,
    result.tier_a_count
FROM public.core_judgments
WHERE tier = 3
    AND status IN ('unsatisfied', 'partially_satisfied')
    AND (
        judgment_expiry_date IS NULL
        OR judgment_expiry_date > CURRENT_DATE
    );
-- ========================================================================
-- 3. Calculate Tier B metrics (tier = 2, Active Enforcement)
-- ========================================================================
SELECT COALESCE(SUM(principal_amount), 0),
    COUNT(*) INTO result.tier_b_principal,
    result.tier_b_count
FROM public.core_judgments
WHERE tier = 2
    AND status IN ('unsatisfied', 'partially_satisfied')
    AND (
        judgment_expiry_date IS NULL
        OR judgment_expiry_date > CURRENT_DATE
    );
-- ========================================================================
-- 4. Compute Actionable Liquidity
-- ========================================================================
result.actionable_liquidity := result.tier_a_principal + result.tier_b_principal;
-- ========================================================================
-- 5. Determine Aggression Mode
-- ========================================================================
result.high_aggression_mode := (
    result.actionable_liquidity > HIGH_AGGRESSION_THRESHOLD
);
-- ========================================================================
-- 6. Count active enforcement cases
-- ========================================================================
SELECT COUNT(DISTINCT judgment_id) INTO result.active_enforcement_count
FROM public.enforcement_actions
WHERE status IN ('planned', 'pending', 'served');
-- ========================================================================
-- 7. Count pending FOIL requests
-- ========================================================================
SELECT COUNT(*) INTO result.pending_foil_count
FROM public.foil_responses
WHERE status = 'pending';
-- ========================================================================
-- 8. Calculate Budget Allocations
-- ========================================================================
result.skiptracing_budget := ROUND(
    result.actionable_liquidity * SKIPTRACING_RATE,
    2
);
result.litigation_budget := ROUND(result.actionable_liquidity * LITIGATION_RATE, 2);
result.marshal_budget := ROUND(
    result.active_enforcement_count * MARSHAL_FEE_PER_CASE,
    2
);
result.foil_budget := ROUND(
    result.pending_foil_count * FOIL_COST_PER_REQUEST,
    2
);
-- Total daily budget
result.total_daily_budget := result.skiptracing_budget + result.litigation_budget + result.marshal_budget + result.foil_budget;
-- ========================================================================
-- 9. Recovery Projections
-- ========================================================================
-- Adjust recovery rate based on aggression mode
IF result.high_aggression_mode THEN result.expected_recovery_rate := DEFAULT_RECOVERY_RATE * 1.25;
-- 25% boost in aggression mode
ELSE result.expected_recovery_rate := DEFAULT_RECOVERY_RATE;
END IF;
-- 30-day projected recovery
result.projected_recovery_30d := ROUND(
    result.actionable_liquidity * result.expected_recovery_rate,
    2
);
-- ========================================================================
-- 10. Backlog Metrics (stale cases without recent activity)
-- ========================================================================
WITH stale_cases AS (
    SELECT cj.id,
        EXTRACT(
            DAY
            FROM (
                    CURRENT_TIMESTAMP - COALESCE(
                        (
                            SELECT MAX(ea.updated_at)
                            FROM public.enforcement_actions ea
                            WHERE ea.judgment_id = cj.id
                        ),
                        cj.created_at
                    )
                )
        ) as days_stale
    FROM public.core_judgments cj
    WHERE cj.tier IN (2, 3) -- Only track Tier A/B for backlog
        AND cj.status IN ('unsatisfied', 'partially_satisfied')
)
SELECT COUNT(*) FILTER (
        WHERE days_stale > STALE_THRESHOLD_DAYS
    ),
    COALESCE(
        AVG(days_stale) FILTER (
            WHERE days_stale > STALE_THRESHOLD_DAYS
        ),
        0
    ) INTO result.stale_case_count,
    result.backlog_days_avg
FROM stale_cases;
-- ========================================================================
-- 11. Set computation timestamp
-- ========================================================================
result.computed_at := CURRENT_TIMESTAMP;
RETURN result;
END;
$$;
COMMENT ON FUNCTION public.compute_litigation_budget() IS 'Core litigation budget computation. Calculates daily spend allocations for skip tracing, litigation, marshals, and FOIL based on actionable liquidity (Tier A + B principal).';
-- ============================================================================
-- RPC: get_litigation_budget()
-- ============================================================================
-- Public RPC endpoint that wraps compute_litigation_budget() and returns
-- a JSON object for frontend consumption.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.get_litigation_budget() RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE budget public.litigation_budget_result;
BEGIN -- Compute the budget
budget := public.compute_litigation_budget();
-- Return as JSON for easy frontend consumption
RETURN jsonb_build_object(
    -- Liquidity metrics
    'total_liquidation_value',
    budget.total_liquidation_value,
    'tier_a_principal',
    budget.tier_a_principal,
    'tier_b_principal',
    budget.tier_b_principal,
    'actionable_liquidity',
    budget.actionable_liquidity,
    -- Mode flag
    'high_aggression_mode',
    budget.high_aggression_mode,
    -- Case counts
    'tier_a_count',
    budget.tier_a_count,
    'tier_b_count',
    budget.tier_b_count,
    'active_enforcement_count',
    budget.active_enforcement_count,
    'pending_foil_count',
    budget.pending_foil_count,
    -- Budget allocations
    'budgets',
    jsonb_build_object(
        'skiptracing',
        budget.skiptracing_budget,
        'litigation',
        budget.litigation_budget,
        'marshal',
        budget.marshal_budget,
        'foil',
        budget.foil_budget,
        'total_daily',
        budget.total_daily_budget
    ),
    -- Recovery projections
    'recovery',
    jsonb_build_object(
        'expected_rate',
        budget.expected_recovery_rate,
        'projected_30d',
        budget.projected_recovery_30d
    ),
    -- Backlog metrics
    'backlog',
    jsonb_build_object(
        'stale_case_count',
        budget.stale_case_count,
        'avg_days_stale',
        budget.backlog_days_avg
    ),
    -- Metadata
    'computed_at',
    budget.computed_at
);
END;
$$;
COMMENT ON FUNCTION public.get_litigation_budget() IS 'RPC endpoint for CEO dashboard. Returns litigation budget allocations as JSON including skip tracing, litigation, marshal, and FOIL budgets based on Tier A + B liquidity.';
-- ============================================================================
-- VIEW: v_litigation_budget_summary
-- ============================================================================
-- Materialized view for quick dashboard access. Refreshes on demand.
-- ============================================================================
CREATE OR REPLACE VIEW public.v_litigation_budget_summary AS
SELECT (b).total_liquidation_value,
    (b).tier_a_principal,
    (b).tier_b_principal,
    (b).actionable_liquidity,
    (b).high_aggression_mode,
    (b).tier_a_count,
    (b).tier_b_count,
    (b).active_enforcement_count,
    (b).pending_foil_count,
    (b).skiptracing_budget,
    (b).litigation_budget,
    (b).marshal_budget,
    (b).foil_budget,
    (b).total_daily_budget,
    (b).expected_recovery_rate,
    (b).projected_recovery_30d,
    (b).stale_case_count,
    (b).backlog_days_avg,
    (b).computed_at
FROM (
        SELECT public.compute_litigation_budget() AS b
    ) sub;
COMMENT ON VIEW public.v_litigation_budget_summary IS 'Summary view of litigation budget. Query this for dashboard widgets.';
-- ============================================================================
-- GRANTS
-- ============================================================================
-- Allow authenticated users to call the RPC
GRANT EXECUTE ON FUNCTION public.compute_litigation_budget() TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_litigation_budget() TO authenticated;
GRANT SELECT ON public.v_litigation_budget_summary TO authenticated;
-- Service role needs full access for workers
GRANT EXECUTE ON FUNCTION public.compute_litigation_budget() TO service_role;
GRANT EXECUTE ON FUNCTION public.get_litigation_budget() TO service_role;
GRANT SELECT ON public.v_litigation_budget_summary TO service_role;
-- ============================================================================
-- AUDIT LOG: budget_approval_log
-- ============================================================================
-- Track when Dad approves or adjusts budgets (optional audit trail)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.budget_approval_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    approved_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP,
    approved_by uuid REFERENCES auth.users(id),
    budget_snapshot jsonb NOT NULL,
    adjustments jsonb,
    -- Any manual overrides
    notes text,
    created_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_budget_approval_log_approved_at ON public.budget_approval_log(approved_at DESC);
COMMENT ON TABLE public.budget_approval_log IS 'Audit log of budget approvals by leadership. Tracks snapshots and any manual adjustments.';
-- RLS for budget_approval_log
ALTER TABLE public.budget_approval_log ENABLE ROW LEVEL SECURITY;
-- Only admins and ceo role can insert/view
CREATE POLICY budget_approval_log_select ON public.budget_approval_log FOR
SELECT TO authenticated USING (
        public.dragonfly_has_any_role(ARRAY ['admin', 'ceo'])
    );
CREATE POLICY budget_approval_log_insert ON public.budget_approval_log FOR
INSERT TO authenticated WITH CHECK (
        public.dragonfly_has_any_role(ARRAY ['admin', 'ceo'])
    );
GRANT SELECT,
    INSERT ON public.budget_approval_log TO authenticated;
GRANT ALL ON public.budget_approval_log TO service_role;
-- ============================================================================
-- RPC: approve_daily_budget()
-- ============================================================================
-- Records budget approval and returns the approved budget
-- ============================================================================
CREATE OR REPLACE FUNCTION public.approve_daily_budget(
        _adjustments jsonb DEFAULT NULL,
        _notes text DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE current_budget jsonb;
new_id uuid;
BEGIN -- Check authorization
IF NOT public.dragonfly_has_any_role(ARRAY ['admin', 'ceo']) THEN RAISE EXCEPTION 'Unauthorized: budget approval requires admin or ceo role';
END IF;
-- Get current budget
current_budget := public.get_litigation_budget();
-- Log the approval
INSERT INTO public.budget_approval_log (
        approved_by,
        budget_snapshot,
        adjustments,
        notes
    )
VALUES (
        auth.uid(),
        current_budget,
        _adjustments,
        _notes
    )
RETURNING id INTO new_id;
-- Return confirmation with approved budget
RETURN jsonb_build_object(
    'approval_id',
    new_id,
    'approved_at',
    CURRENT_TIMESTAMP,
    'budget',
    current_budget,
    'adjustments',
    _adjustments,
    'status',
    'approved'
);
END;
$$;
COMMENT ON FUNCTION public.approve_daily_budget(jsonb, text) IS 'CEO/Admin function to approve the daily litigation budget. Creates audit trail entry.';
GRANT EXECUTE ON FUNCTION public.approve_daily_budget(jsonb, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.approve_daily_budget(jsonb, text) TO service_role;
