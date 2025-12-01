-- 0027_ingestion_runs_backfill.sql

-- Ensure source_code column exists and has default for existing environments
alter table ingestion.runs
add column if not exists source_code text;

update ingestion.runs
set source_code = coalesce(source_code, 'rpc');

alter table ingestion.runs
alter column source_code set default 'rpc',
alter column source_code set not null;

-- Refresh logging trigger functions to populate source_code explicitly
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

-- Recreate triggers to ensure updated functions are wired
drop trigger if exists trg_log_case on judgments.cases;
create trigger trg_log_case
after insert on judgments.cases
for each row execute function public.log_insert_case();

drop trigger if exists trg_log_entity on parties.entities;
create trigger trg_log_entity
after insert on parties.entities
for each row execute function public.log_insert_entity();

drop view if exists public.v_ingestion_runs;

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
