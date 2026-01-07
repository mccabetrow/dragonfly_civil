-- Migration: Fix public.v_enforcement_overview for prod Overview page
-- =============================================================================
-- ISSUE: The Overview page in prod shows "Data unavailable - Unable to load
--        enforcement overview" because:
--        - Prod view has columns: enforcement_stage, count, total_value
--        - Frontend expects: enforcement_stage, collectability_tier, case_count, total_judgment_amount
--
-- SOLUTION: Recreate the view with the correct column names and structure
--           matching the frontend query in useEnforcementOverview.ts
--
-- Frontend query:
--   .from('v_enforcement_overview')
--   .select('enforcement_stage, collectability_tier, case_count, total_judgment_amount')
--   .order('enforcement_stage', { ascending: true, nullsFirst: false })
--   .order('collectability_tier', { ascending: true, nullsFirst: true })
-- =============================================================================
-- Drop and recreate the view with correct columns
DROP VIEW IF EXISTS public.v_enforcement_overview CASCADE;
CREATE OR REPLACE VIEW public.v_enforcement_overview AS WITH collectability_tiers AS (
        -- Derive collectability tier from score
        SELECT j.id,
            j.case_number,
            j.enforcement_stage,
            j.judgment_amount,
            j.collectability_score,
            CASE
                WHEN j.collectability_score IS NULL THEN NULL
                WHEN j.collectability_score >= 70 THEN 'high'
                WHEN j.collectability_score >= 40 THEN 'medium'
                ELSE 'low'
            END AS collectability_tier
        FROM public.judgments j
        WHERE j.status IS NULL
            OR j.status NOT IN ('closed', 'collected', 'satisfied')
    )
SELECT COALESCE(
        NULLIF(LOWER(TRIM(ct.enforcement_stage)), ''),
        'unassigned'
    ) AS enforcement_stage,
    ct.collectability_tier,
    COUNT(*) AS case_count,
    COALESCE(SUM(ct.judgment_amount), 0)::numeric AS total_judgment_amount
FROM collectability_tiers ct
GROUP BY COALESCE(
        NULLIF(LOWER(TRIM(ct.enforcement_stage)), ''),
        'unassigned'
    ),
    ct.collectability_tier
ORDER BY enforcement_stage ASC,
    collectability_tier ASC NULLS FIRST;
COMMENT ON VIEW public.v_enforcement_overview IS 'Enforcement overview aggregated by stage and collectability tier. Consumed by the dashboard Overview page via useEnforcementOverview hook.';
-- Grant permissions
GRANT SELECT ON public.v_enforcement_overview TO anon,
    authenticated,
    service_role;
-- =============================================================================
-- Validation
-- =============================================================================
DO $$
DECLARE v_cols text [];
v_expected text [] := ARRAY ['enforcement_stage', 'collectability_tier', 'case_count', 'total_judgment_amount'];
v_missing text [];
BEGIN -- Get actual columns
SELECT ARRAY_AGG(
        column_name
        ORDER BY ordinal_position
    ) INTO v_cols
FROM information_schema.columns
WHERE table_schema = 'public'
    AND table_name = 'v_enforcement_overview';
-- Check for missing expected columns
SELECT ARRAY_AGG(exp) INTO v_missing
FROM UNNEST(v_expected) AS exp
WHERE exp NOT IN (
        SELECT UNNEST(v_cols)
    );
IF v_missing IS NOT NULL
AND ARRAY_LENGTH(v_missing, 1) > 0 THEN RAISE EXCEPTION 'public.v_enforcement_overview missing columns: %',
v_missing;
END IF;
RAISE NOTICE 'Migration validated: public.v_enforcement_overview has columns: %',
v_cols;
END $$;
