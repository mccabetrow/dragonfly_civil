-- =============================================================================
-- 20251216000000_production_gap_fill.sql
-- =============================================================================
-- Purpose: Ensure all dashboard-critical views exist and are accessible.
-- This migration fills gaps that may cause 404 errors on the frontend.
--
-- Views created/verified:
--   1. public.v_metrics_intake_daily (ops metrics)
--   2. public.v_enforcement_pipeline_status (enforcement dashboard)
--   3. public.v_plaintiff_call_queue (call queue panel)
--   4. public.v_portfolio_stats (portfolio page)
--
-- All views are granted SELECT to authenticated role.
-- =============================================================================
-- migrate:up
BEGIN;
-- =============================================================================
-- 1. public.v_metrics_intake_daily
-- Daily intake funnel metrics for the executive dashboard
-- =============================================================================
CREATE OR REPLACE VIEW public.v_metrics_intake_daily AS WITH import_rows AS (
        SELECT date_trunc('day', timezone('utc', started_at))::date AS activity_date,
            COALESCE(NULLIF(LOWER(source_system), ''), 'unknown') AS source_system,
            COUNT(*) AS import_count
        FROM public.import_runs
        GROUP BY 1,
            2
    ),
    plaintiff_rows AS (
        SELECT date_trunc('day', timezone('utc', created_at))::date AS activity_date,
            COALESCE(NULLIF(LOWER(source_system), ''), 'unknown') AS source_system,
            COUNT(*) AS plaintiff_count
        FROM public.plaintiffs
        GROUP BY 1,
            2
    ),
    judgment_rows AS (
        SELECT date_trunc(
                'day',
                timezone(
                    'utc',
                    COALESCE(j.created_at, j.entry_date::timestamptz, now())
                )
            )::date AS activity_date,
            COALESCE(NULLIF(LOWER(p.source_system), ''), 'unknown') AS source_system,
            COUNT(*) AS judgment_count,
            COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount
        FROM public.judgments AS j
            LEFT JOIN public.plaintiffs AS p ON j.plaintiff_id = p.id
        GROUP BY 1,
            2
    ),
    combined_keys AS (
        SELECT activity_date,
            source_system
        FROM import_rows
        UNION
        SELECT activity_date,
            source_system
        FROM plaintiff_rows
        UNION
        SELECT activity_date,
            source_system
        FROM judgment_rows
    )
SELECT k.activity_date,
    k.source_system,
    COALESCE(j.total_judgment_amount, 0)::numeric AS total_judgment_amount,
    COALESCE(i.import_count, 0) AS import_count,
    COALESCE(pl.plaintiff_count, 0) AS plaintiff_count,
    COALESCE(j.judgment_count, 0) AS judgment_count
FROM combined_keys AS k
    LEFT JOIN import_rows AS i ON k.activity_date = i.activity_date
    AND k.source_system = i.source_system
    LEFT JOIN plaintiff_rows AS pl ON k.activity_date = pl.activity_date
    AND k.source_system = pl.source_system
    LEFT JOIN judgment_rows AS j ON k.activity_date = j.activity_date
    AND k.source_system = j.source_system
ORDER BY k.activity_date DESC,
    k.source_system ASC;
COMMENT ON VIEW public.v_metrics_intake_daily IS 'Daily intake funnel rollups by source system for the executive dashboard.';
-- =============================================================================
-- 2. public.v_enforcement_pipeline_status
-- Enforcement pipeline status for the dashboard
-- =============================================================================
DROP VIEW IF EXISTS public.v_enforcement_pipeline_status CASCADE;
CREATE OR REPLACE VIEW public.v_enforcement_pipeline_status AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.collectability_score,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    j.court,
    j.county,
    j.judgment_date,
    j.created_at,
    -- Compute offer strategy based on score and amount
    CASE
        WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        WHEN j.collectability_score >= 70
        AND j.judgment_amount >= 10000 THEN 'BUY_CANDIDATE'
        WHEN j.collectability_score >= 40
        OR j.judgment_amount >= 5000 THEN 'CONTINGENCY'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy,
    -- Compute tier from score
    CASE
        WHEN j.collectability_score >= 80 THEN 'A'
        WHEN j.collectability_score >= 50 THEN 'B'
        ELSE 'C'
    END AS collectability_tier,
    -- Days since judgment
    CASE
        WHEN j.judgment_date IS NOT NULL THEN (CURRENT_DATE - j.judgment_date)
        ELSE NULL
    END AS age_days
FROM public.judgments j
WHERE j.status IS NULL
    OR j.status != 'closed'
ORDER BY j.collectability_score DESC NULLS LAST,
    j.judgment_amount DESC;
COMMENT ON VIEW public.v_enforcement_pipeline_status IS 'Enforcement pipeline status with computed offer strategy and tier.';
-- =============================================================================
-- 3. public.v_plaintiff_call_queue (ensure exists)
-- Prioritized call queue for ops
-- =============================================================================
CREATE OR REPLACE VIEW public.v_plaintiff_call_queue AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    status_info.last_contacted_at,
    p.created_at,
    COALESCE(ov.total_judgment_amount, 0::numeric) AS total_judgment_amount,
    COALESCE(ov.case_count, 0) AS case_count
FROM public.plaintiffs p
    LEFT JOIN public.v_plaintiffs_overview ov ON p.id = ov.plaintiff_id
    LEFT JOIN LATERAL (
        SELECT MAX(psh.changed_at) AS last_contacted_at
        FROM public.plaintiff_status_history psh
        WHERE psh.plaintiff_id = p.id
            AND psh.status IN (
                'contacted',
                'qualified',
                'sent_agreement',
                'signed'
            )
    ) status_info ON TRUE
WHERE p.status IN ('new', 'contacted', 'qualified')
ORDER BY COALESCE(ov.total_judgment_amount, 0::numeric) DESC,
    COALESCE(status_info.last_contacted_at, p.created_at) ASC;
COMMENT ON VIEW public.v_plaintiff_call_queue IS 'Prioritized plaintiff call queue for ops console.';
-- =============================================================================
-- 4. public.v_portfolio_stats
-- Portfolio-level statistics for CEO Portfolio page
-- =============================================================================
-- First ensure enforcement.offers exists (may not on fresh installs)
CREATE TABLE IF NOT EXISTS enforcement.offers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id bigint REFERENCES public.judgments(id) ON DELETE CASCADE,
    offer_amount numeric(14, 2) NOT NULL,
    offer_type text NOT NULL CHECK (offer_type IN ('purchase', 'contingency')),
    status text NOT NULL DEFAULT 'offered' CHECK (
        status IN (
            'offered',
            'negotiation',
            'accepted',
            'rejected',
            'expired'
        )
    ),
    operator_notes text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE OR REPLACE VIEW public.v_portfolio_stats AS WITH base_stats AS (
        SELECT COUNT(*) AS total_judgments,
            COALESCE(SUM(judgment_amount), 0) AS total_aum,
            COUNT(*) FILTER (
                WHERE collectability_score > 40
            ) AS actionable_count,
            COALESCE(
                SUM(judgment_amount) FILTER (
                    WHERE collectability_score > 40
                ),
                0
            ) AS actionable_liquidity,
            COALESCE(
                SUM(judgment_amount) FILTER (
                    WHERE collectability_score >= 70
                        AND judgment_amount >= 10000
                ),
                0
            ) AS pipeline_value
        FROM public.judgments
        WHERE status IS NULL
            OR status != 'closed'
    ),
    tier_breakdown AS (
        SELECT CASE
                WHEN collectability_score >= 80 THEN 'A'
                WHEN collectability_score >= 50 THEN 'B'
                ELSE 'C'
            END AS tier,
            COUNT(*) AS tier_count,
            COALESCE(SUM(judgment_amount), 0) AS tier_amount
        FROM public.judgments
        WHERE status IS NULL
            OR status != 'closed'
        GROUP BY 1
    ),
    county_breakdown AS (
        SELECT COALESCE(county, 'Unknown') AS county,
            COUNT(*) AS county_count,
            COALESCE(SUM(judgment_amount), 0) AS county_amount
        FROM public.judgments
        WHERE status IS NULL
            OR status != 'closed'
        GROUP BY 1
        ORDER BY 3 DESC
        LIMIT 5
    ), offer_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE status = 'offered'
            ) AS offers_outstanding
        FROM enforcement.offers
    )
SELECT bs.total_judgments,
    bs.total_aum,
    bs.actionable_count,
    bs.actionable_liquidity,
    bs.pipeline_value,
    COALESCE(os.offers_outstanding, 0) AS offers_outstanding,
    (
        SELECT jsonb_agg(
                jsonb_build_object(
                    'tier',
                    tier,
                    'count',
                    tier_count,
                    'amount',
                    tier_amount
                )
            )
        FROM tier_breakdown
    ) AS tier_allocation,
    (
        SELECT jsonb_agg(
                jsonb_build_object(
                    'county',
                    county,
                    'count',
                    county_count,
                    'amount',
                    county_amount
                )
            )
        FROM county_breakdown
    ) AS top_counties
FROM base_stats bs
    LEFT JOIN offer_stats os ON TRUE;
COMMENT ON VIEW public.v_portfolio_stats IS 'Portfolio-level AUM and metrics for CEO Portfolio page.';
-- =============================================================================
-- 5. Grants to authenticated role
-- =============================================================================
GRANT SELECT ON public.v_metrics_intake_daily TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_enforcement_pipeline_status TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_portfolio_stats TO anon,
    authenticated,
    service_role;
-- Also ensure v_plaintiffs_overview exists (dependency for call queue)
CREATE OR REPLACE VIEW public.v_plaintiffs_overview AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount,
    COUNT(DISTINCT j.id) AS case_count
FROM public.plaintiffs p
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
GROUP BY p.id,
    p.name,
    p.firm_name,
    p.status;
GRANT SELECT ON public.v_plaintiffs_overview TO anon,
    authenticated,
    service_role;
-- =============================================================================
-- 6. Verification queries
-- =============================================================================
DO $$
DECLARE missing_views text [] := ARRAY []::text [];
BEGIN IF to_regclass('public.v_metrics_intake_daily') IS NULL THEN missing_views := array_append(missing_views, 'v_metrics_intake_daily');
END IF;
IF to_regclass('public.v_enforcement_pipeline_status') IS NULL THEN missing_views := array_append(missing_views, 'v_enforcement_pipeline_status');
END IF;
IF to_regclass('public.v_plaintiff_call_queue') IS NULL THEN missing_views := array_append(missing_views, 'v_plaintiff_call_queue');
END IF;
IF to_regclass('public.v_portfolio_stats') IS NULL THEN missing_views := array_append(missing_views, 'v_portfolio_stats');
END IF;
IF array_length(missing_views, 1) > 0 THEN RAISE EXCEPTION 'Migration verification failed: missing views: %',
missing_views;
END IF;
RAISE NOTICE '[20251216000000] All dashboard-critical views verified.';
END $$;
COMMIT;
-- migrate:down
BEGIN;
DROP VIEW IF EXISTS public.v_portfolio_stats CASCADE;
DROP VIEW IF EXISTS public.v_enforcement_pipeline_status CASCADE;
-- Note: v_metrics_intake_daily and v_plaintiff_call_queue may be needed by other migrations
-- Only drop if you're fully rolling back
COMMIT;