-- 0023_ingestion_audit.sql

-- Ensure dedicated schema for ingestion telemetry
create schema if not exists ingestion;

-- Minimal audit log for RPC-driven inserts
create table if not exists ingestion.runs (
  run_id uuid primary key default gen_random_uuid(),
  event text not null,
  ref_id uuid,
  payload jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

alter table ingestion.runs
  add column if not exists event text,
  add column if not exists ref_id uuid,
  add column if not exists payload jsonb,
  add column if not exists created_at timestamptz;

update ingestion.runs
set
  event = coalesce(event, 'unknown'),
  payload = coalesce(payload, '{}'::jsonb),
  created_at = coalesce(created_at, now());

alter table ingestion.runs
  alter column event set not null,
  alter column ref_id drop not null,
  alter column payload set default '{}'::jsonb,
  alter column payload set not null,
  alter column created_at set default now(),
  alter column created_at set not null;

-- Trigger function: log case inserts
create or replace function public.log_insert_case()
returns trigger
language plpgsql
as $$
begin
  insert into ingestion.runs(event, ref_id, payload)
  values ('insert_case', new.case_id, new.raw);
  return new;
end;
$$;

-- Trigger function: log entity inserts
create or replace function public.log_insert_entity()
returns trigger
language plpgsql
as $$
begin
  insert into ingestion.runs(event, ref_id, payload)
  values ('insert_entity', new.entity_id, new.raw);
  return new;
end;
$$;

-- Attach triggers (idempotent)
do $$
begin
  if not exists (
    select 1 from pg_trigger
    where tgname = 'trg_log_case'
      and tgrelid = 'judgments.cases'::regclass
  ) then
    create trigger trg_log_case
      after insert on judgments.cases
      for each row execute function public.log_insert_case();
  end if;

  if not exists (
    select 1 from pg_trigger
    where tgname = 'trg_log_entity'
      and tgrelid = 'parties.entities'::regclass
  ) then
    create trigger trg_log_entity
      after insert on parties.entities
      for each row execute function public.log_insert_entity();
  end if;
end;
$$;

-- Service role only; app clients read audit via service entrypoints
revoke all on ingestion.runs from public;
revoke all on ingestion.runs from anon;
revoke all on ingestion.runs from authenticated;
grant select on ingestion.runs to service_role;
