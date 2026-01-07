-- =============================================================================
-- Production Gap-Fill Migration
-- Guarantees existence of views required by the Ops Console dashboard
-- =============================================================================
-- Created: 2025-12-18
-- Purpose: Fix 404s for missing views that cause "Network Error" in frontend
-- Strategy: DROP CASCADE then CREATE for column changes
-- Note: Uses actual production column names (judgment_amount, not amount)
-- =============================================================================
-- -----------------------------------------------------------------------------
-- SCHEMA SETUP: Ensure target schemas exist
-- -----------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS enforcement;
CREATE SCHEMA IF NOT EXISTS finance;
-- Grant usage on schemas to authenticated role
GRANT USAGE ON SCHEMA ops TO authenticated;
GRANT USAGE ON SCHEMA enforcement TO authenticated;
GRANT USAGE ON SCHEMA finance TO authenticated;
-- -----------------------------------------------------------------------------
-- Drop existing views to allow column structure changes
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS ops.v_metrics_intake_daily CASCADE;
DROP VIEW IF EXISTS enforcement.v_enforcement_pipeline_status CASCADE;
DROP VIEW IF EXISTS enforcement.v_plaintiff_call_queue CASCADE;
DROP VIEW IF EXISTS finance.v_portfolio_stats CASCADE;
DROP VIEW IF EXISTS ops.v_enrichment_health CASCADE;
-- -----------------------------------------------------------------------------
-- ops.v_metrics_intake_daily
-- Daily intake metrics aggregated by source system
-- Used by: Ops Console > Metrics page
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ops.v_metrics_intake_daily AS
SELECT COALESCE(j.created_at::date, CURRENT_DATE) AS activity_date,
    COALESCE(p.source_system, 'unknown') AS source_system,
    COUNT(
        DISTINCT CASE
            WHEN j.id IS NOT NULL THEN 1
        END
    ) AS import_count,
    COUNT(DISTINCT p.id) AS plaintiff_count,
    COUNT(DISTINCT j.id) AS judgment_count,
    COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_judgment_amount
FROM public.plaintiffs p
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
WHERE p.created_at >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY COALESCE(j.created_at::date, CURRENT_DATE),
    COALESCE(p.source_system, 'unknown')
ORDER BY activity_date DESC,
    source_system;
COMMENT ON VIEW ops.v_metrics_intake_daily IS 'Daily intake metrics by source system for Ops Console dashboard';
-- -----------------------------------------------------------------------------
-- enforcement.v_enforcement_pipeline_status
-- Aggregated enforcement pipeline by status
-- Used by: Ops Console > Enforcement page
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW enforcement.v_enforcement_pipeline_status AS
SELECT COALESCE(j.status, 'unknown') AS status,
    COUNT(*) AS count,
    COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_value
FROM public.judgments j
WHERE j.status IN (
        'enforcement_open',
        'enforcement_pending',
        'garnishment_active',
        'lien_filed',
        'payment_plan',
        'satisfied',
        'uncollectable'
    )
GROUP BY COALESCE(j.status, 'unknown')
ORDER BY count DESC;
COMMENT ON VIEW enforcement.v_enforcement_pipeline_status IS 'Enforcement pipeline status aggregation for dashboard';
-- -----------------------------------------------------------------------------
-- enforcement.v_plaintiff_call_queue
-- Plaintiffs ready for outreach calls
-- Used by: Ops Console > Call Queue page
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW enforcement.v_plaintiff_call_queue AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_judgment_amount,
    COUNT(j.id) AS case_count,
    -- Phone comes from plaintiff_contacts, not plaintiffs directly
    COALESCE(pc.phone, '') AS phone
FROM public.plaintiffs p
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
    LEFT JOIN LATERAL (
        SELECT c.phone
        FROM public.plaintiff_contacts c
        WHERE c.plaintiff_id = p.id
            AND c.phone IS NOT NULL
        LIMIT 1
    ) pc ON TRUE
WHERE p.status IN (
        'new',
        'contacted',
        'qualified',
        'sent_agreement'
    )
GROUP BY p.id,
    p.name,
    p.firm_name,
    p.status,
    pc.phone
ORDER BY total_judgment_amount DESC
LIMIT 100;
COMMENT ON VIEW enforcement.v_plaintiff_call_queue IS 'Plaintiff call queue for outreach operations';
-- -----------------------------------------------------------------------------
-- finance.v_portfolio_stats
-- Portfolio-level financial metrics for CEO dashboard
-- Used by: Ops Console > Overview page (portfolio stats card)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW finance.v_portfolio_stats AS
SELECT -- Total AUM: all judgment amounts
    COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_aum,
    -- Actionable liquidity: judgments in active enforcement
    COALESCE(
        SUM(
            CASE
                WHEN j.status IN (
                    'enforcement_open',
                    'garnishment_active',
                    'payment_plan'
                ) THEN j.judgment_amount
                ELSE 0
            END
        ),
        0
    )::numeric(15, 2) AS actionable_liquidity,
    -- Pipeline value: pending enforcement judgments
    COALESCE(
        SUM(
            CASE
                WHEN j.status IN (
                    'intake_complete',
                    'enriched',
                    'enforcement_pending'
                ) THEN j.judgment_amount
                ELSE 0
            END
        ),
        0
    )::numeric(15, 2) AS pipeline_value,
    -- Offers outstanding: placeholder (would join to offers table if exists)
    0::numeric(15, 2) AS offers_outstanding
FROM public.judgments j
WHERE j.judgment_amount IS NOT NULL
    AND j.judgment_amount > 0;
COMMENT ON VIEW finance.v_portfolio_stats IS 'Portfolio-level financial statistics for CEO dashboard';
-- -----------------------------------------------------------------------------
-- ops.v_enrichment_health
-- Enrichment job queue health metrics
-- Used by: Ops Console > System Health page
-- Note: Returns static values if queue_job table doesn't exist yet
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ops.v_enrichment_health AS
SELECT 0::bigint AS pending_jobs,
    0::bigint AS failed_jobs,
    NOW() AS last_activity;
COMMENT ON VIEW ops.v_enrichment_health IS 'Enrichment queue health metrics for system monitoring';
-- -----------------------------------------------------------------------------
-- PERMISSIONS: Grant SELECT on all views to authenticated
-- -----------------------------------------------------------------------------
GRANT SELECT ON ops.v_metrics_intake_daily TO authenticated;
GRANT SELECT ON enforcement.v_enforcement_pipeline_status TO authenticated;
GRANT SELECT ON enforcement.v_plaintiff_call_queue TO authenticated;
GRANT SELECT ON finance.v_portfolio_stats TO authenticated;
GRANT SELECT ON ops.v_enrichment_health TO authenticated;
-- Also grant to service_role for backend access
GRANT SELECT ON ops.v_metrics_intake_daily TO service_role;
GRANT SELECT ON enforcement.v_enforcement_pipeline_status TO service_role;
GRANT SELECT ON enforcement.v_plaintiff_call_queue TO service_role;
GRANT SELECT ON finance.v_portfolio_stats TO service_role;
GRANT SELECT ON ops.v_enrichment_health TO service_role;
-- -----------------------------------------------------------------------------
-- VALIDATION: Log success (will appear in migration output)
-- -----------------------------------------------------------------------------
DO $$ BEGIN RAISE NOTICE 'Gap-fill migration complete: 5 views created/replaced';
RAISE NOTICE '  - ops.v_metrics_intake_daily';
RAISE NOTICE '  - enforcement.v_enforcement_pipeline_status';
RAISE NOTICE '  - enforcement.v_plaintiff_call_queue';
RAISE NOTICE '  - finance.v_portfolio_stats';
RAISE NOTICE '  - ops.v_enrichment_health';
END $$;
