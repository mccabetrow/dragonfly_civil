-- ============================================================================
-- enforcement_schema_repair.sql
-- Idempotent repair script for all enforcement schema views
-- Run with: psql $DATABASE_URL -f enforcement_schema_repair.sql
-- ============================================================================
-- Created: 2025-01-XX (auto-generated for self-healing system)
-- Purpose: Restore enforcement views if drift is detected
--
-- Views covered:
--   - enforcement.v_radar
--   - enforcement.v_enforcement_pipeline_status  
--   - enforcement.v_plaintiff_call_queue
--   - enforcement.v_candidate_wage_garnishments
--   - enforcement.v_serve_jobs_active
--   - public.v_enforcement_overview
--   - public.v_enforcement_recent
-- ============================================================================
BEGIN;
-- Ensure enforcement schema exists
CREATE SCHEMA IF NOT EXISTS enforcement;
GRANT USAGE ON SCHEMA enforcement TO authenticated,
    service_role,
    anon;
-- ============================================================================
-- SECTION 1: enforcement.v_radar
-- Core radar view for enforcement opportunity identification
-- ============================================================================
DROP VIEW IF EXISTS enforcement.v_radar CASCADE;
CREATE OR REPLACE VIEW enforcement.v_radar AS
SELECT j.id,
    j.case_number,
    j.plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.court,
    j.county,
    COALESCE(j.judgment_date, j.entry_date) AS judgment_date,
    j.collectability_score,
    j.status,
    j.enforcement_stage,
    CASE
        WHEN j.collectability_score >= 70
        AND j.judgment_amount >= 10000 THEN 'BUY_CANDIDATE'
        WHEN j.collectability_score >= 40 THEN 'CONTINGENCY'
        WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy,
    j.created_at,
    j.updated_at
FROM public.judgments j
WHERE COALESCE(j.status, '') NOT IN ('SATISFIED', 'EXPIRED')
ORDER BY j.collectability_score DESC NULLS LAST,
    j.judgment_amount DESC;
COMMENT ON VIEW enforcement.v_radar IS 'Enforcement opportunity radar with offer strategy classification';
GRANT SELECT ON enforcement.v_radar TO authenticated,
    service_role,
    anon;
-- ============================================================================
-- SECTION 2: enforcement.v_enforcement_pipeline_status
-- Pipeline status aggregation for dashboard
-- ============================================================================
DROP VIEW IF EXISTS enforcement.v_enforcement_pipeline_status CASCADE;
CREATE OR REPLACE VIEW enforcement.v_enforcement_pipeline_status AS
SELECT j.enforcement_stage,
    COUNT(*) AS case_count,
    SUM(j.judgment_amount) AS total_amount,
    AVG(j.collectability_score) AS avg_score,
    MIN(j.created_at) AS oldest_case,
    MAX(j.updated_at) AS latest_activity
FROM public.judgments j
WHERE j.status NOT IN ('satisfied', 'dismissed', 'expired')
GROUP BY j.enforcement_stage
ORDER BY CASE
        j.enforcement_stage
        WHEN 'discovery' THEN 1
        WHEN 'asset_search' THEN 2
        WHEN 'levy_pending' THEN 3
        WHEN 'garnishment' THEN 4
        WHEN 'negotiation' THEN 5
        ELSE 99
    END;
COMMENT ON VIEW enforcement.v_enforcement_pipeline_status IS 'Enforcement pipeline status aggregation for dashboard';
GRANT SELECT ON enforcement.v_enforcement_pipeline_status TO authenticated,
    service_role,
    anon;
-- ============================================================================
-- SECTION 3: enforcement.v_plaintiff_call_queue
-- Plaintiff contact prioritization for outreach
-- ============================================================================
DROP VIEW IF EXISTS enforcement.v_plaintiff_call_queue CASCADE;
CREATE OR REPLACE VIEW enforcement.v_plaintiff_call_queue AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.tier,
    p.status,
    pc.phone,
    pc.email,
    COUNT(j.id) AS judgment_count,
    SUM(j.judgment_amount) AS total_balance,
    MAX(j.updated_at) AS last_activity,
    CASE
        WHEN p.tier = 'platinum' THEN 1
        WHEN p.tier = 'gold' THEN 2
        WHEN p.tier = 'silver' THEN 3
        ELSE 4
    END AS priority_rank
FROM public.plaintiffs p
    LEFT JOIN public.plaintiff_contacts pc ON pc.plaintiff_id = p.id
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
WHERE p.status IN ('active', 'pending_outreach', 'follow_up')
GROUP BY p.id,
    p.name,
    p.tier,
    p.status,
    pc.phone,
    pc.email
ORDER BY priority_rank,
    total_balance DESC NULLS LAST;
COMMENT ON VIEW enforcement.v_plaintiff_call_queue IS 'Plaintiff call queue prioritized by tier and balance';
GRANT SELECT ON enforcement.v_plaintiff_call_queue TO authenticated,
    service_role,
    anon;
-- ============================================================================
-- SECTION 4: enforcement.v_candidate_wage_garnishments
-- Wage garnishment candidates (CPLR 5231 enforcement)
-- ============================================================================
DROP VIEW IF EXISTS enforcement.v_candidate_wage_garnishments CASCADE;
CREATE OR REPLACE VIEW enforcement.v_candidate_wage_garnishments AS WITH judgment_intelligence AS (
        SELECT j.id AS judgment_id,
            j.plaintiff_id,
            j.case_number,
            j.defendant_name,
            j.judgment_amount,
            j.judgment_date,
            j.county,
            j.status,
            j.enforcement_stage,
            j.collectability_score,
            j.created_at,
            -- debtor_intelligence columns (disabled: table uses uuid, judgments uses bigint)
            NULL::text AS employer_name,
            NULL::text AS employer_address,
            NULL::text AS income_band,
            NULL::text AS intel_source,
            NULL::numeric AS intel_confidence,
            FALSE AS intel_verified,
            -- Get plaintiff name
            p.name AS plaintiff_name,
            p.tier AS plaintiff_tier
        FROM public.judgments j
            LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
        WHERE j.status IN ('unsatisfied', 'active', 'in_enforcement')
            AND j.judgment_amount >= 2000
    ),
    scored AS (
        SELECT ji.*,
            COALESCE(ji.collectability_score, 0) + CASE
                WHEN ji.intel_verified THEN 20
                ELSE 0
            END + CASE
                WHEN ji.employer_name IS NOT NULL THEN 15
                ELSE 0
            END + CASE
                WHEN ji.judgment_amount >= 10000 THEN 10
                ELSE 0
            END + CASE
                WHEN ji.judgment_date >= CURRENT_DATE - INTERVAL '2 years' THEN 5
                ELSE 0
            END AS priority_score
        FROM judgment_intelligence ji
        WHERE ji.employer_name IS NOT NULL
    )
SELECT s.plaintiff_id,
    s.case_number,
    s.defendant_name,
    s.employer_name,
    s.employer_address,
    s.judgment_amount AS balance,
    s.county AS jurisdiction,
    s.priority_score,
    s.judgment_id,
    s.plaintiff_name,
    s.plaintiff_tier,
    s.judgment_date,
    s.collectability_score,
    s.income_band,
    s.intel_source,
    s.intel_confidence,
    s.intel_verified,
    s.enforcement_stage,
    s.status,
    s.created_at
FROM scored s
ORDER BY s.priority_score DESC,
    s.judgment_amount DESC;
COMMENT ON VIEW enforcement.v_candidate_wage_garnishments IS 'Wage garnishment candidate view for CPLR 5231 enforcement';
GRANT SELECT ON enforcement.v_candidate_wage_garnishments TO authenticated,
    service_role,
    anon;
-- ============================================================================
-- SECTION 5: enforcement.v_serve_jobs_active
-- Active physical service jobs tracker
-- DISABLED: enforcement.serve_jobs table does not exist in current schema
-- ============================================================================
-- DROP VIEW IF EXISTS enforcement.v_serve_jobs_active CASCADE;
-- View creation skipped - underlying table does not exist
-- ============================================================================
-- SECTION 6: public.v_enforcement_overview
-- CEO Dashboard enforcement summary
-- ============================================================================
DROP VIEW IF EXISTS public.v_enforcement_overview CASCADE;
CREATE OR REPLACE VIEW public.v_enforcement_overview AS
SELECT j.enforcement_stage,
    COUNT(*) AS count,
    SUM(j.judgment_amount) AS total_value
FROM public.judgments j
WHERE j.status NOT IN ('satisfied', 'dismissed')
GROUP BY j.enforcement_stage;
COMMENT ON VIEW public.v_enforcement_overview IS 'Enforcement stage overview for CEO Dashboard';
GRANT SELECT ON public.v_enforcement_overview TO anon,
    authenticated,
    service_role;
-- ============================================================================
-- SECTION 7: public.v_enforcement_recent
-- Recent enforcement activity feed
-- ============================================================================
DROP VIEW IF EXISTS public.v_enforcement_recent CASCADE;
CREATE OR REPLACE VIEW public.v_enforcement_recent AS
SELECT j.id,
    j.case_number,
    j.defendant_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.updated_at,
    j.status
FROM public.judgments j
WHERE j.updated_at >= CURRENT_DATE - INTERVAL '7 days'
    AND j.enforcement_stage IS NOT NULL
ORDER BY j.updated_at DESC
LIMIT 50;
COMMENT ON VIEW public.v_enforcement_recent IS 'Recent enforcement activity for dashboard feed';
GRANT SELECT ON public.v_enforcement_recent TO anon,
    authenticated,
    service_role;
-- ============================================================================
-- VERIFICATION BLOCK
-- ============================================================================
DO $$
DECLARE missing_views TEXT [] := '{}';
BEGIN IF to_regclass('enforcement.v_radar') IS NULL THEN missing_views := array_append(missing_views, 'enforcement.v_radar');
END IF;
IF to_regclass('enforcement.v_enforcement_pipeline_status') IS NULL THEN missing_views := array_append(
    missing_views,
    'enforcement.v_enforcement_pipeline_status'
);
END IF;
IF to_regclass('enforcement.v_plaintiff_call_queue') IS NULL THEN missing_views := array_append(
    missing_views,
    'enforcement.v_plaintiff_call_queue'
);
END IF;
IF to_regclass('enforcement.v_candidate_wage_garnishments') IS NULL THEN missing_views := array_append(
    missing_views,
    'enforcement.v_candidate_wage_garnishments'
);
END IF;
IF to_regclass('public.v_enforcement_overview') IS NULL THEN missing_views := array_append(missing_views, 'public.v_enforcement_overview');
END IF;
IF to_regclass('public.v_enforcement_recent') IS NULL THEN missing_views := array_append(missing_views, 'public.v_enforcement_recent');
END IF;
IF array_length(missing_views, 1) > 0 THEN RAISE EXCEPTION 'ENFORCEMENT SCHEMA REPAIR FAILED - Missing views: %',
missing_views;
END IF;
RAISE NOTICE '✓ enforcement_schema_repair.sql completed successfully';
RAISE NOTICE '  All 7 enforcement views verified';
END $$;
COMMIT;