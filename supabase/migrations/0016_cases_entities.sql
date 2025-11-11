-- Ensure schema
create schema if not exists judgments;
create schema if not exists parties;

-- A.3 judgments.cases
alter table judgments.cases
  add column if not exists case_id uuid;

alter table judgments.cases
  alter column case_id set default gen_random_uuid();

alter table judgments.cases
  alter column case_id set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'judgments.cases'::regclass
      and contype = 'p'
  ) then
    alter table judgments.cases
      add constraint cases_pkey primary key (case_id);
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source_system'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source'
  ) then
    alter table judgments.cases rename column source_system to source;
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'court_name'
  ) and not exists (
    select 1 from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'court'
  ) then
    alter table judgments.cases rename column court_name to court;
  end if;
end $$;

alter table judgments.cases
  add column if not exists filing_date date;

alter table judgments.cases
  add column if not exists judgment_date date;

alter table judgments.cases
  add column if not exists amount_awarded numeric(14,2);

alter table judgments.cases
  add column if not exists currency text;

update judgments.cases
set currency = 'USD'
where currency is null;

alter table judgments.cases
  alter column currency set default 'USD';

alter table judgments.cases
  add column if not exists raw jsonb;

update judgments.cases
set raw = coalesce(raw, '{}'::jsonb);

alter table judgments.cases
  alter column raw set default '{}'::jsonb;

alter table judgments.cases
  alter column raw set not null;

create table if not exists judgments.cases (
  case_id         uuid primary key default gen_random_uuid(),
  org_id          uuid not null default gen_random_uuid(), -- temp default for smoke; later tie to orgs table
  case_number     text not null,
  source          text not null,              -- e.g. 'webcivil_local','nyscef','vendor'
  title           text,                       -- caption, "Smith v. Jones"
  court           text,                       -- human-friendly court name
  filing_date     date,
  judgment_date   date,
  amount_awarded  numeric(14,2),
  currency        text default 'USD',
  raw             jsonb not null default '{}'::jsonb,  -- full inbound payload
  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

-- Updater trigger
create or replace function public.tg_touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end$$;

drop trigger if exists trg_cases_touch on judgments.cases;
create trigger trg_cases_touch before update on judgments.cases
for each row execute function public.tg_touch_updated_at();

drop view if exists public.v_cases_with_org;

create or replace view public.v_cases_with_org as
select
  c.case_id,
  c.org_id,
  c.case_number,
  c.source,
  c.title,
  c.court,
  c.created_at
from judgments.cases c;

-- Grants (keep aligned with your screenshot)
grant usage on schema public, judgments, parties to anon, authenticated, service_role;
grant select on public.v_cases_with_org to anon, authenticated, service_role;
grant select, insert, update on judgments.cases to service_role; -- anon/auth insert goes via RPC

-- RPC (idempotent) - matches your "wrap under payload" rule
create or replace function public.insert_case(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  new_id uuid;
  has_source_system boolean;

  select exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source_system'
  ) into has_source_system;

  if has_source_system then
    insert into judgments.cases (
      case_number, source, source_system, title, court, filing_date, judgment_date,
      amount_awarded, currency, raw
    )
    values (
      payload->>'case_number',
      coalesce(payload->>'source','unknown'),
      coalesce(payload->>'source','unknown'),
      payload->>'title',
      payload->>'court',
      nullif(payload->>'filing_date','')::date,
      nullif(payload->>'judgment_date','')::date,
      nullif(payload->>'amount_awarded','')::numeric,
      coalesce(payload->>'currency','USD'),
      payload
    )
    returning case_id into new_id;
  else
    insert into judgments.cases (
      case_number, source, title, court, filing_date, judgment_date,
      amount_awarded, currency, raw
    )
    values (
      payload->>'case_number',
      coalesce(payload->>'source','unknown'),
      payload->>'title',
      payload->>'court',
      nullif(payload->>'filing_date','')::date,
      nullif(payload->>'judgment_date','')::date,
      nullif(payload->>'amount_awarded','')::numeric,
      coalesce(payload->>'currency','USD'),
      payload
    )
    returning case_id into new_id;
  end if;

  return new_id;
end $$;
revoke all on function public.insert_case(jsonb) from public;
grant execute on function public.insert_case(jsonb) to anon, authenticated, service_role;

-- postgrest schema cache refresh (service_role only)
create or replace function public.pgrst_reload()
returns void language sql security definer as $$
  select pg_notify('pgrst', 'reload schema');
$$;

revoke all on function public.pgrst_reload() from public;
grant execute on function public.pgrst_reload() to service_role;
