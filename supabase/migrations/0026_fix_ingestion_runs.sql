-- 0026_fix_ingestion_runs.sql

-- A) Ensure table shape
create schema if not exists ingestion;

create table if not exists ingestion.runs (
    run_id uuid primary key default gen_random_uuid(),
    event text not null,
    ref_id uuid,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default now()
);

-- Add missing columns if table exists already
do $$
begin
  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'run_id'
  ) then
    alter table ingestion.runs add column run_id uuid;
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'event'
  ) then
    alter table ingestion.runs add column event text;
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'ref_id'
  ) then
    alter table ingestion.runs add column ref_id uuid;
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'payload'
  ) then
    alter table ingestion.runs
      add column payload jsonb not null default '{}'::jsonb;
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'source_code'
  ) then
    alter table ingestion.runs add column source_code text;
  end if;

  if not exists (
    select 1 from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'created_at'
  ) then
    alter table ingestion.runs
      add column created_at timestamptz not null default now();
  end if;
end
$$;

-- Normalize column defaults and nullability
update ingestion.runs
set
    run_id = coalesce(run_id, gen_random_uuid()),
    event = coalesce(event, 'unknown'),
    payload = coalesce(payload, '{}'::jsonb),
    created_at = coalesce(created_at, now()),
    source_code = coalesce(source_code, 'rpc');

alter table ingestion.runs
alter column run_id set default gen_random_uuid(),
alter column run_id set not null,
alter column payload set default '{}'::jsonb,
alter column payload set not null,
alter column source_code set default 'rpc',
alter column source_code set not null,
alter column created_at set default now(),
alter column created_at set not null;

-- Ensure primary key on run_id
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'ingestion.runs'::regclass
      and contype = 'p'
  ) then
    alter table ingestion.runs add primary key (run_id);
  end if;
end
$$;

-- B) (Re)create trigger functions to log inserts
create or replace function public.log_insert_case()
returns trigger
language plpgsql
security definer
as $$
begin
  insert into ingestion.runs(event, ref_id, payload, source_code)
  values ('insert_case', new.case_id, new.raw, 'rpc');
  return new;
end;
$$;

create or replace function public.log_insert_entity()
returns trigger
language plpgsql
security definer
as $$
begin
  insert into ingestion.runs(event, ref_id, payload, source_code)
  values ('insert_entity', new.entity_id, new.raw, 'rpc');
  return new;
end;
$$;

-- Attach triggers idempotently
drop trigger if exists trg_log_case on judgments.cases;
create trigger trg_log_case
after insert on judgments.cases
for each row execute function public.log_insert_case();

drop trigger if exists trg_log_entity on parties.entities;
create trigger trg_log_entity
after insert on parties.entities
for each row execute function public.log_insert_entity();

-- C) Restrict base table; expose a public view for REST reads
revoke all on table ingestion.runs from public;

do $$
begin
  if exists (
    select 1 from information_schema.views
    where table_schema = 'public'
      and table_name = 'v_ingestion_runs'
  ) then
    drop view public.v_ingestion_runs;
  end if;
end
$$;

create view public.v_ingestion_runs as
select
    run_id,
    event,
    ref_id,
    source_code,
    created_at
from ingestion.runs
order by created_at desc;

grant select on public.v_ingestion_runs to service_role;

