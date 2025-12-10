-- ============================================================================
-- Migration: Fix Enforcement Radar Filter - Remove debtor_intelligence join
-- Created: 2025-12-23
-- Purpose: Fix type mismatch between judgments.id (bigint) and debtor_intelligence.judgment_id (uuid)
-- ============================================================================
-- The debtor_intelligence table references core_judgments.id (uuid), not public.judgments.id (bigint)
-- For now, stub out has_employer/has_bank as false until schema is unified.
-- The filter params are kept for forward-compatibility.
-- ============================================================================
-- ============================================================================
-- 1. Drop and recreate the RPC function with correct types
-- ============================================================================
DROP FUNCTION IF EXISTS public.enforcement_radar_filtered(
    INTEGER,
    BOOLEAN,
    BOOLEAN,
    NUMERIC,
    TEXT,
    INTEGER
);
CREATE OR REPLACE FUNCTION public.enforcement_radar_filtered(
        p_min_score INTEGER DEFAULT NULL,
        p_only_employed BOOLEAN DEFAULT FALSE,
        p_only_bank_assets BOOLEAN DEFAULT FALSE,
        p_min_amount NUMERIC DEFAULT NULL,
        p_strategy TEXT DEFAULT NULL,
        p_limit INTEGER DEFAULT 500
    ) RETURNS TABLE (
        id BIGINT,
        case_number TEXT,
        plaintiff_name TEXT,
        defendant_name TEXT,
        judgment_amount NUMERIC,
        collectability_score INTEGER,
        court TEXT,
        county TEXT,
        judgment_date DATE,
        created_at TIMESTAMPTZ,
        has_employer BOOLEAN,
        has_bank BOOLEAN,
        offer_strategy TEXT
    ) LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$ BEGIN -- Note: has_employer and has_bank are stubbed as FALSE until we add
    -- employer/bank columns to public.judgments or unify with core_judgments.
    -- The filter params are currently no-ops but kept for forward-compatibility.
    RETURN QUERY
SELECT j.id,
    j.case_number,
    j.plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.collectability_score::INTEGER,
    j.court,
    j.county,
    j.judgment_date,
    j.created_at,
    FALSE AS has_employer,
    -- Stubbed until schema unified
    FALSE AS has_bank,
    -- Stubbed until schema unified
    -- Compute offer strategy based on score and amount
    CASE
        WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        WHEN j.collectability_score >= 70
        AND j.judgment_amount >= 5000 THEN 'BUY_CANDIDATE'
        WHEN j.collectability_score >= 50 THEN 'CONTINGENCY'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy
FROM public.judgments j
WHERE -- Exclude satisfied/expired
    COALESCE(j.status, '') NOT IN ('SATISFIED', 'EXPIRED') -- Min score filter
    AND (
        p_min_score IS NULL
        OR j.collectability_score >= p_min_score
    ) -- Min amount filter
    AND (
        p_min_amount IS NULL
        OR j.judgment_amount >= p_min_amount
    ) -- Strategy filter
    AND (
        p_strategy IS NULL
        OR p_strategy = 'ALL'
        OR (
            CASE
                WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
                WHEN j.collectability_score >= 70
                AND j.judgment_amount >= 5000 THEN 'BUY_CANDIDATE'
                WHEN j.collectability_score >= 50 THEN 'CONTINGENCY'
                ELSE 'LOW_PRIORITY'
            END = p_strategy
        )
    ) -- Note: p_only_employed and p_only_bank_assets are ignored until schema unified
ORDER BY j.collectability_score DESC NULLS LAST,
    j.judgment_amount DESC NULLS LAST
LIMIT p_limit;
END;
$$;
COMMENT ON FUNCTION public.enforcement_radar_filtered IS 'Returns filtered enforcement radar data. Currently min_score and strategy filters work; employed/bank filters are no-ops pending schema unification.';
-- ============================================================================
-- 2. Grant Permissions
-- ============================================================================
GRANT EXECUTE ON FUNCTION public.enforcement_radar_filtered TO authenticated;
GRANT EXECUTE ON FUNCTION public.enforcement_radar_filtered TO service_role;