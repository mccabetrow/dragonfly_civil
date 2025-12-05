-- Migration: Create v_daily_health view for daily health broadcasts
-- This view aggregates key metrics for the Dragonfly Engine daily health check
CREATE OR REPLACE VIEW public.v_daily_health AS
SELECT CURRENT_DATE AS run_date,
    -- Tier A: High-value judgments ready for enforcement
    COALESCE(
        (
            SELECT COUNT(*)
            FROM public.judgments j
            WHERE j.judgment_amount >= 10000
                AND j.created_at >= CURRENT_DATE - INTERVAL '30 days'
        ),
        0
    ) AS tier_a_count,
    -- Stalled cases: Enforcement cases with no activity in 14 days
    COALESCE(
        (
            SELECT COUNT(*)
            FROM public.enforcement_cases ec
            WHERE ec.updated_at < CURRENT_DATE - INTERVAL '14 days'
                AND ec.status NOT IN ('closed', 'collected', 'abandoned')
        ),
        0
    ) AS stalled_cases,
    -- Today's collections: Count of completed enforcement actions today
    COALESCE(
        (
            SELECT COUNT(*)
            FROM public.enforcement_actions ea
            WHERE ea.status = 'completed'
                AND ea.created_at::date = CURRENT_DATE
        ),
        0
    )::numeric AS today_collections_amount,
    -- Pending signatures: Actions requiring attorney signature that are pending
    COALESCE(
        (
            SELECT COUNT(*)
            FROM public.enforcement_actions ea
            WHERE ea.status = 'pending'
                AND ea.requires_attorney_signature = true
        ),
        0
    ) AS pending_signatures,
    -- Budget approvals today: Actions approved today
    COALESCE(
        (
            SELECT COUNT(*)
            FROM public.enforcement_actions ea
            WHERE ea.status IN ('completed', 'served')
                AND ea.created_at::date = CURRENT_DATE
        ),
        0
    ) AS budget_approvals_today;

-- Grant access
GRANT SELECT ON public.v_daily_health TO anon, authenticated, service_role;

COMMENT ON VIEW public.v_daily_health IS 'Daily health metrics for the Dragonfly Engine dashboard and Discord broadcasts';
