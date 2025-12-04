-- 20251205100000_enforcement_radar.sql
-- Dragonfly Enforcement Radar + Enrichment Health + Offer Strategy
-- Ensure schemas exist
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS enforcement;
-- ============================================================================
-- 1. Add missing columns to public.judgments for radar functionality
-- ============================================================================
-- collectability_score: 0-100 score from enrichment worker
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS collectability_score NUMERIC(5, 2);
COMMENT ON COLUMN public.judgments.collectability_score IS 'Collectability score 0-100 based on enrichment data (employed, homeowner, bank_account, age)';
-- court: extracted from source_file or separate field
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS court TEXT;
-- county: jurisdiction county
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS county TEXT;
-- judgment_date: actual judgment date (entry_date may be filing date)
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS judgment_date DATE;
-- ============================================================================
-- 2. Enrichment Health View (ops.v_enrichment_health)
-- Quick check to ensure the background worker isn't dead.
-- Note: Only created if ops.job_queue exists
-- ============================================================================
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
) THEN EXECUTE $view$
CREATE OR REPLACE VIEW ops.v_enrichment_health AS
SELECT count(*) FILTER (
        WHERE status = 'pending'
    ) AS pending_jobs,
    count(*) FILTER (
        WHERE status = 'processing'
    ) AS processing_jobs,
    count(*) FILTER (
        WHERE status = 'failed'
    ) AS failed_jobs,
    count(*) FILTER (
        WHERE status = 'completed'
    ) AS completed_jobs,
    max(created_at) AS last_job_created_at,
    max(updated_at) AS last_job_updated_at,
    now() - max(updated_at) AS time_since_last_activity
FROM ops.job_queue $view$;
GRANT SELECT ON ops.v_enrichment_health TO authenticated,
    service_role;
END IF;
END $$;
-- ============================================================================
-- 3. Enforcement Radar View (enforcement.v_radar)
-- The daily cockpit for enforcement. Filters out dead stuff and bakes in offer strategy.
-- ============================================================================
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
COMMENT ON VIEW enforcement.v_radar IS 'Daily enforcement cockpit view with offer strategy based on collectability score and amount';
-- ============================================================================
-- 4. Grants
-- ============================================================================
GRANT USAGE ON SCHEMA ops TO authenticated,
    service_role;
GRANT USAGE ON SCHEMA enforcement TO authenticated,
    service_role;
GRANT SELECT ON enforcement.v_radar TO authenticated,
    service_role;
-- ============================================================================
-- 5. Index for radar query performance
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_judgments_collectability_score ON public.judgments(collectability_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_judgments_radar_composite ON public.judgments(
    status,
    collectability_score DESC NULLS LAST,
    judgment_amount DESC
)
WHERE COALESCE(status, '') NOT IN ('SATISFIED', 'EXPIRED');