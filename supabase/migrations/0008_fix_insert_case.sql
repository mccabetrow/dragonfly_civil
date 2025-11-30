-- 0008_fix_insert_case.sql
-- Make sure the target table has the columns we insert into.
create schema if not exists judgments;

-- If your base table is already present, this will only add missing columns.
create table if not exists judgments.cases (
    case_id uuid primary key default gen_random_uuid()
);

alter table judgments.cases
add column if not exists case_id uuid,
add column if not exists index_no text,
add column if not exists court text,
add column if not exists county text,
add column if not exists principal_amt numeric,
add column if not exists status text,
add column if not exists source text,
add column if not exists created_at timestamptz default now();

-- Ensure every existing row has a case_id populated
update judgments.cases
set case_id = coalesce(case_id, gen_random_uuid());

alter table judgments.cases
alter column case_id set default gen_random_uuid();

do $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'judgments.cases'::regclass
      AND contype = 'p'
  ) THEN
    ALTER TABLE judgments.cases
      ADD CONSTRAINT cases_case_id_pk PRIMARY KEY (case_id);
  END IF;
END
$$ language plpgsql;

-- Optional: uniqueness if your workflow expects it (comment out if unsure)
-- create unique index if not exists cases_index_no_unique on judgments.cases (lower(index_no));

-- Public read wrapper (view) that our client hits via /v_cases
drop view if exists public.v_cases cascade;

create view public.v_cases as
select
    c.case_id,
    c.index_no,
    c.court,
    c.county,
    c.principal_amt,
    c.status,
    c.source,
    c.created_at
from judgments.cases as c;

grant select on public.v_cases to anon, authenticated, service_role;

-- Recreate the RPC to accept JSONB payload and map into judgments.cases explicitly.
drop function if exists public.insert_case (jsonb);
drop function if exists public.insert_case (
    text, text, text, numeric, text, text
);

create or replace function public.insert_case(payload jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  _case_id uuid;
begin
  insert into judgments.cases (index_no, court, county, principal_amt, status, source)
  values (
    payload->>'index_no',
    payload->>'court',
    payload->>'county',
    nullif(payload->>'principal_amt','')::numeric,
    coalesce(nullif(payload->>'status',''),'new'),
    payload->>'source'
  )
  returning case_id into _case_id;

  return jsonb_build_object('case_id', _case_id);
end
$$;

-- Convenience overload so named-args + Prefer: params=single-object also works
create or replace function public.insert_case(
    index_no text,
    court text,
    county text,
    principal_amt numeric,
    status text,
    source text
) returns jsonb
language sql
security definer
set search_path = public
as $$
  select public.insert_case(jsonb_build_object(
    'index_no',      $1,
    'court',         $2,
    'county',        $3,
    'principal_amt', $4,
    'status',        $5,
    'source',        $6
  ));
$$;

grant execute on function public.insert_case(jsonb) to anon,
authenticated,
service_role;
grant execute on function public.insert_case(
    text, text, text, numeric, text, text
) to anon,
authenticated,
service_role;
