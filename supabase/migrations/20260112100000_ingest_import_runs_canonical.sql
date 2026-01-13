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
BEGIN;
-- ===========================================================================
-- STEP 1: Create schema if missing
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS ingest;
COMMENT ON SCHEMA ingest IS 'Ingestion tracking schema for exactly-once batch processing.';
-- ===========================================================================
-- STEP 2: Create enum type if missing (idempotent via DO block)
-- ===========================================================================
DO $$ BEGIN IF NOT EXISTS (
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
CREATE TABLE IF NOT EXISTS ingest.import_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_batch_id text NOT NULL,
    file_hash text NOT NULL,
    status ingest.import_run_status NOT NULL DEFAULT 'pending',
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    record_count integer,
    error_details jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT import_runs_source_batch_unique UNIQUE (source_batch_id)
);
COMMENT ON TABLE ingest.import_runs IS 'Tracks ingestion batches for exactly-once processing and crash recovery.';
COMMENT ON COLUMN ingest.import_runs.source_batch_id IS 'Caller-provided unique identifier (e.g., filename, S3 key).';
COMMENT ON COLUMN ingest.import_runs.file_hash IS 'SHA-256 hash of the source file for duplicate detection.';
-- ===========================================================================
-- STEP 4: Add missing columns if table existed without them (idempotent)
-- MUST run before any index/trigger that references these columns
-- ===========================================================================
DO $$ BEGIN -- Add created_at if missing
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
DO $$ BEGIN IF EXISTS (
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
CREATE INDEX IF NOT EXISTS idx_import_runs_source_batch_id ON ingest.import_runs (source_batch_id);
CREATE INDEX IF NOT EXISTS idx_import_runs_file_hash ON ingest.import_runs (file_hash);
CREATE INDEX IF NOT EXISTS idx_import_runs_status_active ON ingest.import_runs (status)
WHERE status IN ('pending', 'processing');
-- Guard: only create updated_at index if column exists
DO $$ BEGIN IF EXISTS (
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
CREATE OR REPLACE FUNCTION ingest.set_updated_at() RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = ingest AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
-- ===========================================================================
-- STEP 7: Create trigger if missing (guarded on column existence)
-- ===========================================================================
DO $$ BEGIN -- Only create trigger if updated_at column exists
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
ALTER TABLE ingest.import_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest.import_runs FORCE ROW LEVEL SECURITY;
-- ===========================================================================
-- STEP 9: Drop and recreate policy (ensures clean state, idempotent)
-- ===========================================================================
DROP POLICY IF EXISTS import_runs_service_role_full ON ingest.import_runs;
CREATE POLICY import_runs_service_role_full ON ingest.import_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ===========================================================================
-- STEP 10: Revoke public access, grant to service_role only
-- ===========================================================================
REVOKE ALL ON SCHEMA ingest
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA ingest
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ingest
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL ROUTINES IN SCHEMA ingest
FROM PUBLIC,
    anon,
    authenticated;
GRANT USAGE ON SCHEMA ingest TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE ingest.import_runs TO service_role;
GRANT EXECUTE ON FUNCTION ingest.set_updated_at() TO service_role;
-- ===========================================================================
-- STEP 11: Set default privileges for future objects
-- ===========================================================================
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest REVOKE ALL ON TABLES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest REVOKE ALL ON SEQUENCES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest REVOKE ALL ON ROUTINES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest
GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest
GRANT EXECUTE ON ROUTINES TO service_role;
-- ===========================================================================
-- STEP 12: Helper function for claiming stale jobs (stale takeover logic)
-- ===========================================================================
CREATE OR REPLACE FUNCTION ingest.claim_stale_job(
        p_stale_threshold interval DEFAULT interval '10 minutes'
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest AS $$
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
REVOKE ALL ON FUNCTION ingest.claim_stale_job(interval)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ingest.claim_stale_job(interval) TO service_role;
DO $$ BEGIN RAISE NOTICE '✓ ingest.import_runs canonical migration complete';
END $$;
COMMIT;
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