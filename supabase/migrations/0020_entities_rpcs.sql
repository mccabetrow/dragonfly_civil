-- 0020_entities_rpcs.sql

-- Shared trigger function (idempotent)
create or replace function public.tg_touch_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- Simple entity view
drop view if exists public.v_entities_simple;

create or replace view public.v_entities_simple as
select
    e.entity_id,
    e.case_id,
    e.role,
    e.name_full,
    e.created_at
from parties.entities as e;

drop trigger if exists trg_entities_touch on parties.entities;
create trigger trg_entities_touch
before update on parties.entities
for each row execute function public.tg_touch_updated_at();

-- RPC: insert single entity
create or replace function public.insert_entity(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  new_id uuid;
  entity_payload jsonb := coalesce(payload, '{}'::jsonb);
begin
  if entity_payload->>'case_id' is null then
    raise exception 'payload.case_id is required';
  end if;

  insert into parties.entities (
    case_id,
    role,
    name_full,
    first_name,
    last_name,
    business_name,
    ein_or_ssn,
    address,
    phones,
    emails,
    raw
  )
  values (
    (entity_payload->>'case_id')::uuid,
    entity_payload->>'role',
    entity_payload->>'name_full',
    entity_payload->>'first_name',
    entity_payload->>'last_name',
    entity_payload->>'business_name',
    entity_payload->>'ein_or_ssn',
    entity_payload->'address',
    entity_payload->'phones',
    entity_payload->'emails',
    entity_payload
  )
  returning entity_id into new_id;

  return new_id;
end;
$$;

grant execute on function public.insert_entity(jsonb) to anon,
authenticated,
service_role;

-- RPC: insert case with related entities
create or replace function public.insert_case_with_entities(payload jsonb)
returns jsonb
language plpgsql
security definer
as $$
declare
  case_payload jsonb;
  entities_payload jsonb;
  created_case uuid;
  entity_ids uuid[] := '{}';
  entity_record jsonb;
begin
  case_payload := coalesce(payload->'case', '{}'::jsonb);
  entities_payload := coalesce(payload->'entities', '[]'::jsonb);

  created_case := public.insert_case(case_payload);

  for entity_record in
    select jsonb_array_elements(entities_payload)
  loop
    entity_ids := array_append(
      entity_ids,
      public.insert_entity(
        entity_record || jsonb_build_object('case_id', created_case)
      )
    );
  end loop;

  return jsonb_build_object(
    'case_id', created_case,
    'entity_ids', entity_ids
  );
end;
$$;

grant execute on function public.insert_case_with_entities(jsonb) to anon,
authenticated,
service_role;
