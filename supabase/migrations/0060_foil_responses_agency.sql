-- 0060_foil_responses_agency.sql
-- Normalize foil_responses into judgments schema and add missing columns.

-- migrate:up

drop view if exists public.foil_responses;

do $$
declare
  relkind char;
begin
  select c.relkind
    into relkind
  from pg_class c
  join pg_namespace n on n.oid = c.relnamespace
  where n.nspname = 'judgments'
    and c.relname = 'foil_responses';

  if relkind in ('v', 'm') then
    execute 'drop view if exists judgments.foil_responses cascade';
    relkind := null;
  end if;

  if relkind is null then
    if exists (
      select 1
      from pg_class c
      join pg_namespace n on n.oid = c.relnamespace
      where n.nspname = 'public'
        and c.relname = 'foil_responses'
        and c.relkind = 'r'
    ) then
      execute 'alter table public.foil_responses set schema judgments';
    else
      execute '
        create table judgments.foil_responses (
          id            bigserial primary key,
          case_id       uuid not null references judgments.cases(case_id) on delete cascade,
          created_at    timestamptz not null default timezone(''utc'', now()),
          received_date date,
          agency        text,
          payload       jsonb not null
        )
      ';
    end if;
  end if;
end
$$;

-- 2) Ensure required columns exist on judgments.foil_responses.
alter table judgments.foil_responses
add column if not exists created_at timestamptz not null default timezone(
    'utc', now()
),
add column if not exists received_date date,
add column if not exists agency text,
add column if not exists payload jsonb;

alter table judgments.foil_responses
alter column created_at set default timezone('utc', now()),
alter column created_at set not null,
alter column payload set not null;

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'foil_responses'
      and column_name = 'source_agency'
  ) then
    execute 'update judgments.foil_responses set agency = coalesce(agency, source_agency)';
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'foil_responses'
      and column_name = 'response_date'
  ) then
    execute 'update judgments.foil_responses set received_date = coalesce(received_date, response_date)';
  end if;
end
$$;

alter table judgments.foil_responses
drop column if exists source_agency,
drop column if exists request_id,
drop column if exists response_date;

create index if not exists idx_judgments_foil_responses_agency_date on judgments.foil_responses (
    agency, received_date
);

-- 3) Recreate the public view to match the table shape.
create or replace view public.foil_responses as
select
    id,
    case_id,
    created_at,
    received_date,
    agency,
    payload
from judgments.foil_responses;

revoke all on public.foil_responses from public;
revoke all on public.foil_responses from anon;
revoke all on public.foil_responses from authenticated;
grant select on public.foil_responses to service_role;

-- migrate:down

-- Keep the table and just roll back the added columns + view.
drop view if exists public.foil_responses;

alter table judgments.foil_responses
add column if not exists source_agency text,
add column if not exists request_id text,
add column if not exists response_date date;

update judgments.foil_responses
set
    source_agency = coalesce(source_agency, agency),
    response_date = coalesce(response_date, received_date);

alter table judgments.foil_responses
drop column if exists agency,
drop column if exists received_date;

create or replace view public.foil_responses as
select
    id,
    case_id,
    source_agency,
    request_id,
    response_date,
    payload,
    created_at
from judgments.foil_responses;

revoke all on public.foil_responses from public;
revoke all on public.foil_responses from anon;
revoke all on public.foil_responses from authenticated;
grant select on public.foil_responses to service_role;

