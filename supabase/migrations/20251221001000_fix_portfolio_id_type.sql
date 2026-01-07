-- ============================================================================
-- Migration: Fix Portfolio Explorer RPC - Correct ID Type
-- Created: 2024-12-21
-- Description: Fixes id type to BIGINT to match judgments table
-- ============================================================================
-- Drop and recreate with correct id type (BIGINT, not UUID)
DROP FUNCTION IF EXISTS public.portfolio_judgments_paginated CASCADE;
CREATE OR REPLACE FUNCTION public.portfolio_judgments_paginated(
        p_page INTEGER DEFAULT 1,
        p_limit INTEGER DEFAULT 50,
        p_min_score INTEGER DEFAULT NULL,
        p_status TEXT DEFAULT NULL,
        p_search TEXT DEFAULT NULL,
        p_county TEXT DEFAULT NULL
    ) RETURNS TABLE (
        id BIGINT,
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
SELECT j.id::BIGINT,
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
-- Also fix the view to use BIGINT for id
DROP VIEW IF EXISTS public.v_portfolio_judgments CASCADE;
CREATE VIEW public.v_portfolio_judgments AS
SELECT j.id,
    j.case_number,
    COALESCE(j.plaintiff_name, 'Unknown') AS plaintiff_name,
    COALESCE(j.defendant_name, 'Unknown') AS defendant_name,
    COALESCE(j.judgment_amount, 0) AS judgment_amount,
    COALESCE(j.collectability_score, 0) AS collectability_score,
    COALESCE(j.status, 'unknown') AS status,
    COALESCE(j.county, 'Unknown') AS county,
    j.judgment_date,
    j.entry_date,
    j.created_at,
    j.updated_at,
    CASE
        WHEN j.collectability_score >= 80 THEN 'A'
        WHEN j.collectability_score >= 50 THEN 'B'
        ELSE 'C'
    END AS tier,
    CASE
        WHEN j.collectability_score >= 80 THEN 'High Priority'
        WHEN j.collectability_score >= 50 THEN 'Medium Priority'
        ELSE 'Low Priority'
    END AS tier_label
FROM public.judgments j
ORDER BY j.judgment_amount DESC NULLS LAST;
COMMENT ON VIEW public.v_portfolio_judgments IS 'Portfolio Explorer view - all judgments with tier classification for grid display';
-- Permissions
GRANT SELECT ON public.v_portfolio_judgments TO authenticated;
GRANT SELECT ON public.v_portfolio_judgments TO service_role;
GRANT SELECT ON public.v_portfolio_judgments TO anon;
GRANT EXECUTE ON FUNCTION public.portfolio_judgments_paginated TO authenticated;
GRANT EXECUTE ON FUNCTION public.portfolio_judgments_paginated TO service_role;
