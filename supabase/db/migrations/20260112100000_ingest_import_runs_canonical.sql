-- =============================================================================
-- 20260112_ingest_import_runs_canonical.sql
-- Canonical migration for ingest.import_runs - FULLY IDEMPOTENT
-- =============================================================================
--
-- DESIGN PRINCIPLES:
-- 1. Every statement is rerunnable without errors
-- 2. Uses CREATE IF NOT EXISTS, DROP POLICY IF EXISTS, DO blocks
-- 3. Adds updated_at + trigger for stale takeover logic
-- 4. Enables RLS + FORCE RLS + service_role-only policy
-- 5. Guards index/trigger creation on column existence
--
-- Safe to run on fresh database OR existing database with partial state.
--
-- =============================================================================
begin;
-- ===========================================================================
-- STEP 1: Create schema if missing
-- ===========================================================================
create schema if not exists ingest;
comment on schema ingest is 'Ingestion tracking schema for exactly-once batch processing.';
-- ===========================================================================
-- STEP 2: Create enum type if missing (idempotent via DO block)
-- ===========================================================================
do $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'ingest'
        AND t.typname = 'import_run_status'
) THEN CREATE TYPE ingest.import_run_status AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed'
);
RAISE NOTICE '✓ Created enum ingest.import_run_status';
ELSE RAISE NOTICE '○ Enum ingest.import_run_status already exists';
END IF;
END $$;
-- ===========================================================================
-- STEP 3: Create table if missing
-- ===========================================================================
create table if not exists ingest.import_runs (
    id uuid primary key default gen_random_uuid(),
    source_batch_id text not null,
    file_hash text not null,
    status ingest.import_run_status not null default 'pending',
    started_at timestamptz not null default now(),
    completed_at timestamptz,
    record_count integer,
    error_details jsonb,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint import_runs_source_batch_unique unique (source_batch_id)
);
comment on table ingest.import_runs is 'Tracks ingestion batches for exactly-once processing and crash recovery.';
comment on column ingest.import_runs.source_batch_id is 'Caller-provided unique identifier (e.g., filename, S3 key).';
comment on column ingest.import_runs.file_hash is 'SHA-256 hash of the source file for duplicate detection.';
-- ===========================================================================
-- STEP 4: Add missing columns if table existed without them (idempotent)
-- MUST run before any index/trigger that references these columns
-- ===========================================================================
do $$ BEGIN -- Add created_at if missing
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'created_at'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN created_at timestamptz NOT NULL DEFAULT now();
RAISE NOTICE '✓ Added column created_at';
END IF;
-- Add updated_at if missing
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'updated_at'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN updated_at timestamptz NOT NULL DEFAULT now();
RAISE NOTICE '✓ Added column updated_at';
END IF;
END $$;
-- Add comment after column is guaranteed to exist
do $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'updated_at'
) THEN COMMENT ON COLUMN ingest.import_runs.updated_at IS 'Last modification timestamp for stale job takeover logic.';
END IF;
END $$;
-- ===========================================================================
-- STEP 5: Create indexes if missing (guarded on column existence)
-- ===========================================================================
create index if not exists idx_import_runs_source_batch_id on ingest.import_runs (source_batch_id);
create index if not exists idx_import_runs_file_hash on ingest.import_runs (file_hash);
create index if not exists idx_import_runs_status_active on ingest.import_runs (status)
where status in ('pending', 'processing');
-- Guard: only create updated_at index if column exists
do $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'updated_at'
) THEN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ingest'
        AND tablename = 'import_runs'
        AND indexname = 'idx_import_runs_updated_at'
) THEN CREATE INDEX idx_import_runs_updated_at ON ingest.import_runs (updated_at)
WHERE status = 'processing';
RAISE NOTICE '✓ Created index idx_import_runs_updated_at';
END IF;
ELSE RAISE WARNING '⚠ Column updated_at does not exist - skipping index';
END IF;
END $$;
-- ===========================================================================
-- STEP 6: Create updated_at trigger function (CREATE OR REPLACE is idempotent)
-- ===========================================================================
create or replace function ingest.set_updated_at() returns trigger language plpgsql
set search_path = ingest as $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
-- ===========================================================================
-- STEP 7: Create trigger if missing (guarded on column existence)
-- ===========================================================================
do $$ BEGIN -- Only create trigger if updated_at column exists
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'updated_at'
) THEN RAISE WARNING '⚠ Column updated_at does not exist - skipping trigger';
RETURN;
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgname = 'trg_import_runs_updated_at'
        AND tgrelid = 'ingest.import_runs'::regclass
) THEN CREATE TRIGGER trg_import_runs_updated_at BEFORE
UPDATE ON ingest.import_runs FOR EACH ROW EXECUTE FUNCTION ingest.set_updated_at();
RAISE NOTICE '✓ Created trigger trg_import_runs_updated_at';
ELSE RAISE NOTICE '○ Trigger trg_import_runs_updated_at already exists';
END IF;
END $$;
-- ===========================================================================
-- STEP 8: Enable RLS + FORCE RLS (safe to rerun)
-- ===========================================================================
alter table ingest.import_runs enable row level security;
alter table ingest.import_runs force row level security;
-- ===========================================================================
-- STEP 9: Drop and recreate policy (ensures clean state, idempotent)
-- ===========================================================================
drop policy if exists import_runs_service_role_full on ingest.import_runs;
create policy import_runs_service_role_full on ingest.import_runs for all to service_role using (true) with check (true);
-- ===========================================================================
-- STEP 10: Revoke public access, grant to service_role only
-- ===========================================================================
revoke all on schema ingest
from public,
anon,
authenticated;
revoke all on all tables in schema ingest
from public,
anon,
authenticated;
revoke all on all sequences in schema ingest
from public,
anon,
authenticated;
revoke all on all routines in schema ingest
from public,
anon,
authenticated;
grant usage on schema ingest to service_role;
grant select,
insert,
update,
delete on table ingest.import_runs to service_role;
grant execute on function ingest.set_updated_at() to service_role;
-- ===========================================================================
-- STEP 11: Set default privileges for future objects
-- ===========================================================================
alter default privileges in schema ingest revoke all on tables
from public,
anon,
authenticated;
alter default privileges in schema ingest revoke all on sequences
from public,
anon,
authenticated;
alter default privileges in schema ingest revoke all on routines
from public,
anon,
authenticated;
alter default privileges in schema ingest
grant all on tables to service_role;
alter default privileges in schema ingest
grant all on sequences to service_role;
alter default privileges in schema ingest
grant execute on routines to service_role;
-- ===========================================================================
-- STEP 12: Helper function for claiming stale jobs (stale takeover logic)
-- ===========================================================================
create or replace function ingest.claim_stale_job(
    p_stale_threshold interval default interval '10 minutes'
) returns uuid language plpgsql security definer
set search_path = ingest as $$
DECLARE v_job_id uuid;
BEGIN -- Claim oldest stale 'processing' job (worker crashed)
UPDATE ingest.import_runs
SET status = 'processing',
    updated_at = now()
WHERE id = (
        SELECT id
        FROM ingest.import_runs
        WHERE status = 'processing'
            AND updated_at < now() - p_stale_threshold
        ORDER BY updated_at ASC
        LIMIT 1 FOR
        UPDATE SKIP LOCKED
    )
RETURNING id INTO v_job_id;
RETURN v_job_id;
END;
$$;
revoke all on function ingest.claim_stale_job(interval)
from public;
grant execute on function ingest.claim_stale_job(interval) to service_role;
do $$ BEGIN RAISE NOTICE '✓ ingest.import_runs canonical migration complete';
END $$;
commit;
-- ===========================================================================
-- VERIFICATION QUERIES (run after migration)
-- ===========================================================================
/*
 -- Check table structure
 SELECT column_name, data_type, is_nullable
 FROM information_schema.columns
 WHERE table_schema = 'ingest' AND table_name = 'import_runs'
 ORDER BY ordinal_position;

 -- Check indexes
 SELECT indexname, indexdef
 FROM pg_indexes
 WHERE schemaname = 'ingest' AND tablename = 'import_runs';

 -- Check triggers
 SELECT tgname
 FROM pg_trigger
 WHERE tgrelid = 'ingest.import_runs'::regclass AND NOT tgisinternal;

 -- Check policies
 SELECT schemaname, tablename, policyname, permissive, roles, cmd
 FROM pg_policies
 WHERE schemaname = 'ingest';

 -- Check RLS status
 SELECT
 n.nspname AS schema,
 c.relname AS table_name,
 c.relrowsecurity AS rls_enabled,
 c.relforcerowsecurity AS rls_forced
 FROM pg_class c
 JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE n.nspname = 'ingest' AND c.relkind = 'r';
 */
-- ===========================================================================
