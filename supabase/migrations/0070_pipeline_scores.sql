-- migrate:up

alter table judgments.cases
add column if not exists last_enriched_at timestamptz,
add column if not exists last_scored_at timestamptz,
add column if not exists identity_score numeric(5, 2),
add column if not exists contactability_score numeric(5, 2),
add column if not exists asset_score numeric(5, 2),
add column if not exists recency_amount_score numeric(5, 2),
add column if not exists adverse_penalty numeric(5, 2),
add column if not exists collectability_score numeric(5, 2),
add column if not exists collectability_tier text;

do $$
begin
  if to_regclass('enrichment.assets') is not null then
    create unique index if not exists enrichment_assets_entity_type_key
      on enrichment.assets (entity_id, asset_type);
  end if;
end;
$$;

create or replace function public.set_case_enrichment(
    p_case_id uuid,
    p_collectability_score numeric,
    p_collectability_tier text,
    p_summary text default null
) returns void
language plpgsql
security definer
as $$
begin
  update judgments.cases
  set
    collectability_score = p_collectability_score,
    collectability_tier = p_collectability_tier,
    last_enriched_at = now(),
    updated_at = now()
  where case_id = p_case_id;
end;
$$;

grant execute on function public.set_case_enrichment(uuid, numeric, text, text)
to anon, authenticated, service_role;

create or replace function public.set_case_scores(
    p_case_id uuid,
    p_identity_score numeric,
    p_contactability_score numeric,
    p_asset_score numeric,
    p_recency_amount_score numeric,
    p_adverse_penalty numeric,
    p_collectability_score numeric,
    p_collectability_tier text
) returns void
language plpgsql
security definer
as $$
begin
  update judgments.cases
  set
    identity_score = p_identity_score,
    contactability_score = p_contactability_score,
    asset_score = p_asset_score,
    recency_amount_score = p_recency_amount_score,
    adverse_penalty = p_adverse_penalty,
    collectability_score = p_collectability_score,
    collectability_tier = p_collectability_tier,
    last_scored_at = now(),
    updated_at = now()
  where case_id = p_case_id;
end;
$$;

grant execute on function public.set_case_scores(
    uuid, numeric, numeric, numeric, numeric, numeric, numeric, text
)
to anon, authenticated, service_role;

-- migrate:down
-- no view change; 0006_public_surface_hardening maintains v_cases compatibly

drop function if exists public.set_case_scores (
    uuid, numeric, numeric, numeric, numeric, numeric, numeric, text
);
drop function if exists public.set_case_enrichment (uuid, numeric, text, text);

drop index if exists enrichment_assets_entity_type_key;

alter table judgments.cases
drop column if exists collectability_tier,
drop column if exists collectability_score,
drop column if exists adverse_penalty,
drop column if exists recency_amount_score,
drop column if exists asset_score,
drop column if exists contactability_score,
drop column if exists identity_score,
drop column if exists last_scored_at,
drop column if exists last_enriched_at;

