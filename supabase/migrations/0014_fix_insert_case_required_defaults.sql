create schema if not exists judgments;
create extension if not exists pgcrypto schema extensions;

-- Recreate RPC with robust defaults for NOT NULL columns
create or replace function public.insert_case(payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_case_id       uuid;
  v_org_id        uuid;
  v_case_number   text;
  v_source_system text;
  v_title         text;
  v_court_name    text;
begin
  -- org id
  v_org_id := coalesce((payload->>'org_id')::uuid, extensions.gen_random_uuid());

  -- Required fields with fallbacks
  v_case_number   := nullif(payload->>'case_number','');
  v_source_system := nullif(coalesce(payload->>'source', payload->>'source_system'), '');
  v_title         := nullif(coalesce(payload->>'title',   payload->>'case_number'), '');
  v_court_name    := nullif(coalesce(payload->>'court',   payload->>'court_name'), '');

  -- Fallbacks if still missing
  if v_case_number is null then
    v_case_number := 'UNK-' || left(encode(extensions.gen_random_bytes(8), 'hex'), 8);
  end if;

  if v_source_system is null then
    v_source_system := 'unknown';
  end if;

  if v_title is null then
    v_title := v_case_number;
  end if;

  if v_court_name is null then
    v_court_name := 'Unknown';
  end if;

  insert into judgments.cases (
    org_id,
    case_number,
    source_system,
    title,
    court_name,
    raw
  )
  values (
    v_org_id,
    v_case_number,
    v_source_system,
    v_title,
    v_court_name,
    payload
  )
  returning case_id into v_case_id;

  return v_case_id;
end
$$;

grant execute on function public.insert_case(jsonb) to anon, authenticated, service_role;
