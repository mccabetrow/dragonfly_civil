-- =============================================================================
-- 20260112_003_ingest_idempotent_rls.sql
-- Ensure ingest.import_runs RLS + policies are fully idempotent
-- =============================================================================
--
-- DESIGN PRINCIPLES:
-- 1. Every statement is rerunnable without errors
-- 2. Uses pg_catalog checks before CREATE POLICY
-- 3. Handles exactly-once ingestion semantics
-- 4. No "policy already exists" failures
-- 5. Creates tables only if they don't exist
-- 6. No assumptions about column existence - checks before adding
--
-- =============================================================================
BEGIN;
-- ===========================================================================
-- STEP 1: Ensure ingest schema exists
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS ingest;
COMMENT ON SCHEMA ingest IS 'Ingestion pipeline schema - batch tracking, job queue, and import runs.';
DO $$ BEGIN RAISE NOTICE '✓ ingest schema exists';
END $$;
-- ===========================================================================
-- STEP 2: Create ingest.import_runs table if not exists
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ingest.import_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id uuid NOT NULL,
    source_type text NOT NULL,
    source_reference text,
    file_hash text,
    started_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'processing',
            'completed',
            'failed',
            'cancelled'
        )
    ),
    rows_processed integer DEFAULT 0,
    rows_succeeded integer DEFAULT 0,
    rows_failed integer DEFAULT 0,
    error_message text,
    metadata jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- ===========================================================================
-- STEP 3: Add columns if they don't exist (defensive)
-- ===========================================================================
DO $$ BEGIN -- Add idempotency_key if it doesn't exist
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'idempotency_key'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN idempotency_key text;
RAISE NOTICE '  Added idempotency_key column';
END IF;
-- Add claimed_by if it doesn't exist
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'claimed_by'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN claimed_by text;
RAISE NOTICE '  Added claimed_by column';
END IF;
-- Add claimed_at if it doesn't exist
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'claimed_at'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN claimed_at timestamptz;
RAISE NOTICE '  Added claimed_at column';
END IF;
END $$;
-- ===========================================================================
-- STEP 4: Create indexes if columns exist (defensive - schema may vary)
-- ===========================================================================
DO $$ BEGIN -- Only create batch_id index if column exists
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'batch_id'
) THEN CREATE INDEX IF NOT EXISTS idx_import_runs_batch_id ON ingest.import_runs (batch_id);
END IF;
-- Only create source_type index if column exists
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'source_type'
) THEN CREATE INDEX IF NOT EXISTS idx_import_runs_source ON ingest.import_runs (source_type, source_reference);
END IF;
-- status and started_at should exist in most schemas
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'status'
) THEN CREATE INDEX IF NOT EXISTS idx_import_runs_status ON ingest.import_runs (status);
END IF;
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'started_at'
) THEN CREATE INDEX IF NOT EXISTS idx_import_runs_started_at ON ingest.import_runs (started_at DESC);
END IF;
END $$;
-- Unique constraint for idempotency (if column exists and constraint doesn't)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'idempotency_key'
)
AND NOT EXISTS (
    SELECT 1
    FROM pg_constraint c
        JOIN pg_namespace n ON n.oid = c.connamespace
    WHERE n.nspname = 'ingest'
        AND c.conname = 'import_runs_idempotency_key_unique'
) THEN -- Use partial unique index to allow nulls
CREATE UNIQUE INDEX IF NOT EXISTS import_runs_idempotency_key_unique ON ingest.import_runs (idempotency_key)
WHERE idempotency_key IS NOT NULL;
RAISE NOTICE '  Created unique index on idempotency_key';
END IF;
END $$;
COMMENT ON TABLE ingest.import_runs IS 'Tracks each import batch execution for exactly-once semantics.';
DO $$ BEGIN RAISE NOTICE '✓ ingest.import_runs table configured';
END $$;
-- ===========================================================================
-- STEP 5: Create ingest.job_queue table if not exists
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ingest.job_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}',
    priority integer DEFAULT 0,
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'claimed',
            'processing',
            'completed',
            'failed',
            'cancelled'
        )
    ),
    claimed_by text,
    claimed_at timestamptz,
    started_at timestamptz,
    completed_at timestamptz,
    attempts integer DEFAULT 0,
    max_attempts integer DEFAULT 3,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_job_queue_status_priority ON ingest.job_queue (status, priority DESC, created_at);
CREATE INDEX IF NOT EXISTS idx_job_queue_claimed ON ingest.job_queue (claimed_by)
WHERE claimed_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_job_queue_type ON ingest.job_queue (job_type);
COMMENT ON TABLE ingest.job_queue IS 'Generic job queue for async processing.';
DO $$ BEGIN RAISE NOTICE '✓ ingest.job_queue table configured';
END $$;
-- ===========================================================================
-- STEP 6: Enable RLS on ingest tables
-- ===========================================================================
ALTER TABLE ingest.import_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest.import_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE ingest.job_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest.job_queue FORCE ROW LEVEL SECURITY;
DO $$ BEGIN RAISE NOTICE '✓ RLS enabled on ingest tables';
END $$;
-- ===========================================================================
-- STEP 7: Create idempotent RLS policies for import_runs
-- ===========================================================================
-- Helper: Check if policy exists
CREATE OR REPLACE FUNCTION public.policy_exists(
        p_schema text,
        p_table text,
        p_policy text
    ) RETURNS boolean LANGUAGE sql SECURITY INVOKER
SET search_path = pg_catalog AS $$
SELECT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = p_schema
            AND tablename = p_table
            AND policyname = p_policy
    );
$$;
COMMENT ON FUNCTION public.policy_exists IS 'Check if a RLS policy exists on a table.';
-- Policy: service_role full access on import_runs
DO $$ BEGIN IF NOT public.policy_exists(
    'ingest',
    'import_runs',
    'import_runs_service_role_full'
) THEN EXECUTE $policy$ CREATE POLICY import_runs_service_role_full ON ingest.import_runs FOR ALL TO service_role USING (true) WITH CHECK (true) $policy$;
RAISE NOTICE '  Created policy: import_runs_service_role_full';
ELSE RAISE NOTICE '  Policy import_runs_service_role_full already exists';
END IF;
END $$;
-- Policy: Deny public access on import_runs
DO $$ BEGIN -- First drop any existing permissive policies for anon/authenticated/public
DROP POLICY IF EXISTS import_runs_deny_public ON ingest.import_runs;
DROP POLICY IF EXISTS import_runs_anon_deny ON ingest.import_runs;
DROP POLICY IF EXISTS import_runs_authenticated_deny ON ingest.import_runs;
-- Note: With RLS enabled and no policy for a role, access is denied by default
-- We don't need explicit deny policies - just don't create permissive ones
RAISE NOTICE '  Ensured no permissive policies for anon/authenticated on import_runs';
END $$;
-- ===========================================================================
-- STEP 8: Create idempotent RLS policies for job_queue
-- ===========================================================================
-- Policy: service_role full access on job_queue
DO $$ BEGIN IF NOT public.policy_exists(
    'ingest',
    'job_queue',
    'job_queue_service_role_full'
) THEN EXECUTE $policy$ CREATE POLICY job_queue_service_role_full ON ingest.job_queue FOR ALL TO service_role USING (true) WITH CHECK (true) $policy$;
RAISE NOTICE '  Created policy: job_queue_service_role_full';
ELSE RAISE NOTICE '  Policy job_queue_service_role_full already exists';
END IF;
END $$;
DO $$ BEGIN RAISE NOTICE '✓ RLS policies configured on ingest tables';
END $$;
-- ===========================================================================
-- STEP 9: Create claim_stale_job function for exactly-once processing
-- ===========================================================================
CREATE OR REPLACE FUNCTION ingest.claim_stale_job(
        p_job_type text,
        p_worker_id text,
        p_stale_threshold interval DEFAULT interval '5 minutes'
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    pg_catalog AS $$
DECLARE v_job_id uuid;
BEGIN -- Atomic claim with row locking
UPDATE ingest.job_queue
SET status = 'claimed',
    claimed_by = p_worker_id,
    claimed_at = now(),
    attempts = attempts + 1,
    updated_at = now()
WHERE id = (
        SELECT id
        FROM ingest.job_queue
        WHERE job_type = p_job_type
            AND (
                -- Unclaimed pending jobs
                (status = 'pending')
                OR -- Stale claimed jobs (worker died)
                (
                    status = 'claimed'
                    AND claimed_at < now() - p_stale_threshold
                )
            )
            AND attempts < max_attempts
        ORDER BY priority DESC,
            created_at FOR
        UPDATE SKIP LOCKED
        LIMIT 1
    )
RETURNING id INTO v_job_id;
RETURN v_job_id;
END;
$$;
REVOKE ALL ON FUNCTION ingest.claim_stale_job(text, text, interval)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ingest.claim_stale_job(text, text, interval) TO service_role;
COMMENT ON FUNCTION ingest.claim_stale_job IS 'Atomically claim a job with stale detection. SECURITY DEFINER for worker access.';
-- ===========================================================================
-- STEP 10: Create check_import_idempotency function
-- ===========================================================================
CREATE OR REPLACE FUNCTION ingest.check_import_idempotency(p_idempotency_key text) RETURNS TABLE (
        already_processed boolean,
        import_run_id uuid,
        status text,
        completed_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    pg_catalog AS $$ BEGIN RETURN QUERY
SELECT true AS already_processed,
    ir.id AS import_run_id,
    ir.status,
    ir.completed_at
FROM ingest.import_runs ir
WHERE ir.idempotency_key = p_idempotency_key
    AND ir.status IN ('completed', 'processing')
LIMIT 1;
-- If no rows returned, caller knows it's safe to proceed
IF NOT FOUND THEN RETURN QUERY
SELECT false,
    NULL::uuid,
    NULL::text,
    NULL::timestamptz;
END IF;
END;
$$;
REVOKE ALL ON FUNCTION ingest.check_import_idempotency(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ingest.check_import_idempotency(text) TO service_role;
COMMENT ON FUNCTION ingest.check_import_idempotency IS 'Check if an import with given idempotency key was already processed.';
-- ===========================================================================
-- STEP 11: Grant schema access to service_role
-- ===========================================================================
GRANT USAGE ON SCHEMA ingest TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA ingest TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ingest TO service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA ingest TO service_role;
-- Default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest
GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ingest
GRANT ALL ON FUNCTIONS TO service_role;
-- Revoke from public roles
REVOKE ALL ON SCHEMA ingest
FROM anon;
REVOKE ALL ON SCHEMA ingest
FROM authenticated;
DO $$ BEGIN RAISE NOTICE '✓ Granted service_role access, revoked public access on ingest schema';
END $$;
-- ===========================================================================
-- STEP 12: Create updated_at trigger
-- ===========================================================================
CREATE OR REPLACE FUNCTION ingest.set_updated_at() RETURNS TRIGGER LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
-- Trigger for import_runs
DROP TRIGGER IF EXISTS trg_import_runs_updated_at ON ingest.import_runs;
CREATE TRIGGER trg_import_runs_updated_at BEFORE
UPDATE ON ingest.import_runs FOR EACH ROW EXECUTE FUNCTION ingest.set_updated_at();
-- Trigger for job_queue
DROP TRIGGER IF EXISTS trg_job_queue_updated_at ON ingest.job_queue;
CREATE TRIGGER trg_job_queue_updated_at BEFORE
UPDATE ON ingest.job_queue FOR EACH ROW EXECUTE FUNCTION ingest.set_updated_at();
DO $$ BEGIN RAISE NOTICE '✓ Created updated_at triggers';
END $$;
-- ===========================================================================
-- STEP 13: Summary
-- ===========================================================================
DO $$ BEGIN RAISE NOTICE '✓ ingest schema RLS and idempotency complete';
RAISE NOTICE '  - import_runs: RLS enabled, service_role policy, idempotency_key support';
RAISE NOTICE '  - job_queue: RLS enabled, service_role policy, stale claim support';
RAISE NOTICE '  - Functions: claim_stale_job, check_import_idempotency';
END $$;
-- ===========================================================================
-- STEP 14: Reload PostgREST schema cache
-- ===========================================================================
DO $$ BEGIN PERFORM pg_notify('pgrst', 'reload schema');
RAISE NOTICE '✓ Notified PostgREST to reload schema cache';
END $$;
COMMIT;
-- ===========================================================================
-- VERIFICATION (run after migration)
-- ===========================================================================
/*
 -- Check RLS is enabled
 SELECT 
 schemaname,
 tablename,
 rowsecurity
 FROM pg_tables
 WHERE schemaname = 'ingest';
 
 -- Check policies
 SELECT * FROM pg_policies WHERE schemaname = 'ingest';
 
 -- Test idempotency check
 SELECT * FROM ingest.check_import_idempotency('test-key-that-does-not-exist');
 
 -- Check grants
 SELECT 
 grantee,
 privilege_type,
 table_schema,
 table_name
 FROM information_schema.table_privileges
 WHERE table_schema = 'ingest'
 ORDER BY table_name, grantee;
 */