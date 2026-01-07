-- 0153_enrichment_rpcs.sql
-- Recreate enrichment + scoring RPCs required by workers and schema guard.
BEGIN;
CREATE OR REPLACE FUNCTION public.set_case_enrichment(
    p_case_id uuid,
    p_collectability_score numeric,
    p_collectability_tier text,
    p_summary text DEFAULT NULL
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
pg_temp AS $$
DECLARE v_tier text;
BEGIN IF p_case_id IS NULL THEN RAISE EXCEPTION 'set_case_enrichment: case_id is required' USING ERRCODE = '23502';
END IF;
v_tier := NULLIF(btrim(COALESCE(p_collectability_tier, '')), '');
UPDATE judgments.cases
SET collectability_score = p_collectability_score,
    collectability_tier = v_tier,
    last_enriched_at = timezone('utc', now()),
    updated_at = timezone('utc', now())
WHERE case_id = p_case_id;
IF NOT FOUND THEN RAISE EXCEPTION 'set_case_enrichment: case % not found',
p_case_id USING ERRCODE = 'P0002';
END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.set_case_enrichment(uuid, numeric, text, text)
FROM public;
REVOKE ALL ON FUNCTION public.set_case_enrichment(uuid, numeric, text, text)
FROM anon;
REVOKE ALL ON FUNCTION public.set_case_enrichment(uuid, numeric, text, text)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.set_case_enrichment(
    uuid, numeric, text, text
) TO service_role;
CREATE OR REPLACE FUNCTION public.set_case_scores(
    p_case_id uuid,
    p_identity_score numeric,
    p_contactability_score numeric,
    p_asset_score numeric,
    p_recency_amount_score numeric,
    p_adverse_penalty numeric,
    p_collectability_score numeric,
    p_collectability_tier text
) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
pg_temp AS $$
DECLARE v_tier text;
BEGIN IF p_case_id IS NULL THEN RAISE EXCEPTION 'set_case_scores: case_id is required' USING ERRCODE = '23502';
END IF;
v_tier := NULLIF(btrim(COALESCE(p_collectability_tier, '')), '');
UPDATE judgments.cases
SET identity_score = p_identity_score,
    contactability_score = p_contactability_score,
    asset_score = p_asset_score,
    recency_amount_score = p_recency_amount_score,
    adverse_penalty = p_adverse_penalty,
    collectability_score = p_collectability_score,
    collectability_tier = v_tier,
    last_scored_at = timezone('utc', now()),
    updated_at = timezone('utc', now())
WHERE case_id = p_case_id;
IF NOT FOUND THEN RAISE EXCEPTION 'set_case_scores: case % not found',
p_case_id USING ERRCODE = 'P0002';
END IF;
END;
$$;
REVOKE ALL ON FUNCTION public.set_case_scores(
    uuid,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    text
)
FROM public;
REVOKE ALL ON FUNCTION public.set_case_scores(
    uuid,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    text
)
FROM anon;
REVOKE ALL ON FUNCTION public.set_case_scores(
    uuid,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    text
)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.set_case_scores(
    uuid,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    numeric,
    text
) TO service_role;
CREATE OR REPLACE FUNCTION public.upsert_enrichment_bundle(
    bundle jsonb
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
pg_temp AS $$
DECLARE v_case_id uuid;
v_contacts jsonb := COALESCE(bundle->'contacts', '[]'::jsonb);
v_assets jsonb := COALESCE(bundle->'assets', '[]'::jsonb);
v_contacts_count integer := 0;
v_assets_count integer := 0;
BEGIN v_case_id := (bundle->>'case_id')::uuid;
IF v_case_id IS NULL THEN RAISE EXCEPTION 'upsert_enrichment_bundle: case_id is required' USING ERRCODE = '23502';
END IF;
PERFORM 1
FROM judgments.cases
WHERE case_id = v_case_id;
IF NOT FOUND THEN RAISE EXCEPTION 'upsert_enrichment_bundle: case % not found',
v_case_id USING ERRCODE = 'P0002';
END IF;
IF v_contacts IS NOT NULL
AND jsonb_typeof(v_contacts) <> 'array' THEN RAISE EXCEPTION 'upsert_enrichment_bundle: contacts must be an array' USING ERRCODE = '22023';
END IF;
IF v_assets IS NOT NULL
AND jsonb_typeof(v_assets) <> 'array' THEN RAISE EXCEPTION 'upsert_enrichment_bundle: assets must be an array' USING ERRCODE = '22023';
END IF;
IF jsonb_array_length(v_contacts) > 0 THEN WITH payload AS (
    SELECT (contact->>'entity_id')::uuid AS entity_id,
        NULLIF(contact->>'kind', '')::enrichment.contact_kind AS kind,
        NULLIF(contact->>'value', '') AS value,
        NULLIF(contact->>'source', '') AS source,
        NULLIF(contact->>'score', '')::numeric AS score,
        COALESCE((contact->>'validated_bool')::boolean, FALSE) AS validated_bool
    FROM jsonb_array_elements(v_contacts) AS elems(contact)
)
INSERT INTO enrichment.contacts (
        entity_id,
        kind,
        value,
        source,
        score,
        validated_bool
    )
SELECT entity_id,
    kind,
    value,
    source,
    score,
    validated_bool
FROM payload
WHERE entity_id IS NOT NULL
    AND kind IS NOT NULL
    AND value IS NOT NULL ON CONFLICT (entity_id, kind, value) DO
UPDATE
SET source = EXCLUDED.source,
    score = EXCLUDED.score,
    validated_bool = EXCLUDED.validated_bool;
GET DIAGNOSTICS v_contacts_count = ROW_COUNT;
END IF;
IF jsonb_array_length(v_assets) > 0 THEN WITH payload AS (
    SELECT (asset->>'entity_id')::uuid AS entity_id,
        NULLIF(asset->>'asset_type', '') AS asset_type,
        COALESCE(asset->'meta_json', '{}'::jsonb) AS meta_json,
        NULLIF(asset->>'source', '') AS source,
        NULLIF(asset->>'confidence', '')::numeric AS confidence
    FROM jsonb_array_elements(v_assets) AS elems(asset)
)
INSERT INTO enrichment.assets (
        entity_id,
        asset_type,
        meta_json,
        source,
        confidence
    )
SELECT entity_id,
    asset_type,
    meta_json,
    source,
    confidence
FROM payload
WHERE entity_id IS NOT NULL
    AND asset_type IS NOT NULL ON CONFLICT (entity_id, asset_type) DO
UPDATE
SET meta_json = EXCLUDED.meta_json,
    source = EXCLUDED.source,
    confidence = EXCLUDED.confidence;
GET DIAGNOSTICS v_assets_count = ROW_COUNT;
END IF;
RETURN jsonb_build_object(
    'ok',
    TRUE,
    'case_id',
    v_case_id,
    'contacts_processed',
    COALESCE(v_contacts_count, 0),
    'assets_processed',
    COALESCE(v_assets_count, 0)
);
END;
$$;
REVOKE ALL ON FUNCTION public.upsert_enrichment_bundle(jsonb)
FROM public;
REVOKE ALL ON FUNCTION public.upsert_enrichment_bundle(jsonb)
FROM anon;
REVOKE ALL ON FUNCTION public.upsert_enrichment_bundle(jsonb)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_enrichment_bundle(
    jsonb
) TO service_role;
SELECT public.pgrst_reload();
COMMIT;

