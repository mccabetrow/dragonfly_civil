-- 20261101_ingestion_idempotency.sql
-- Ensure ingestion runs are tracked exactly-once per batch/file
set check_function_bodies = off;
-- ---------------------------------------------------------------------------
-- Schema + Type setup
-- ---------------------------------------------------------------------------
create schema if not exists ingest;
do $$ begin if not exists (
    select 1
    from pg_type t
        join pg_namespace n on n.oid = t.typnamespace
    where n.nspname = 'ingest'
        and t.typname = 'import_run_status'
) then create type ingest.import_run_status as enum ('pending', 'processing', 'completed', 'failed');
end if;
end;
$$;
-- ---------------------------------------------------------------------------
-- Table definition
-- ---------------------------------------------------------------------------
create table if not exists ingest.import_runs (
    id uuid primary key default gen_random_uuid(),
    source_batch_id text not null,
    file_hash text not null,
    status ingest.import_run_status not null default 'pending',
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    record_count integer,
    error_details jsonb,
    constraint import_runs_source_batch_unique unique (source_batch_id)
);
comment on table ingest.import_runs is 'Tracks ingestion batches for exactly-once processing and crash recovery.';
comment on column ingest.import_runs.source_batch_id is 'Caller-provided unique identifier (e.g., filename, S3 key).';
-- ---------------------------------------------------------------------------
-- Security + RLS
-- ---------------------------------------------------------------------------
grant usage on schema ingest to service_role;
grant select,
    insert,
    update on table ingest.import_runs to service_role;
alter table ingest.import_runs enable row level security;
alter table ingest.import_runs force row level security;
create policy import_runs_service_role_full on ingest.import_runs for all to service_role using (true) with check (true);