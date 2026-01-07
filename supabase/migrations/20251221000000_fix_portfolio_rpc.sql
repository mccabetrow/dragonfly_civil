-- ============================================================================
-- Migration: Fix Portfolio Explorer RPC Function
-- Created: 2024-12-21
-- Description: Fixes type mismatches in portfolio_judgments_paginated
-- ============================================================================
-- Drop and recreate with correct type casts
DROP FUNCTION IF EXISTS public.portfolio_judgments_paginated CASCADE;
CREATE OR REPLACE FUNCTION public.portfolio_judgments_paginated(
        p_page INTEGER DEFAULT 1,
        p_limit INTEGER DEFAULT 50,
        p_min_score INTEGER DEFAULT NULL,
        p_status TEXT DEFAULT NULL,
        p_search TEXT DEFAULT NULL,
        p_county TEXT DEFAULT NULL
    ) RETURNS TABLE (
        id UUID,
        case_number TEXT,
        plaintiff_name TEXT,
        defendant_name TEXT,
        judgment_amount NUMERIC,
        collectability_score INTEGER,
        status TEXT,
        county TEXT,
        judgment_date DATE,
        tier TEXT,
        tier_label TEXT,
        total_count BIGINT,
        total_value NUMERIC
    ) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_offset INTEGER;
v_total_count BIGINT;
v_total_value NUMERIC;
BEGIN -- Calculate offset
v_offset := (GREATEST(p_page, 1) - 1) * GREATEST(p_limit, 1);
-- Get total count and value for filtered results
SELECT COUNT(*),
    COALESCE(SUM(j.judgment_amount), 0) INTO v_total_count,
    v_total_value
FROM public.judgments j
WHERE (
        p_min_score IS NULL
        OR COALESCE(j.collectability_score, 0) >= p_min_score
    )
    AND (
        p_status IS NULL
        OR j.status = p_status
    )
    AND (
        p_county IS NULL
        OR j.county = p_county
    )
    AND (
        p_search IS NULL
        OR (
            j.case_number ILIKE '%' || p_search || '%'
            OR j.plaintiff_name ILIKE '%' || p_search || '%'
            OR j.defendant_name ILIKE '%' || p_search || '%'
        )
    );
-- Return paginated results with explicit type casts
RETURN QUERY
SELECT j.id::UUID,
    j.case_number::TEXT,
    COALESCE(j.plaintiff_name, 'Unknown')::TEXT,
    COALESCE(j.defendant_name, 'Unknown')::TEXT,
    COALESCE(j.judgment_amount, 0)::NUMERIC,
    COALESCE(j.collectability_score, 0)::INTEGER,
    COALESCE(j.status, 'unknown')::TEXT,
    COALESCE(j.county, 'Unknown')::TEXT,
    j.judgment_date::DATE,
    (
        CASE
            WHEN j.collectability_score >= 80 THEN 'A'
            WHEN j.collectability_score >= 50 THEN 'B'
            ELSE 'C'
        END
    )::TEXT,
    (
        CASE
            WHEN j.collectability_score >= 80 THEN 'High Priority'
            WHEN j.collectability_score >= 50 THEN 'Medium Priority'
            ELSE 'Low Priority'
        END
    )::TEXT,
    v_total_count::BIGINT,
    v_total_value::NUMERIC
FROM public.judgments j
WHERE (
        p_min_score IS NULL
        OR COALESCE(j.collectability_score, 0) >= p_min_score
    )
    AND (
        p_status IS NULL
        OR j.status = p_status
    )
    AND (
        p_county IS NULL
        OR j.county = p_county
    )
    AND (
        p_search IS NULL
        OR (
            j.case_number ILIKE '%' || p_search || '%'
            OR j.plaintiff_name ILIKE '%' || p_search || '%'
            OR j.defendant_name ILIKE '%' || p_search || '%'
        )
    )
ORDER BY j.judgment_amount DESC NULLS LAST
LIMIT p_limit OFFSET v_offset;
END;
$$;
COMMENT ON FUNCTION public.portfolio_judgments_paginated IS 'Paginated portfolio judgments with server-side filtering for Portfolio Explorer';
-- Re-grant permissions
GRANT EXECUTE ON FUNCTION public.portfolio_judgments_paginated TO authenticated;
GRANT EXECUTE ON FUNCTION public.portfolio_judgments_paginated TO service_role;
