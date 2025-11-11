-- 0028_ingestion_runs_reconcile.sql

-- 1) Make sure the base table has both columns and the right nullability
create schema if not exists ingestion;

-- Add event column if missing
do $$
begin
  if not exists (
    select 1
    from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'event'
  ) then
    alter table ingestion.runs add column event text;
  end if;
end
$$;

-- Relax legacy NOT NULL on source_code so new writes don't fail
do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'ingestion'
      and table_name = 'runs'
      and column_name = 'source_code'
  ) then
    begin
      alter table ingestion.runs
        alter column source_code drop not null;
    exception when others then
      null;
    end;
  end if;
end
$$;

-- 2) Recreate triggers to populate BOTH event and source_code for compatibility
create or replace function public.log_insert_case()
returns trigger
language plpgsql
security definer
as $$
begin
  insert into ingestion.runs(event, source_code, ref_id, payload)
  values ('insert_case', 'insert_case', new.case_id, new.raw);
  return new;
end;
$$;

create or replace function public.log_insert_entity()
returns trigger
language plpgsql
security definer
as $$
begin
  insert into ingestion.runs(event, source_code, ref_id, payload)
  values ('insert_entity', 'insert_entity', new.entity_id, new.raw);
  return new;
end;
$$;

drop trigger if exists trg_log_case on judgments.cases;
create trigger trg_log_case
  after insert on judgments.cases
  for each row execute function public.log_insert_case();

drop trigger if exists trg_log_entity on parties.entities;
create trigger trg_log_entity
  after insert on parties.entities
  for each row execute function public.log_insert_entity();

-- 3) (Re)create a simple public view; drop first to allow column list changes
drop view if exists public.v_ingestion_runs cascade;

create view public.v_ingestion_runs as
  select
    coalesce(run_id, id) as run_id,
    event,
    source_code,
    ref_id,
    created_at
  from ingestion.runs
  order by created_at desc;

grant select on public.v_ingestion_runs to service_role;
