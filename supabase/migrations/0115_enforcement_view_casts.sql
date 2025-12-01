-- 0115_enforcement_view_casts.sql
-- Finalize enforcement dashboard views with text plaintiff identifiers to keep doctor refreshes idempotent.
-- migrate:up
BEGIN;
DROP VIEW IF EXISTS public.v_enforcement_recent CASCADE;
DROP VIEW IF EXISTS public.v_judgment_pipeline CASCADE;
CREATE OR REPLACE VIEW public.v_enforcement_recent AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id::text AS plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
ORDER BY j.enforcement_stage_updated_at DESC,
    j.id DESC;
GRANT SELECT ON public.v_enforcement_recent TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id::text AS plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier,
    cs.age_days AS collectability_age_days,
    cs.last_enriched_at,
    cs.last_enrichment_status
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number;
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated,
    service_role;
COMMIT;
-- migrate:down
BEGIN;
DROP VIEW IF EXISTS public.v_enforcement_recent CASCADE;
DROP VIEW IF EXISTS public.v_judgment_pipeline CASCADE;
CREATE OR REPLACE VIEW public.v_enforcement_recent AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
ORDER BY j.enforcement_stage_updated_at DESC,
    j.id DESC;
GRANT SELECT ON public.v_enforcement_recent TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier,
    cs.age_days AS collectability_age_days,
    cs.last_enriched_at,
    cs.last_enrichment_status
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number;
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated,
    service_role;
COMMIT;