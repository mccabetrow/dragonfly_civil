-- 0073_enforcement_stages.sql
-- Add enforcement stages to judgments and expose dashboard-friendly views.

-- migrate:up

-- Extend judgments with canonical enforcement tracking columns.
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS enforcement_stage text NOT NULL DEFAULT 'pre_enforcement',
ADD COLUMN IF NOT EXISTS enforcement_stage_updated_at timestamptz NOT NULL DEFAULT now();

-- Backfill any existing rows that still carry null enforcement metadata.
UPDATE public.judgments
SET enforcement_stage = 'pre_enforcement'
WHERE enforcement_stage IS NULL;

UPDATE public.judgments
SET enforcement_stage_updated_at = coalesce(enforcement_stage_updated_at, now())
WHERE enforcement_stage_updated_at IS NULL;

-- Make sure defaults and constraints are enforced even if the column pre-existed.
ALTER TABLE public.judgments
ALTER COLUMN enforcement_stage SET DEFAULT 'pre_enforcement',
ALTER COLUMN enforcement_stage SET NOT NULL,
ALTER COLUMN enforcement_stage_updated_at SET DEFAULT now(),
ALTER COLUMN enforcement_stage_updated_at SET NOT NULL;

COMMENT ON COLUMN public.judgments.enforcement_stage IS
'Canonical enforcement stage. Allowed values: pre_enforcement, paperwork_filed, levy_issued, waiting_payment, payment_plan, collected, closed_no_recovery.';

-- Aggregate enforcement rolls by stage and collectability tier.
CREATE OR REPLACE VIEW public.v_enforcement_overview AS
SELECT
    j.enforcement_stage,
    cs.collectability_tier,
    count(*) AS case_count,
    coalesce(sum(j.judgment_amount), 0) AS total_judgment_amount
FROM public.judgments AS j
LEFT JOIN public.v_collectability_snapshot AS cs
    ON j.case_number = cs.case_number
GROUP BY
    j.enforcement_stage,
    cs.collectability_tier;

-- Surface the most recent enforcement transitions for the dashboard.
DO $$
DECLARE
    has_plaintiff_id boolean;
    has_plaintiffs_table boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'judgments'
          AND column_name = 'plaintiff_id'
    ) INTO has_plaintiff_id;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'plaintiffs'
    ) INTO has_plaintiffs_table;

    IF has_plaintiff_id AND has_plaintiffs_table THEN
        EXECUTE $view$
        CREATE OR REPLACE VIEW public.v_enforcement_recent AS
        SELECT
            j.id AS judgment_id,
            j.case_number,
            j.plaintiff_id::text AS plaintiff_id,
            j.judgment_amount,
            j.enforcement_stage,
            j.enforcement_stage_updated_at,
            cs.collectability_tier,
            COALESCE(p.name, j.plaintiff_name) AS plaintiff_name
        FROM public.judgments j
        LEFT JOIN public.plaintiffs p
            ON p.id::text = j.plaintiff_id::text
        LEFT JOIN public.v_collectability_snapshot cs
            ON cs.case_number = j.case_number
        ORDER BY
            j.enforcement_stage_updated_at DESC,
            j.id DESC;
        $view$;
    ELSIF has_plaintiffs_table THEN
        EXECUTE $view$
        CREATE OR REPLACE VIEW public.v_enforcement_recent AS
        SELECT
            j.id AS judgment_id,
            j.case_number,
            p.id::text AS plaintiff_id,
            j.judgment_amount,
            j.enforcement_stage,
            j.enforcement_stage_updated_at,
            cs.collectability_tier,
            COALESCE(p.name, j.plaintiff_name) AS plaintiff_name
        FROM public.judgments j
        LEFT JOIN public.plaintiffs p
            ON lower(p.name) = lower(j.plaintiff_name)
        LEFT JOIN public.v_collectability_snapshot cs
            ON cs.case_number = j.case_number
        ORDER BY
            j.enforcement_stage_updated_at DESC,
            j.id DESC;
        $view$;
    ELSE
        EXECUTE $view$
        CREATE OR REPLACE VIEW public.v_enforcement_recent AS
        SELECT
            j.id AS judgment_id,
            j.case_number,
            NULL::text AS plaintiff_id,
            j.judgment_amount,
            j.enforcement_stage,
            j.enforcement_stage_updated_at,
            cs.collectability_tier,
            j.plaintiff_name
        FROM public.judgments j
        LEFT JOIN public.v_collectability_snapshot cs
            ON cs.case_number = j.case_number
        ORDER BY
            j.enforcement_stage_updated_at DESC,
            j.id DESC;
        $view$;
    END IF;
END
$$;

-- Refresh pipeline view so downstream dashboards receive enforcement metadata.
DO $$
DECLARE
    has_plaintiff_id boolean;
    has_plaintiffs_table boolean;
BEGIN
    SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'judgments'
          AND column_name = 'plaintiff_id'
    ) INTO has_plaintiff_id;

    SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
          AND table_name = 'plaintiffs'
    ) INTO has_plaintiffs_table;

    IF has_plaintiff_id AND has_plaintiffs_table THEN
        EXECUTE $view$
        CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
        SELECT
            j.id AS judgment_id,
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
        LEFT JOIN public.plaintiffs p
            ON p.id::text = j.plaintiff_id::text
        LEFT JOIN public.v_collectability_snapshot cs
            ON cs.case_number = j.case_number;
        $view$;
    ELSIF has_plaintiffs_table THEN
        EXECUTE $view$
        CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
        SELECT
            j.id AS judgment_id,
            j.case_number,
            p.id::text AS plaintiff_id,
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
        LEFT JOIN public.plaintiffs p
            ON lower(p.name) = lower(j.plaintiff_name)
        LEFT JOIN public.v_collectability_snapshot cs
            ON cs.case_number = j.case_number;
        $view$;
    ELSE
        EXECUTE $view$
        CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
        SELECT
            j.id AS judgment_id,
            j.case_number,
            NULL::text AS plaintiff_id,
            j.plaintiff_name,
            j.defendant_name,
            j.judgment_amount,
            j.enforcement_stage,
            j.enforcement_stage_updated_at,
            cs.collectability_tier,
            cs.age_days AS collectability_age_days,
            cs.last_enriched_at,
            cs.last_enrichment_status
        FROM public.judgments j
        LEFT JOIN public.v_collectability_snapshot cs
            ON cs.case_number = j.case_number;
        $view$;
    END IF;
END
$$;

GRANT SELECT ON public.v_enforcement_overview TO anon,
authenticated,
service_role;
GRANT SELECT ON public.v_enforcement_recent TO anon,
authenticated,
service_role;

-- migrate:down

REVOKE SELECT ON public.v_enforcement_recent FROM anon,
authenticated,
service_role;
REVOKE SELECT ON public.v_enforcement_overview FROM anon,
authenticated,
service_role;

DROP VIEW IF EXISTS public.v_enforcement_recent;
DROP VIEW IF EXISTS public.v_enforcement_overview;

ALTER TABLE public.judgments
DROP COLUMN IF EXISTS enforcement_stage_updated_at CASCADE,
DROP COLUMN IF EXISTS enforcement_stage CASCADE;

-- Purpose: track enforcement stages on judgments and provide overview/recent views for dashboards.
