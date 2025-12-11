-- Migration: Fix public.v_radar and ensure public.v_enforcement_pipeline_status exist
-- Issue: public.v_radar has wrong columns (category, count, total_amount) instead of detail columns
--        Dashboard queries public schema but needs enforcement schema column structure
--
-- Solution: Recreate public.v_radar as a detail view matching enforcement.v_radar
--           Ensure public.v_enforcement_pipeline_status exists for pipeline API
-- ============================================================================
-- 1. Fix public.v_radar - replace summary view with detail view
-- ============================================================================
DROP VIEW IF EXISTS public.v_radar CASCADE;
CREATE OR REPLACE VIEW public.v_radar AS
SELECT j.id,
    COALESCE(j.case_number, 'J-' || j.id::text) AS case_number,
    COALESCE(p.name, j.plaintiff_name, 'Unknown') AS plaintiff_name,
    COALESCE(j.defendant_name, 'Unknown Defendant') AS defendant_name,
    COALESCE(j.judgment_amount, 0)::numeric AS judgment_amount,
    j.court,
    j.county,
    j.judgment_date::date AS judgment_date,
    j.collectability_score,
    j.status,
    j.enforcement_stage,
    CASE
        WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        WHEN j.collectability_score >= 70
        AND j.judgment_amount >= 10000 THEN 'BUY_CANDIDATE'
        WHEN j.collectability_score >= 40
        OR j.judgment_amount >= 5000 THEN 'CONTINGENCY'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy,
    j.created_at,
    j.updated_at
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON j.plaintiff_id = p.id
WHERE j.status IS NULL
    OR j.status NOT IN ('closed', 'collected', 'satisfied');
COMMENT ON VIEW public.v_radar IS 'Enforcement radar view - detail records for dashboard portfolio display';
-- ============================================================================
-- 2. Ensure public.v_enforcement_pipeline_status exists
-- ============================================================================
DROP VIEW IF EXISTS public.v_enforcement_pipeline_status CASCADE;
CREATE OR REPLACE VIEW public.v_enforcement_pipeline_status AS
SELECT COALESCE(enforcement_stage, 'unassigned') AS enforcement_stage,
    COUNT(*) AS case_count,
    COALESCE(SUM(judgment_amount), 0)::numeric AS total_amount,
    ROUND(AVG(collectability_score)::numeric, 1) AS avg_score,
    MIN(created_at) AS oldest_case,
    MAX(updated_at) AS latest_activity
FROM public.judgments
WHERE status IS NULL
    OR status NOT IN ('closed', 'collected', 'satisfied')
GROUP BY COALESCE(enforcement_stage, 'unassigned')
ORDER BY CASE
        COALESCE(enforcement_stage, 'unassigned')
        WHEN 'discovery' THEN 1
        WHEN 'filed' THEN 2
        WHEN 'served' THEN 3
        WHEN 'judgment' THEN 4
        WHEN 'execution' THEN 5
        WHEN 'collection' THEN 6
        WHEN 'unassigned' THEN 99
        ELSE 50
    END;
COMMENT ON VIEW public.v_enforcement_pipeline_status IS 'Pipeline status by enforcement stage - aggregated statistics';
-- ============================================================================
-- 3. Grant permissions
-- ============================================================================
GRANT SELECT ON public.v_radar TO authenticated,
    anon,
    service_role;
GRANT SELECT ON public.v_enforcement_pipeline_status TO authenticated,
    anon,
    service_role;
-- ============================================================================
-- 4. Validation
-- ============================================================================
DO $$
DECLARE v_radar_cols int;
v_pipeline_cols int;
BEGIN -- Validate v_radar has correct columns
SELECT COUNT(*) INTO v_radar_cols
FROM information_schema.columns
WHERE table_schema = 'public'
    AND table_name = 'v_radar'
    AND column_name IN (
        'id',
        'case_number',
        'plaintiff_name',
        'defendant_name',
        'judgment_amount',
        'offer_strategy'
    );
IF v_radar_cols < 6 THEN RAISE EXCEPTION 'public.v_radar missing expected columns';
END IF;
-- Validate v_enforcement_pipeline_status has correct columns
SELECT COUNT(*) INTO v_pipeline_cols
FROM information_schema.columns
WHERE table_schema = 'public'
    AND table_name = 'v_enforcement_pipeline_status'
    AND column_name IN (
        'enforcement_stage',
        'case_count',
        'total_amount',
        'avg_score'
    );
IF v_pipeline_cols < 4 THEN RAISE EXCEPTION 'public.v_enforcement_pipeline_status missing expected columns';
END IF;
RAISE NOTICE 'Migration validated: public.v_radar has % columns, public.v_enforcement_pipeline_status has % columns',
v_radar_cols,
v_pipeline_cols;
END $$;