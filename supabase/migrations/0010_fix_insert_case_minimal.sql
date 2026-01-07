-- 0010_fix_insert_case_minimal.sql

-- Ensure judgments schema exists
create schema if not exists judgments;

-- Make sure pgcrypto is available for gen_random_uuid()
create extension if not exists pgcrypto schema extensions;

-- 1) Ensure a raw jsonb column exists (to stash whatever the caller sends)
do $$

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
-- 2) Ensure org_id has a default
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

-- 3) Replace RPC to only insert columns that always exist
begin
create or replace function public.insert_case(payload jsonb)
returns uuid
language plpgsql
security definer
set search_path = public
as $$
declare
  v_case_id uuid;
  v_case_number text;

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

  insert into judgments.cases (
    org_id,
    case_number,
    raw
  )
  values (
    coalesce((payload->>'org_id')::uuid, extensions.gen_random_uuid()),
    v_case_number,
    payload
  )
  returning case_id into v_case_id;

  return v_case_id;
end
$$;
-- 4) Make sure callers can execute it
grant execute on function public.insert_case(jsonb) to anon, authenticated, service_role;

