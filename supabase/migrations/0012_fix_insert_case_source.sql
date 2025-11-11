-- 0012_fix_insert_case_source.sql

create schema if not exists judgments;
create extension if not exists pgcrypto schema extensions;

-- Ensure raw column exists
do $$
begin
  if not exists (
    select 1
    from information_schema.columns
    where table_schema='judgments'
      and table_name='cases'
      and column_name='raw'
  ) then
    alter table judgments.cases add column raw jsonb;
  end if;
end $$;

-- Ensure org_id default remains

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema='judgments'
      and table_name='cases'
      and column_name='org_id'
  ) then
    alter table judgments.cases
      alter column org_id set default extensions.gen_random_uuid();
  end if;
end $$;

-- Replace RPC to set source_system fallback
drop function if exists public.insert_case(jsonb);
drop function if exists public.insert_case(text, text, text, numeric, text, text);

create or replace function public.insert_case(payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_case_id uuid;
  v_case_number text;
  v_source_system text;
begin
  v_case_number := nullif(payload->>'case_number', '');
  if v_case_number is null then
    v_case_number := nullif(payload->>'docket_number', '');
  end if;
  if v_case_number is null then
    v_case_number := nullif(payload->>'index_no', '');
  end if;
  if v_case_number is null then
    v_case_number := encode(extensions.gen_random_bytes(6), 'hex');
  end if;

  v_source_system := nullif(payload->>'source', '');
  if v_source_system is null then
    v_source_system := 'rpc';
  end if;

  insert into judgments.cases (
    org_id,
    case_number,
    source_system,
    raw
  )
  values (
    coalesce((payload->>'org_id')::uuid, extensions.gen_random_uuid()),
    v_case_number,
    v_source_system,
    payload
  )
  returning case_id into v_case_id;

  return v_case_id;
end
$$;
grant execute on function public.insert_case(jsonb) to anon, authenticated, service_role;
