-- ============================================================================
-- Migration: Enforcement Radar Filter Support
-- Created: 2025-12-10
-- Purpose: Add RPC function for enforcement radar with optional filters
-- ============================================================================
-- This migration:
--   1. Creates enforcement_radar_filtered RPC with optional filter parameters
--   2. Supports min_score, only_employed, only_bank_assets filters
--   3. Returns judgment data with computed offer_strategy
-- ============================================================================
-- ============================================================================
-- 1. Create RPC Function for filtered enforcement radar
-- ============================================================================
CREATE OR REPLACE FUNCTION public.enforcement_radar_filtered(
        p_min_score INTEGER DEFAULT NULL,
        p_only_employed BOOLEAN DEFAULT FALSE,
        p_only_bank_assets BOOLEAN DEFAULT FALSE,
        p_min_amount NUMERIC DEFAULT NULL,
        p_strategy TEXT DEFAULT NULL,
        p_limit INTEGER DEFAULT 500
    ) RETURNS TABLE (
        id UUID,
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
    ) LANGUAGE plpgsql STABLE SECURITY DEFINER AS $$ BEGIN RETURN QUERY WITH judgment_intel AS (
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
            -- Join with debtor_intelligence to check for employer/bank
            COALESCE(di.employer_name IS NOT NULL, FALSE) AS has_employer,
            COALESCE(di.bank_name IS NOT NULL, FALSE) AS has_bank
        FROM public.judgments j
            LEFT JOIN public.debtor_intelligence di ON di.judgment_id = j.id
        WHERE -- Min score filter
            (
                p_min_score IS NULL
                OR j.collectability_score >= p_min_score
            ) -- Min amount filter
            AND (
                p_min_amount IS NULL
                OR j.judgment_amount >= p_min_amount
            ) -- Employed filter
            AND (
                NOT p_only_employed
                OR di.employer_name IS NOT NULL
            ) -- Bank assets filter
            AND (
                NOT p_only_bank_assets
                OR di.bank_name IS NOT NULL
            )
        ORDER BY j.collectability_score DESC NULLS LAST,
            j.judgment_amount DESC NULLS LAST
        LIMIT p_limit
    )
SELECT ji.id,
    ji.case_number,
    ji.plaintiff_name,
    ji.defendant_name,
    ji.judgment_amount,
    ji.collectability_score,
    ji.court,
    ji.county,
    ji.judgment_date,
    ji.created_at,
    ji.has_employer,
    ji.has_bank,
    -- Compute offer strategy based on score and amount
    CASE
        WHEN ji.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        WHEN ji.collectability_score >= 70
        AND ji.judgment_amount >= 5000 THEN 'BUY_CANDIDATE'
        WHEN ji.collectability_score >= 50 THEN 'CONTINGENCY'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy
FROM judgment_intel ji
WHERE -- Strategy filter (applied after computation)
    (
        p_strategy IS NULL
        OR p_strategy = 'ALL'
        OR CASE
            WHEN ji.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
            WHEN ji.collectability_score >= 70
            AND ji.judgment_amount >= 5000 THEN 'BUY_CANDIDATE'
            WHEN ji.collectability_score >= 50 THEN 'CONTINGENCY'
            ELSE 'LOW_PRIORITY'
        END = p_strategy
    );
END;
$$;
COMMENT ON FUNCTION public.enforcement_radar_filtered IS 'Returns filtered enforcement radar data with optional filters for min_score, only_employed, only_bank_assets. Powers the Enforcement Action Center dashboard.';
-- ============================================================================
-- 2. Grant Permissions
-- ============================================================================
GRANT EXECUTE ON FUNCTION public.enforcement_radar_filtered TO authenticated;
GRANT EXECUTE ON FUNCTION public.enforcement_radar_filtered TO service_role;
-- ============================================================================
-- 3. Verification query (for doctor checks)
-- ============================================================================
-- Test: SELECT COUNT(*) FROM public.enforcement_radar_filtered(80, TRUE, FALSE);