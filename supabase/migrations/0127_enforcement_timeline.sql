-- 0127_enforcement_timeline.sql
-- Establish a canonical enforcement timeline table + RPC so workers/dashboard can log and read chronological events.
BEGIN;
CREATE TABLE IF NOT EXISTS public.enforcement_timeline (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES public.enforcement_cases(id) ON DELETE CASCADE,
    judgment_id bigint NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    plaintiff_id uuid REFERENCES public.plaintiffs(id) ON DELETE
    SET NULL,
        entry_kind text NOT NULL DEFAULT 'event',
        stage_key text,
        status text,
        source text NOT NULL DEFAULT 'timeline_engine',
        title text NOT NULL,
        details text,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        occurred_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
        created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
        created_by text,
        CONSTRAINT enforcement_timeline_title_required CHECK (btrim(COALESCE(title, '')) <> ''),
        CONSTRAINT enforcement_timeline_kind_required CHECK (btrim(COALESCE(entry_kind, '')) <> '')
);
CREATE INDEX IF NOT EXISTS enforcement_timeline_case_idx ON public.enforcement_timeline (case_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS enforcement_timeline_judgment_idx ON public.enforcement_timeline (judgment_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS enforcement_timeline_stage_idx ON public.enforcement_timeline (stage_key)
WHERE stage_key IS NOT NULL;
ALTER TABLE public.enforcement_timeline ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON public.enforcement_timeline
FROM PUBLIC;
GRANT SELECT ON public.enforcement_timeline TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE,
    DELETE ON public.enforcement_timeline TO authenticated,
    service_role;
DROP POLICY IF EXISTS enforcement_timeline_read ON public.enforcement_timeline;
DROP POLICY IF EXISTS enforcement_timeline_write ON public.enforcement_timeline;
CREATE POLICY enforcement_timeline_read ON public.enforcement_timeline FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
CREATE POLICY enforcement_timeline_write ON public.enforcement_timeline FOR ALL USING (auth.role() IN ('authenticated', 'service_role')) WITH CHECK (auth.role() IN ('authenticated', 'service_role'));
DROP VIEW IF EXISTS public.v_enforcement_timeline;
CREATE OR REPLACE VIEW public.v_enforcement_timeline AS
SELECT et.case_id,
    et.id AS source_id,
    COALESCE(NULLIF(et.entry_kind, ''), 'event') AS item_kind,
    et.occurred_at,
    et.title,
    et.details,
    NULL::text AS storage_path,
    NULL::text AS file_type,
    NULL::text AS uploaded_by,
    jsonb_strip_nulls(
        COALESCE(et.metadata, '{}'::jsonb) || jsonb_build_object(
            'judgment_id',
            et.judgment_id,
            'plaintiff_id',
            et.plaintiff_id,
            'stage_key',
            et.stage_key,
            'status',
            et.status,
            'source',
            et.source,
            'created_by',
            et.created_by
        )
    ) AS metadata,
    et.created_at
FROM public.enforcement_timeline et
UNION ALL
SELECT e.case_id,
    e.id AS source_id,
    'event'::text AS item_kind,
    e.event_date AS occurred_at,
    e.event_type AS title,
    e.notes AS details,
    NULL::text AS storage_path,
    NULL::text AS file_type,
    NULL::text AS uploaded_by,
    jsonb_strip_nulls(
        COALESCE(e.metadata, '{}'::jsonb) || jsonb_build_object('legacy_table', 'enforcement_events')
    ) AS metadata,
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
    jsonb_strip_nulls(
        COALESCE(f.metadata, '{}'::jsonb) || jsonb_build_object('legacy_table', 'evidence_files')
    ) AS metadata,
    f.created_at
FROM public.evidence_files f;
GRANT SELECT ON public.v_enforcement_timeline TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE FUNCTION public.add_enforcement_event(
        _judgment_id bigint,
        _case_id uuid,
        _title text,
        _details text DEFAULT NULL,
        _occurred_at timestamptz DEFAULT NULL,
        _entry_kind text DEFAULT 'event',
        _stage_key text DEFAULT NULL,
        _status text DEFAULT NULL,
        _metadata jsonb DEFAULT '{}'::jsonb,
        _source text DEFAULT 'add_enforcement_event',
        _created_by text DEFAULT NULL
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE v_case_id uuid;
v_judgment_id bigint;
v_plaintiff_id uuid;
v_title text := btrim(COALESCE(_title, ''));
v_kind text := COALESCE(
    NULLIF(btrim(COALESCE(_entry_kind, '')), ''),
    'event'
);
v_event_id uuid;
v_now timestamptz := timezone('utc', now());
BEGIN IF v_title = '' THEN RAISE EXCEPTION 'title is required for enforcement timeline entries';
END IF;
IF _case_id IS NOT NULL THEN
SELECT ec.id,
    ec.judgment_id INTO v_case_id,
    v_judgment_id
FROM public.enforcement_cases ec
WHERE ec.id = _case_id
LIMIT 1;
ELSIF _judgment_id IS NOT NULL THEN
SELECT ec.id,
    ec.judgment_id INTO v_case_id,
    v_judgment_id
FROM public.enforcement_cases ec
WHERE ec.judgment_id = _judgment_id
ORDER BY ec.opened_at DESC
LIMIT 1;
END IF;
IF v_case_id IS NULL THEN RAISE EXCEPTION 'enforcement case not found for judgment_id %, case_id %',
_judgment_id,
_case_id USING ERRCODE = 'P0002';
END IF;
IF v_judgment_id IS NULL THEN
SELECT ec.judgment_id INTO v_judgment_id
FROM public.enforcement_cases ec
WHERE ec.id = v_case_id;
END IF;
SELECT j.plaintiff_id INTO v_plaintiff_id
FROM public.judgments j
WHERE j.id = v_judgment_id;
INSERT INTO public.enforcement_timeline (
        case_id,
        judgment_id,
        plaintiff_id,
        entry_kind,
        stage_key,
        status,
        source,
        title,
        details,
        metadata,
        occurred_at,
        created_at,
        created_by
    )
VALUES (
        v_case_id,
        v_judgment_id,
        v_plaintiff_id,
        v_kind,
        NULLIF(btrim(COALESCE(_stage_key, '')), ''),
        NULLIF(btrim(COALESCE(_status, '')), ''),
        COALESCE(
            NULLIF(btrim(COALESCE(_source, '')), ''),
            'add_enforcement_event'
        ),
        v_title,
        NULLIF(_details, ''),
        jsonb_strip_nulls(COALESCE(_metadata, '{}'::jsonb)),
        COALESCE(_occurred_at, v_now),
        v_now,
        NULLIF(btrim(COALESCE(_created_by, '')), '')
    )
RETURNING id INTO v_event_id;
RETURN v_event_id;
END;
$$;
REVOKE ALL ON FUNCTION public.add_enforcement_event(
    bigint,
    uuid,
    text,
    text,
    timestamptz,
    text,
    text,
    text,
    jsonb,
    text,
    text
)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.add_enforcement_event(
        bigint,
        uuid,
        text,
        text,
        timestamptz,
        text,
        text,
        text,
        jsonb,
        text,
        text
    ) TO authenticated,
    service_role;
COMMIT;
