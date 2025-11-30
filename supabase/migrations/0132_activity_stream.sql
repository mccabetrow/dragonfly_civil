-- 0132_activity_stream.sql
-- Activity stream RPC + timeline view updates.
BEGIN;
-- Extend the enforcement timeline view to include structured evidence rows.
CREATE OR REPLACE VIEW public.v_enforcement_timeline AS
SELECT e.case_id,
    e.id AS source_id,
    'event'::text AS item_kind,
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
SELECT ee.case_id,
    ee.id AS source_id,
    'evidence'::text AS item_kind,
    COALESCE(ee.uploaded_at, timezone('utc', now())) AS occurred_at,
    COALESCE(NULLIF(trim(ee.evidence_type), ''), 'evidence') AS title,
    NULLIF(ee.mime_type, '') AS details,
    CASE
        WHEN ee.storage_bucket IS NOT NULL
        AND ee.file_path IS NOT NULL THEN format('%s/%s', ee.storage_bucket, ee.file_path)
        ELSE ee.file_path
    END AS storage_path,
    NULLIF(ee.mime_type, '') AS file_type,
    ee.uploaded_by,
    ee.metadata,
    ee.uploaded_at
FROM public.enforcement_evidence ee
UNION ALL
SELECT f.case_id,
    f.id AS source_id,
    'evidence'::text AS item_kind,
    COALESCE(f.created_at, timezone('utc', now())) AS occurred_at,
    COALESCE(NULLIF(trim(f.file_type), ''), 'evidence') AS title,
    NULL::text AS details,
    f.storage_path,
    f.file_type,
    f.uploaded_by,
    f.metadata,
    f.created_at
FROM public.evidence_files f;
GRANT SELECT ON public.v_enforcement_timeline TO anon,
    authenticated,
    service_role;
-- Surface the most recent enforcement case linked to each judgment for UI wiring.
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
    cs.last_enrichment_status,
    ec.id AS enforcement_case_id
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
    LEFT JOIN LATERAL (
        SELECT ec_inner.id
        FROM public.enforcement_cases ec_inner
        WHERE ec_inner.judgment_id = j.id
        ORDER BY ec_inner.opened_at DESC NULLS LAST,
            ec_inner.created_at DESC NULLS LAST,
            ec_inner.id DESC
        LIMIT 1
    ) ec ON TRUE;
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated,
    service_role;
-- RPC endpoint consumed by the dashboard activity feed.
CREATE OR REPLACE FUNCTION public.get_enforcement_timeline(
        p_case_id uuid,
        p_limit_count integer DEFAULT 50
    ) RETURNS TABLE (
        case_id uuid,
        source_id uuid,
        item_kind text,
        occurred_at timestamptz,
        title text,
        details text,
        storage_path text,
        file_type text,
        uploaded_by text,
        metadata jsonb,
        created_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_limit integer := COALESCE(NULLIF(p_limit_count, 0), 50);
BEGIN IF p_case_id IS NULL THEN RAISE EXCEPTION 'case_id is required' USING ERRCODE = '23502';
END IF;
IF v_limit < 0 THEN v_limit := 50;
END IF;
RETURN QUERY
SELECT t.case_id,
    t.source_id,
    t.item_kind,
    t.occurred_at,
    t.title,
    t.details,
    t.storage_path,
    t.file_type,
    t.uploaded_by,
    t.metadata,
    t.created_at
FROM public.v_enforcement_timeline t
WHERE t.case_id = p_case_id
ORDER BY t.occurred_at DESC NULLS LAST,
    t.created_at DESC NULLS LAST,
    t.source_id DESC
LIMIT v_limit;
END;
$$;
REVOKE ALL ON FUNCTION public.get_enforcement_timeline(uuid, integer)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_enforcement_timeline(uuid, integer) TO anon;
GRANT EXECUTE ON FUNCTION public.get_enforcement_timeline(uuid, integer) TO authenticated;
GRANT EXECUTE ON FUNCTION public.get_enforcement_timeline(uuid, integer) TO service_role;
COMMIT;