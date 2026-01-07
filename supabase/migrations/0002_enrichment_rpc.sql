create or replace function enrichment.upsert_enrichment_bundle(bundle jsonb)
returns jsonb
language plpgsql
security definer
as $$
declare
  v_case uuid;
begin
  /*
    Expected bundle shape:
    {
      "case_id": "...",
      "contacts": [ { "entity_id": "...", "kind": "phone|email|address", "value": "...", "source": "...", "score": 0-100, "validated_bool": true/false } ],
      "assets":   [ { "entity_id": "...", "asset_type": "real_property|bank_hint|employment|vehicle|license|ucc|dba", "meta_json": {...}, "source":"...", "confidence":0-100 } ]
    }
  */
  v_case := (bundle->>'case_id')::uuid;
  if v_case is null then
    raise exception 'bundle.case_id is required';
  end if;
  -- Contacts
  insert into enrichment.contacts(entity_id, kind, value, source, score, validated_bool)
  select
    (c->>'entity_id')::uuid,
    (c->>'kind')::enrichment.contact_kind,
    c->>'value',
    c->>'source',
    coalesce((c->>'score')::numeric,0),
    coalesce((c->>'validated_bool')::boolean,false)
  from jsonb_array_elements(coalesce(bundle->'contacts','[]'::jsonb)) as c
  on conflict (entity_id, kind, value) do update
    set source = excluded.source,
        score = excluded.score,
        validated_bool = excluded.validated_bool;
  -- Assets
  insert into enrichment.assets(entity_id, asset_type, meta_json, source, confidence)
  select
    (a->>'entity_id')::uuid,
    a->>'asset_type',
    coalesce(a->'meta_json','{}'::jsonb),
    a->>'source',
    coalesce((a->>'confidence')::numeric,0)
  from jsonb_array_elements(coalesce(bundle->'assets','[]'::jsonb)) as a;
  return jsonb_build_object('ok', true, 'case_id', v_case, 'contacts', jsonb_array_length(coalesce(bundle->'contacts','[]'::jsonb)), 'assets', jsonb_array_length(coalesce(bundle->'assets','[]'::jsonb)));
end $$;

grant execute on function enrichment.upsert_enrichment_bundle(jsonb) to anon,
authenticated,
service_role;

