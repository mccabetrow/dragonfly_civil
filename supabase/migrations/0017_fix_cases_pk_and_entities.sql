-- 0017_fix_cases_pk_and_entities.sql

-- Ensure schemas
create schema if not exists judgments;
create schema if not exists parties;

-- Ensure case identifiers are populated, unique, and constrained
alter table if exists judgments.cases
add column if not exists case_id uuid default gen_random_uuid();

update judgments.cases
set case_id = gen_random_uuid()
where case_id is null;

with duplicates as (
    select ctid
    from (
        select
            ctid,
            row_number() over (partition by case_id order by ctid) as rn
        from judgments.cases
    ) as ranked
    where rn > 1
)

update judgments.cases c
set case_id = gen_random_uuid()
from duplicates as d
where c.ctid = d.ctid;

alter table judgments.cases
alter column case_id set not null;

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'judgments.cases'::regclass
      and conname = 'cases_case_id_key'
  ) then
    alter table judgments.cases
      add constraint cases_case_id_key unique (case_id);
  end if;
end $$;

-- Create parties.entities if missing

do $$
begin
  if not exists (
    select 1 from information_schema.tables
    where table_schema = 'parties' and table_name = 'entities'
  ) then
    create table parties.entities (
      entity_id     uuid primary key default gen_random_uuid(),
      org_id        uuid not null default gen_random_uuid(),
      case_id       uuid not null,
      role          text check (role in ('plaintiff','defendant','garnishee','other')),
      name_full     text,
      first_name    text,
      last_name     text,
      business_name text,
      ein_or_ssn    text,
      address       jsonb,
      phones        jsonb,
      emails        jsonb,
      raw           jsonb not null default '{}'::jsonb,
      created_at    timestamptz not null default now(),
      updated_at    timestamptz not null default now()
    );
  end if;
end $$;

-- Ensure foreign key to cases.case_id exists

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'entities_case_id_fkey'
      and conrelid = 'parties.entities'::regclass
  ) then
    alter table parties.entities
      add constraint entities_case_id_fkey
      foreign key (case_id)
      references judgments.cases(case_id)
      on delete cascade;
  end if;
end $$;

-- Maintain updated_at via shared trigger
create or replace function public.tg_touch_updated_at()
returns trigger language plpgsql as $$
begin new.updated_at = now(); return new; end$$;

drop trigger if exists trg_entities_touch on parties.entities;
create trigger trg_entities_touch
before update on parties.entities
for each row execute function public.tg_touch_updated_at();

grant select, insert, update on parties.entities to service_role;

