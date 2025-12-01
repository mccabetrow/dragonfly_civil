-- 0130_enforcement_evidence.sql
-- Enforcement Evidence Engine v1 schema, grants, and RPCs.
BEGIN;
CREATE TABLE IF NOT EXISTS public.enforcement_evidence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs(id) ON DELETE CASCADE,
    case_id uuid NOT NULL REFERENCES public.enforcement_cases(id) ON DELETE CASCADE,
    evidence_type text NOT NULL CHECK (char_length(trim(evidence_type)) > 0),
    storage_bucket text NOT NULL DEFAULT 'enforcement_evidence',
    file_path text NOT NULL CHECK (
        char_length(trim(file_path)) > 0
        AND position('..' IN file_path) = 0
    ),
    checksum text,
    mime_type text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    uploaded_by text NOT NULL DEFAULT current_user::text,
    uploaded_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    CONSTRAINT enforcement_evidence_case_path_unique UNIQUE (case_id, file_path)
);
COMMENT ON TABLE public.enforcement_evidence IS 'Stores metadata + storage pointers for enforcement evidence artifacts in Supabase storage.';
CREATE INDEX IF NOT EXISTS enforcement_evidence_case_idx ON public.enforcement_evidence (case_id, uploaded_at DESC);
CREATE INDEX IF NOT EXISTS enforcement_evidence_plaintiff_idx ON public.enforcement_evidence (plaintiff_id, uploaded_at DESC);
ALTER TABLE public.enforcement_evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enforcement_evidence FORCE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'enforcement_evidence'
        AND policyname = 'enforcement_evidence_select_authenticated'
) THEN EXECUTE 'CREATE POLICY enforcement_evidence_select_authenticated ON public.enforcement_evidence FOR SELECT TO authenticated USING (true);';
END IF;
END $$;
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'enforcement_evidence'
        AND policyname = 'enforcement_evidence_write_service_role'
) THEN EXECUTE 'CREATE POLICY enforcement_evidence_write_service_role ON public.enforcement_evidence FOR ALL TO service_role USING (true) WITH CHECK (true);';
END IF;
END $$;
GRANT SELECT ON public.enforcement_evidence TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.enforcement_evidence TO service_role;
CREATE OR REPLACE FUNCTION public.add_evidence(
        plaintiff_id uuid,
        case_id uuid,
        evidence_type text,
        file_path text,
        metadata jsonb DEFAULT '{}'::jsonb,
        mime_type text DEFAULT NULL,
        checksum text DEFAULT NULL
    ) RETURNS public.enforcement_evidence LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_case RECORD;
v_path text;
v_metadata jsonb := COALESCE(jsonb_strip_nulls(metadata), '{}'::jsonb);
v_uploaded_by text := COALESCE(
    NULLIF(
        current_setting('request.jwt.claim.email', true),
        ''
    ),
    NULLIF(
        current_setting('request.jwt.claim.sub', true),
        ''
    ),
    current_user::text
);
v_row public.enforcement_evidence;
BEGIN IF plaintiff_id IS NULL
OR case_id IS NULL THEN RAISE EXCEPTION 'plaintiff_id and case_id are required' USING ERRCODE = '23502';
END IF;
IF COALESCE(trim(evidence_type), '') = '' THEN RAISE EXCEPTION 'evidence_type is required' USING ERRCODE = '23514';
END IF;
IF COALESCE(trim(file_path), '') = '' THEN RAISE EXCEPTION 'file_path is required' USING ERRCODE = '23514';
END IF;
SELECT ec.id,
    ec.plaintiff_id INTO v_case
FROM public.enforcement_cases ec
WHERE ec.id = case_id
LIMIT 1;
IF v_case.id IS NULL THEN RAISE EXCEPTION 'enforcement case % not found',
case_id USING ERRCODE = 'P0002';
END IF;
IF v_case.plaintiff_id IS DISTINCT
FROM plaintiff_id THEN RAISE EXCEPTION 'case % does not belong to plaintiff %',
    case_id,
    plaintiff_id USING ERRCODE = '23503';
END IF;
v_path := regexp_replace(file_path, '\\', '/', 'g');
v_path := regexp_replace(v_path, '^/+|/+$', '', 'g');
IF position('..' IN v_path) > 0 THEN RAISE EXCEPTION 'file_path cannot contain .. segments' USING ERRCODE = '22023';
END IF;
IF v_path = '' THEN RAISE EXCEPTION 'file_path must include a filename' USING ERRCODE = '23514';
END IF;
v_path := format('%s/%s', case_id, v_path);
INSERT INTO public.enforcement_evidence (
        plaintiff_id,
        case_id,
        evidence_type,
        storage_bucket,
        file_path,
        metadata,
        mime_type,
        checksum,
        uploaded_by
    )
VALUES (
        plaintiff_id,
        case_id,
        trim(evidence_type),
        'enforcement_evidence',
        v_path,
        v_metadata,
        NULLIF(mime_type, ''),
        NULLIF(checksum, ''),
        v_uploaded_by
    ) ON CONFLICT (case_id, file_path) DO
UPDATE
SET evidence_type = EXCLUDED.evidence_type,
    metadata = EXCLUDED.metadata,
    mime_type = COALESCE(
        EXCLUDED.mime_type,
        enforcement_evidence.mime_type
    ),
    checksum = COALESCE(EXCLUDED.checksum, enforcement_evidence.checksum),
    uploaded_by = EXCLUDED.uploaded_by,
    uploaded_at = timezone('utc', now())
RETURNING * INTO v_row;
RETURN v_row;
END;
$$;
REVOKE ALL ON FUNCTION public.add_evidence(uuid, uuid, text, text, jsonb, text, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.add_evidence(uuid, uuid, text, text, jsonb, text, text) TO authenticated,
    service_role;
COMMIT;