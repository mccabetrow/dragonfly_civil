-- supabase/migrations/0009_org_default_and_rpc.sql

-- Ensure schema and required extension exist
create schema if not exists judgments;
create extension if not exists pgcrypto schema extensions;

-- 1) Give org_id a default so inserts without org_id succeed
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

-- 2) RPC: accept optional org_id in payload; generate if missing
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
begin
  insert into judgments.cases (
    org_id,
    case_number,
    court,
    filing_date,
    amount,
    source,
    raw
  )
  values (
    coalesce((payload->>'org_id')::uuid, extensions.gen_random_uuid()),
    payload->>'case_number',
    payload->>'court',
    (payload->>'filing_date')::date,
    (payload->>'amount')::numeric,
    payload->>'source',
    payload
  )
  returning case_id into v_case_id;

  return v_case_id;
end
$$;

-- 3) Grant execute (so PostgREST/RLS paths work)
grant execute on function public.insert_case(jsonb) to anon, authenticated, service_role;
