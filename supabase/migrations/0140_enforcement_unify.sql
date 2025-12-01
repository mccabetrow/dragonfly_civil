-- 0140_enforcement_unify.sql
-- Unify enforcement stack: consolidate events, add spawn_enforcement_flow stub
BEGIN;
-- 1. Add plaintiff_id FK to enforcement_cases for direct linkage
ALTER TABLE public.enforcement_cases
ADD COLUMN IF NOT EXISTS plaintiff_id uuid REFERENCES public.plaintiffs(id) ON DELETE
SET NULL;
CREATE INDEX IF NOT EXISTS enforcement_cases_plaintiff_idx ON public.enforcement_cases(plaintiff_id);
-- 2. Backfill plaintiff_id from judgments
UPDATE public.enforcement_cases ec
SET plaintiff_id = j.plaintiff_id
FROM public.judgments j
WHERE ec.judgment_id = j.id
    AND ec.plaintiff_id IS NULL
    AND j.plaintiff_id IS NOT NULL;
-- 3. Create spawn_enforcement_flow stub (workers expect this)
CREATE OR REPLACE FUNCTION public.spawn_enforcement_flow(
        p_case_number text,
        p_template_code text DEFAULT 'INFO_SUBPOENA_FLOW'
    ) RETURNS uuid [] LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_judgment_id bigint;
v_case_id uuid;
v_plaintiff_id uuid;
v_created_ids uuid [];
BEGIN -- Lookup judgment
SELECT id,
    plaintiff_id INTO v_judgment_id,
    v_plaintiff_id
FROM public.judgments
WHERE case_number = p_case_number
LIMIT 1;
IF v_judgment_id IS NULL THEN RAISE EXCEPTION 'spawn_enforcement_flow: judgment not found for case_number %',
p_case_number USING ERRCODE = 'P0002';
END IF;
-- Upsert enforcement_case
INSERT INTO public.enforcement_cases (
        judgment_id,
        plaintiff_id,
        case_number,
        status,
        current_stage
    )
VALUES (
        v_judgment_id,
        v_plaintiff_id,
        p_case_number,
        'open',
        'enforcement_active'
    ) ON CONFLICT (judgment_id) DO
UPDATE
SET status = 'open',
    current_stage = COALESCE(
        EXCLUDED.current_stage,
        enforcement_cases.current_stage
    ),
    updated_at = timezone('utc', now())
RETURNING id INTO v_case_id;
-- Log timeline entry
INSERT INTO public.enforcement_timeline (
        case_id,
        judgment_id,
        plaintiff_id,
        entry_kind,
        stage_key,
        title,
        details
    )
VALUES (
        v_case_id,
        v_judgment_id,
        v_plaintiff_id,
        'stage_change',
        p_template_code,
        'Enforcement flow spawned',
        format('Template: %s', p_template_code)
    );
-- Generate tasks via existing RPC
SELECT array_agg(task_id) INTO v_created_ids
FROM public.generate_enforcement_tasks(v_case_id);
RETURN COALESCE(v_created_ids, ARRAY []::uuid []);
END;
$$;
GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(text, text) TO authenticated,
    service_role;
-- 4. Add unique constraint on enforcement_cases(judgment_id) for upsert
CREATE UNIQUE INDEX IF NOT EXISTS enforcement_cases_judgment_unique_idx ON public.enforcement_cases(judgment_id);
-- 5. Updated v_enforcement_timeline to unify all sources
CREATE OR REPLACE VIEW public.v_enforcement_timeline AS
SELECT t.case_id,
    t.id AS source_id,
    t.entry_kind AS item_kind,
    COALESCE(t.created_at, timezone('utc', now())) AS occurred_at,
    t.title,
    t.details,
    NULL::text AS storage_path,
    NULL::text AS file_type,
    NULL::text AS uploaded_by,
    t.metadata,
    t.created_at
FROM public.enforcement_timeline t
UNION ALL
SELECT e.case_id,
    e.id AS source_id,
    'event_legacy'::text AS item_kind,
    e.event_date AS occurred_at,
    e.event_type AS title,
    e.notes AS details,
    NULL::text AS storage_path,
    NULL::text AS file_type,
    NULL::text AS uploaded_by,
    e.metadata,
    e.created_at
FROM public.enforcement_events e
UNION ALL
SELECT f.case_id,
    f.id AS source_id,
    'evidence'::text AS item_kind,
    COALESCE(f.created_at, timezone('utc', now())) AS occurred_at,
    COALESCE(f.file_type, 'evidence') AS title,
    NULL::text AS details,
    f.storage_path,
    f.file_type,
    f.uploaded_by,
    f.metadata,
    f.created_at
FROM public.evidence_files f
UNION ALL
SELECT ee.case_id,
    ee.id AS source_id,
    'evidence_v2'::text AS item_kind,
    ee.uploaded_at AS occurred_at,
    ee.evidence_type AS title,
    NULL::text AS details,
    ee.file_path AS storage_path,
    COALESCE(ee.mime_type, ee.evidence_type) AS file_type,
    ee.uploaded_by,
    ee.metadata,
    ee.uploaded_at
FROM public.enforcement_evidence ee;
GRANT SELECT ON public.v_enforcement_timeline TO anon,
    authenticated,
    service_role;
COMMIT;