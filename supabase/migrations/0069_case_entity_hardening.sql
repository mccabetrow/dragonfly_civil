-- 0069_case_entity_hardening.sql

-- Normalize entity names for idempotent upserts
create or replace function public.normalize_party_name(value text)
returns text
language plpgsql
immutable
as $$
declare
  normalized text;
begin
  if value is null then
    return null;
  end if;
  normalized := regexp_replace(lower(value), '[^a-z0-9]', '', 'g');
  if normalized is null or normalized = '' then
    normalized := 'hash_' || md5(value);
  end if;
  return normalized;
end;
$$;

alter table parties.entities
add column if not exists name_normalized text;

-- Align stored roles and normalized names
update parties.entities
set role = coalesce(nullif(lower(role), ''), 'defendant');

update parties.entities
set name_normalized = coalesce(
    public.normalize_party_name(
        coalesce(
            nullif(name_full, ''),
            nullif(business_name, ''),
            nullif(
                trim(
                    concat_ws(
                        ' ', nullif(first_name, ''), nullif(last_name, '')
                    )
                ),
                ''
            ),
            nullif(raw ->> 'name_full', ''),
            nullif(raw ->> 'name', '')
        )
    ),
    'hash_'
    || md5(coalesce(raw ->> 'name_full', raw ->> 'name', entity_id::text))
);

-- Remove duplicate entities that collapse under normalized keys
with ranked as (
    select
        entity_id,
        row_number() over (
            partition by case_id, role, name_normalized
            order by updated_at desc, created_at desc, entity_id asc
        ) as rn
    from parties.entities
    where name_normalized is not null
)

delete from parties.entities e
using ranked r
where
    e.entity_id = r.entity_id
    and r.rn > 1;

update parties.entities
set name_normalized = 'hash_' || md5(entity_id::text)
where name_normalized is null;

alter table parties.entities
alter column name_normalized set not null;

drop index if exists ux_entities_case_role_name_norm;
create unique index ux_entities_case_role_name_norm
on parties.entities (case_id, role, name_normalized);

-- Ensure cases share a deterministic org_id when one is not provided
alter table judgments.cases
alter column org_id set default '00000000-0000-0000-0000-000000000000'::uuid;

update judgments.cases
set org_id = '00000000-0000-0000-0000-000000000000'::uuid
where org_id is null;

update judgments.cases
set case_number = upper(btrim(case_number))
where case_number is not null;

-- Canonical insert for cases
create or replace function public.insert_case(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  v_payload jsonb := coalesce(payload, '{}'::jsonb);
  v_case_id uuid;
  v_org_id uuid := coalesce(nullif(v_payload->>'org_id', '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid);
  v_case_number text := upper(trim(coalesce(v_payload->>'case_number', '')));
  v_source text := coalesce(nullif(v_payload->>'source', ''), 'unknown');
  v_title text := v_payload->>'title';
  v_court text := v_payload->>'court';
  v_filing_date date := nullif(v_payload->>'filing_date', '')::date;
  v_judgment_date date := nullif(v_payload->>'judgment_date', '')::date;
  v_amount numeric := nullif(v_payload->>'amount_awarded', '')::numeric;
  v_currency text := coalesce(nullif(v_payload->>'currency', ''), 'USD');
  v_has_source_system boolean;
begin
  if v_case_number is null or v_case_number = '' then
    raise exception 'payload.case.case_number is required';
  end if;

  v_payload := v_payload
    || jsonb_build_object(
      'case_number', v_case_number,
      'source', v_source,
      'currency', v_currency,
      'org_id', v_org_id::text
    );

  select exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source_system'
  )
  into v_has_source_system;

  if v_has_source_system then
    insert into judgments.cases (
      org_id,
      case_number,
      source,
      source_system,
      title,
      court,
      filing_date,
      judgment_date,
      amount_awarded,
      currency,
      raw
    )
    values (
      v_org_id,
      v_case_number,
      v_source,
      v_source,
      v_title,
      v_court,
      v_filing_date,
      v_judgment_date,
      v_amount,
      v_currency,
      v_payload
    )
    returning case_id into v_case_id;
  else
    insert into judgments.cases (
      org_id,
      case_number,
      source,
      title,
      court,
      filing_date,
      judgment_date,
      amount_awarded,
      currency,
      raw
    )
    values (
      v_org_id,
      v_case_number,
      v_source,
      v_title,
      v_court,
      v_filing_date,
      v_judgment_date,
      v_amount,
      v_currency,
      v_payload
    )
    returning case_id into v_case_id;
  end if;

  return v_case_id;
end;
$$;

grant execute on function public.insert_case(jsonb) to anon,
authenticated,
service_role;

-- Idempotent case lookup
create or replace function public.insert_or_get_case(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  v_payload jsonb := coalesce(payload, '{}'::jsonb);
  v_case_id uuid;
  v_existing_org uuid;
  v_org_id uuid := coalesce(nullif(v_payload->>'org_id', '')::uuid, '00000000-0000-0000-0000-000000000000'::uuid);
  v_source text := coalesce(nullif(v_payload->>'source', ''), 'unknown');
  v_case_number text := upper(trim(coalesce(v_payload->>'case_number', '')));
begin
  if v_case_number is null or v_case_number = '' then
    raise exception 'payload.case.case_number is required';
  end if;

  v_payload := v_payload
    || jsonb_build_object(
      'case_number', v_case_number,
      'source', v_source,
      'org_id', v_org_id::text
    );

  select c.case_id, c.org_id
  into v_case_id, v_existing_org
  from judgments.cases c
  where c.case_number = v_case_number
    and c.source = v_source
  order by c.created_at desc
  limit 1;

  if v_case_id is not null then
    if v_existing_org is distinct from v_org_id then
      update judgments.cases
      set org_id = v_org_id
      where case_id = v_case_id;
    end if;
    return v_case_id;
  end if;

  begin
    v_case_id := public.insert_case(v_payload);

    update judgments.cases c
    set org_id = v_org_id
    where c.case_id = v_case_id;

    return v_case_id;
  exception
    when unique_violation then
      select c.case_id
      into v_case_id
      from judgments.cases c
      where c.case_number = v_case_number
        and c.source = v_source
      order by c.created_at desc
      limit 1;

      if v_case_id is null then
        raise;
      end if;

      update judgments.cases
      set org_id = v_org_id
      where case_id = v_case_id;

      return v_case_id;
  end;
end;
$$;
grant execute on function public.insert_or_get_case(jsonb) to anon,
authenticated,
service_role;

-- Upsert entity helper
create or replace function public.insert_entity(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  entity_payload jsonb := coalesce(payload, '{}'::jsonb);
  v_case_id uuid := (entity_payload->>'case_id')::uuid;
  v_role text := coalesce(nullif(lower(entity_payload->>'role'), ''), 'defendant');
  v_name text := coalesce(
    nullif(entity_payload->>'name_full', ''),
    nullif(entity_payload->>'name', ''),
    nullif(entity_payload->>'business_name', ''),
    nullif(trim(concat_ws(' ', nullif(entity_payload->>'first_name', ''), nullif(entity_payload->>'last_name', ''))), '')
  );
  v_name_normalized text;
  v_entity_id uuid;
begin
  if v_case_id is null then
    raise exception 'payload.case_id is required';
  end if;

  if v_role not in ('plaintiff', 'defendant', 'garnishee', 'other') then
    v_role := 'defendant';
  end if;

  if v_name is null then
    v_name := 'Unknown ' || substr(md5(entity_payload::text), 1, 12);
  end if;

  v_name_normalized := public.normalize_party_name(v_name);

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
    raw,
    name_normalized
  )
  values (
    v_case_id,
    v_role,
    coalesce(entity_payload->>'name_full', v_name),
    entity_payload->>'first_name',
    entity_payload->>'last_name',
    entity_payload->>'business_name',
    entity_payload->>'ein_or_ssn',
    entity_payload->'address',
    entity_payload->'phones',
    entity_payload->'emails',
    entity_payload,
    v_name_normalized
  )
  on conflict (case_id, role, name_normalized)
  do update
    set name_full = excluded.name_full,
        first_name = excluded.first_name,
        last_name = excluded.last_name,
        business_name = excluded.business_name,
        ein_or_ssn = excluded.ein_or_ssn,
        address = excluded.address,
        phones = excluded.phones,
        emails = excluded.emails,
        raw = excluded.raw,
        updated_at = now()
  returning entity_id into v_entity_id;

  return v_entity_id;
end;
$$;

grant execute on function public.insert_entity(jsonb) to anon,
authenticated,
service_role;

-- Idempotent case and entity bundle
create or replace function public.insert_or_get_case_with_entities(
    payload jsonb
)
returns jsonb
language plpgsql
security definer
as $$
declare
  case_payload jsonb := coalesce(payload->'case', '{}'::jsonb);
  entities_payload jsonb := coalesce(payload->'entities', '[]'::jsonb);
  created_case uuid;
  entity_ids uuid[] := '{}';
  entity_record jsonb;
  entity_id uuid;
  case_number text;
  case_source text;
  case_court text;
  case_title text;
  case_amount numeric;
  case_judgment_date date;
  case_org uuid;
begin
  if case_payload->>'case_number' is null or btrim(case_payload->>'case_number') = '' then
    raise exception 'payload.case.case_number is required';
  end if;

  created_case := public.insert_or_get_case(case_payload);

  select c.case_number, c.source, c.court, c.title, c.amount_awarded, c.judgment_date, c.org_id
  into case_number, case_source, case_court, case_title, case_amount, case_judgment_date, case_org
  from judgments.cases c
  where c.case_id = created_case;

  for entity_record in
    select jsonb_array_elements(entities_payload)
  loop
    entity_id := public.insert_entity(
      entity_record || jsonb_build_object('case_id', created_case)
    );

    if entity_id is not null and not (entity_ids @> array[entity_id]) then
      entity_ids := array_append(entity_ids, entity_id);
    end if;
  end loop;

  return jsonb_build_object(
    'case', jsonb_build_object(
      'case_id', created_case,
      'case_number', case_number,
      'source', case_source,
      'court', case_court,
      'org_id', case_org,
      'title', case_title,
      'amount_awarded', case_amount,
      'judgment_date', case_judgment_date
    ),
    'case_id', created_case,
    'case_number', case_number,
    'source', case_source,
    'court', case_court,
    'title', case_title,
    'amount_awarded', case_amount,
    'judgment_date', case_judgment_date,
    'entities', (
      select coalesce(jsonb_agg(
        jsonb_build_object(
          'entity_id', e.entity_id,
          'role', e.role,
          'name_full', e.name_full,
          'name_normalized', e.name_normalized
        )
        order by e.role, e.name_full, e.entity_id
      ), '[]'::jsonb)
      from parties.entities e
      where e.case_id = created_case
    ),
    'entity_ids', coalesce(to_jsonb(entity_ids), '[]'::jsonb),
    'meta', jsonb_build_object(
      'inserted_entities', coalesce(array_length(entity_ids, 1), 0)
    )
  );
end;
$$;

grant execute on function public.insert_or_get_case_with_entities(
    jsonb
) to anon,
authenticated,
service_role;

create or replace function public.insert_case_with_entities(payload jsonb)
returns jsonb
language sql
security definer
as $$
  select public.insert_or_get_case_with_entities(payload);
$$;

grant execute on function public.insert_case_with_entities(jsonb) to anon,
authenticated,
service_role;
