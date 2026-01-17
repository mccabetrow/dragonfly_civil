-- =============================================================================
-- Migration: 20260115120000_plaintiff_ingest_claim_rpc.sql
-- Purpose: Production-grade plaintiff ingestion moat with claim/reconcile/rollback RPC
-- Author: Principal Database Reliability Engineer
-- Date: 2026-01-15
-- =============================================================================
--
-- DESIGN PRINCIPLES:
--   1. Atomic concurrency-safe batch claiming via INSERT...ON CONFLICT
--   2. Three possible claim outcomes: 'claimed', 'duplicate', 'in_progress'
--   3. Reconciliation verifies row counts match expectations
--   4. Soft-delete rollback preserves audit trail (no hard deletes)
--   5. All functions are idempotent and safe to retry
--
-- RPC FUNCTIONS:
--   ingest.claim_import_run(source_system, source_batch_id, file_hash, filename, import_kind)
--     → (run_id uuid, claim_status text)
--
--   ingest.reconcile_import_run(run_id uuid)
--     → (is_valid boolean, expected_count int, actual_count int, delta int)
--
--   ingest.rollback_import_run(run_id uuid, reason text)
--     → (success boolean, rows_affected int)
--
-- ROLLBACK:
--   DROP FUNCTION IF EXISTS ingest.claim_import_run(text, text, text, text, text);
--   DROP FUNCTION IF EXISTS ingest.reconcile_import_run(uuid);
--   DROP FUNCTION IF EXISTS ingest.rollback_import_run(uuid, text);
--   DROP TYPE IF EXISTS ingest.claim_result;
--   DROP TYPE IF EXISTS ingest.reconcile_result;
--   DROP TYPE IF EXISTS ingest.rollback_result;
--
-- =============================================================================
BEGIN;
-- =============================================================================
-- STEP 1: Add columns for rollback support if missing
-- =============================================================================
-- Add rolled_back_at column if missing
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'rolled_back_at'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN rolled_back_at timestamptz;
RAISE NOTICE '✓ Added column rolled_back_at to ingest.import_runs';
END IF;
END $$;
-- Add rollback_reason column if missing
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'rollback_reason'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN rollback_reason text;
RAISE NOTICE '✓ Added column rollback_reason to ingest.import_runs';
END IF;
END $$;
-- Add claimed_at column for tracking claim time
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'claimed_at'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN claimed_at timestamptz;
RAISE NOTICE '✓ Added column claimed_at to ingest.import_runs';
END IF;
END $$;
-- Add worker_id column for tracking which worker claimed the run
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'worker_id'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN worker_id text;
RAISE NOTICE '✓ Added column worker_id to ingest.import_runs';
END IF;
END $$;
-- Add status 'rolled_back' to enum if not exists
DO $$ BEGIN -- Check if rolled_back value exists in the enum
IF NOT EXISTS (
    SELECT 1
    FROM pg_enum e
        JOIN pg_type t ON e.enumtypid = t.oid
        JOIN pg_namespace n ON t.typnamespace = n.oid
    WHERE n.nspname = 'ingest'
        AND t.typname = 'import_run_status'
        AND e.enumlabel = 'rolled_back'
) THEN ALTER TYPE ingest.import_run_status
ADD VALUE IF NOT EXISTS 'rolled_back';
RAISE NOTICE '✓ Added rolled_back to ingest.import_run_status enum';
END IF;
END $$;
-- =============================================================================
-- STEP 2: Create result types for RPC functions
-- =============================================================================
-- Claim result type
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'ingest'
        AND t.typname = 'claim_result'
) THEN CREATE TYPE ingest.claim_result AS (
    run_id uuid,
    claim_status text -- 'claimed', 'duplicate', 'in_progress'
);
RAISE NOTICE '✓ Created type ingest.claim_result';
ELSE RAISE NOTICE '○ Type ingest.claim_result already exists';
END IF;
END $$;
-- Reconcile result type
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'ingest'
        AND t.typname = 'reconcile_result'
) THEN CREATE TYPE ingest.reconcile_result AS (
    is_valid boolean,
    expected_count integer,
    actual_count integer,
    delta integer
);
RAISE NOTICE '✓ Created type ingest.reconcile_result';
ELSE RAISE NOTICE '○ Type ingest.reconcile_result already exists';
END IF;
END $$;
-- Rollback result type
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON n.oid = t.typnamespace
    WHERE n.nspname = 'ingest'
        AND t.typname = 'rollback_result'
) THEN CREATE TYPE ingest.rollback_result AS (
    success boolean,
    rows_affected integer
);
RAISE NOTICE '✓ Created type ingest.rollback_result';
ELSE RAISE NOTICE '○ Type ingest.rollback_result already exists';
END IF;
END $$;
-- =============================================================================
-- STEP 3: Create claim_import_run function
-- =============================================================================
--
-- Atomic concurrency-safe claim using INSERT...ON CONFLICT
-- Returns claim_status:
--   'claimed'     - This caller successfully claimed the batch
--   'duplicate'   - Batch was already completed (file_hash + batch_id match a completed run)
--   'in_progress' - Batch is being processed by another worker
--
CREATE OR REPLACE FUNCTION ingest.claim_import_run(
        p_source_system text,
        p_source_batch_id text,
        p_file_hash text,
        p_filename text DEFAULT NULL,
        p_import_kind text DEFAULT 'plaintiff',
        p_worker_id text DEFAULT NULL
    ) RETURNS ingest.claim_result LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    public AS $$
DECLARE v_result ingest.claim_result;
v_existing_id uuid;
v_existing_status ingest.import_run_status;
v_stale_threshold interval := interval '30 minutes';
BEGIN -- =========================================================================
-- STEP 1: Check for existing run with same idempotency key
-- =========================================================================
SELECT id,
    status INTO v_existing_id,
    v_existing_status
FROM ingest.import_runs
WHERE source_system = p_source_system
    AND source_batch_id = p_source_batch_id
    AND file_hash = p_file_hash FOR
UPDATE SKIP LOCKED;
-- Skip locked rows to avoid blocking
IF v_existing_id IS NOT NULL THEN -- Run already exists - determine status
CASE
    v_existing_status
    WHEN 'completed' THEN -- Already processed successfully - return duplicate
    v_result.run_id := v_existing_id;
v_result.claim_status := 'duplicate';
RETURN v_result;
WHEN 'failed',
'rolled_back' THEN -- Previous attempt failed - allow re-claim
UPDATE ingest.import_runs
SET status = 'processing',
    claimed_at = now(),
    worker_id = p_worker_id,
    updated_at = now(),
    error_details = NULL -- Clear previous errors
WHERE id = v_existing_id;
v_result.run_id := v_existing_id;
v_result.claim_status := 'claimed';
RETURN v_result;
WHEN 'pending',
'processing' THEN -- Check for stale lock (crashed worker)
IF (
    SELECT updated_at
    FROM ingest.import_runs
    WHERE id = v_existing_id
) < now() - v_stale_threshold THEN -- Stale - take over
UPDATE ingest.import_runs
SET status = 'processing',
    claimed_at = now(),
    worker_id = p_worker_id,
    updated_at = now(),
    error_details = jsonb_build_object(
        'takeover_reason',
        'stale_lock',
        'previous_worker',
        (
            SELECT worker_id
            FROM ingest.import_runs
            WHERE id = v_existing_id
        ),
        'takeover_at',
        now()::text
    )
WHERE id = v_existing_id;
v_result.run_id := v_existing_id;
v_result.claim_status := 'claimed';
RETURN v_result;
ELSE -- Still active - return in_progress
v_result.run_id := v_existing_id;
v_result.claim_status := 'in_progress';
RETURN v_result;
END IF;
ELSE -- Unknown status - treat as in_progress
v_result.run_id := v_existing_id;
v_result.claim_status := 'in_progress';
RETURN v_result;
END CASE
;
END IF;
-- =========================================================================
-- STEP 2: No existing run - attempt to insert new claim
-- =========================================================================
INSERT INTO ingest.import_runs (
        source_system,
        source_batch_id,
        file_hash,
        filename,
        import_kind,
        status,
        claimed_at,
        worker_id,
        created_at,
        updated_at
    )
VALUES (
        p_source_system,
        p_source_batch_id,
        p_file_hash,
        p_filename,
        COALESCE(p_import_kind, 'plaintiff'),
        'processing',
        now(),
        p_worker_id,
        now(),
        now()
    ) ON CONFLICT (source_system, source_batch_id, file_hash) DO NOTHING
RETURNING id INTO v_result.run_id;
IF v_result.run_id IS NOT NULL THEN -- Successfully claimed
v_result.claim_status := 'claimed';
ELSE -- Lost race - another worker claimed it first
-- Re-query to get the winner's status
SELECT id,
    status INTO v_existing_id,
    v_existing_status
FROM ingest.import_runs
WHERE source_system = p_source_system
    AND source_batch_id = p_source_batch_id
    AND file_hash = p_file_hash;
v_result.run_id := v_existing_id;
IF v_existing_status = 'completed' THEN v_result.claim_status := 'duplicate';
ELSE v_result.claim_status := 'in_progress';
END IF;
END IF;
RETURN v_result;
END;
$$;
COMMENT ON FUNCTION ingest.claim_import_run(text, text, text, text, text, text) IS 'Atomically claim an import batch. Returns (run_id, claim_status) where claim_status is one of: claimed, duplicate, in_progress.';
-- =============================================================================
-- STEP 4: Create reconcile_import_run function
-- =============================================================================
--
-- Verifies that the expected row count matches actual rows in plaintiffs_raw
-- Updates the import_run record with final counts
--
CREATE OR REPLACE FUNCTION ingest.reconcile_import_run(
        p_run_id uuid,
        p_expected_count integer DEFAULT NULL
    ) RETURNS ingest.reconcile_result LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    public AS $$
DECLARE v_result ingest.reconcile_result;
v_run_record RECORD;
v_actual_count integer;
v_inserted_count integer;
v_skipped_count integer;
v_failed_count integer;
BEGIN -- =========================================================================
-- STEP 1: Verify run exists and is in valid state
-- =========================================================================
SELECT * INTO v_run_record
FROM ingest.import_runs
WHERE id = p_run_id FOR
UPDATE;
IF v_run_record IS NULL THEN RAISE EXCEPTION 'Import run % not found',
p_run_id;
END IF;
IF v_run_record.status NOT IN ('processing', 'pending') THEN RAISE EXCEPTION 'Cannot reconcile run % with status %',
p_run_id,
v_run_record.status;
END IF;
-- =========================================================================
-- STEP 2: Count rows by status
-- =========================================================================
SELECT COUNT(*),
    COUNT(*) FILTER (
        WHERE status IN ('pending', 'promoted', 'processing')
    ),
    COUNT(*) FILTER (
        WHERE status = 'skipped'
    ),
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) INTO v_actual_count,
    v_inserted_count,
    v_skipped_count,
    v_failed_count
FROM ingest.plaintiffs_raw
WHERE import_run_id = p_run_id;
-- =========================================================================
-- STEP 3: Calculate delta
-- =========================================================================
v_result.actual_count := v_actual_count;
v_result.expected_count := COALESCE(
    p_expected_count,
    v_run_record.rows_fetched,
    v_actual_count
);
v_result.delta := v_result.expected_count - v_actual_count;
v_result.is_valid := (v_result.delta = 0);
-- =========================================================================
-- STEP 4: Update run with final counts
-- =========================================================================
UPDATE ingest.import_runs
SET status = CASE
        WHEN v_result.is_valid THEN 'completed'
        ELSE 'failed'
    END,
    completed_at = now(),
    rows_fetched = v_result.expected_count,
    rows_inserted = v_inserted_count,
    rows_skipped = v_skipped_count,
    rows_errored = v_failed_count,
    updated_at = now(),
    error_details = CASE
        WHEN v_result.is_valid THEN NULL
        ELSE jsonb_build_object(
            'reconciliation_failed',
            true,
            'expected_count',
            v_result.expected_count,
            'actual_count',
            v_actual_count,
            'delta',
            v_result.delta
        )
    END
WHERE id = p_run_id;
RETURN v_result;
END;
$$;
COMMENT ON FUNCTION ingest.reconcile_import_run(uuid, integer) IS 'Reconcile import run by comparing expected vs actual row counts. Marks run as completed or failed.';
-- =============================================================================
-- STEP 5: Create rollback_import_run function
-- =============================================================================
--
-- Soft-delete: marks run as rolled_back and updates plaintiffs_raw status
-- Does NOT delete any data - preserves full audit trail
--
CREATE OR REPLACE FUNCTION ingest.rollback_import_run(
        p_run_id uuid,
        p_reason text DEFAULT 'manual_rollback'
    ) RETURNS ingest.rollback_result LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    public AS $$
DECLARE v_result ingest.rollback_result;
v_run_record RECORD;
v_rows_affected integer;
BEGIN -- =========================================================================
-- STEP 1: Verify run exists
-- =========================================================================
SELECT * INTO v_run_record
FROM ingest.import_runs
WHERE id = p_run_id FOR
UPDATE;
IF v_run_record IS NULL THEN v_result.success := false;
v_result.rows_affected := 0;
RETURN v_result;
END IF;
-- Already rolled back - idempotent return
IF v_run_record.status = 'rolled_back' THEN v_result.success := true;
v_result.rows_affected := 0;
RETURN v_result;
END IF;
-- =========================================================================
-- STEP 2: Mark plaintiffs_raw rows as rolled_back
-- =========================================================================
UPDATE ingest.plaintiffs_raw
SET status = 'skipped',
    error_code = 'ROLLED_BACK',
    error_message = p_reason,
    updated_at = now()
WHERE import_run_id = p_run_id
    AND status NOT IN ('promoted');
-- Don't touch already-promoted rows
GET DIAGNOSTICS v_rows_affected = ROW_COUNT;
-- =========================================================================
-- STEP 3: Mark import_run as rolled_back
-- =========================================================================
UPDATE ingest.import_runs
SET status = 'rolled_back',
    rolled_back_at = now(),
    rollback_reason = p_reason,
    updated_at = now(),
    error_details = COALESCE(error_details, '{}'::jsonb) || jsonb_build_object(
        'rollback_reason',
        p_reason,
        'rollback_at',
        now()::text,
        'rows_affected',
        v_rows_affected
    )
WHERE id = p_run_id;
v_result.success := true;
v_result.rows_affected := v_rows_affected;
RETURN v_result;
END;
$$;
COMMENT ON FUNCTION ingest.rollback_import_run(uuid, text) IS 'Soft-delete import run and mark associated rows as rolled_back. Preserves full audit trail.';
-- =============================================================================
-- STEP 6: Create finalize_import_run function (helper for Python ingester)
-- =============================================================================
--
-- Updates run with final counts and optionally marks as completed/failed
--
CREATE OR REPLACE FUNCTION ingest.finalize_import_run(
        p_run_id uuid,
        p_rows_fetched integer,
        p_rows_inserted integer,
        p_rows_skipped integer,
        p_rows_errored integer,
        p_error_details jsonb DEFAULT NULL,
        p_mark_completed boolean DEFAULT true
    ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    public AS $$
DECLARE v_new_status ingest.import_run_status;
BEGIN -- Determine final status
IF p_error_details IS NOT NULL
AND p_error_details ? 'fatal' THEN v_new_status := 'failed';
ELSIF p_mark_completed THEN v_new_status := 'completed';
ELSE v_new_status := 'processing';
-- Keep processing if not marking completed
END IF;
UPDATE ingest.import_runs
SET status = v_new_status,
    completed_at = CASE
        WHEN p_mark_completed THEN now()
        ELSE completed_at
    END,
    rows_fetched = p_rows_fetched,
    rows_inserted = p_rows_inserted,
    rows_skipped = p_rows_skipped,
    rows_errored = p_rows_errored,
    error_details = p_error_details,
    updated_at = now()
WHERE id = p_run_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION ingest.finalize_import_run(
    uuid,
    integer,
    integer,
    integer,
    integer,
    jsonb,
    boolean
) IS 'Finalize import run with final row counts and status. Used by Python ingester.';
-- =============================================================================
-- STEP 7: Create heartbeat function for long-running imports
-- =============================================================================
--
-- Updates updated_at to prevent stale takeover during long imports
--
CREATE OR REPLACE FUNCTION ingest.heartbeat_import_run(p_run_id uuid) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    public AS $$ BEGIN
UPDATE ingest.import_runs
SET updated_at = now()
WHERE id = p_run_id
    AND status = 'processing';
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION ingest.heartbeat_import_run(uuid) IS 'Update heartbeat timestamp to prevent stale lock takeover during long imports.';
-- =============================================================================
-- STEP 8: Create views for operator queries
-- =============================================================================
-- Latest runs (last 50)
CREATE OR REPLACE VIEW ingest.v_latest_runs AS
SELECT ir.id,
    ir.source_system,
    ir.source_batch_id,
    ir.filename,
    ir.import_kind,
    ir.status::text,
    ir.worker_id,
    ir.rows_fetched,
    ir.rows_inserted,
    ir.rows_skipped,
    ir.rows_errored,
    ir.created_at,
    ir.claimed_at,
    ir.completed_at,
    ir.rolled_back_at,
    EXTRACT(
        EPOCH
        FROM (
                COALESCE(ir.completed_at, ir.rolled_back_at, now()) - ir.created_at
            )
    ) AS duration_seconds,
    ir.error_details
FROM ingest.import_runs ir
ORDER BY ir.created_at DESC
LIMIT 50;
COMMENT ON VIEW ingest.v_latest_runs IS 'Last 50 import runs for operator monitoring.';
-- Duplicates blocked
CREATE OR REPLACE VIEW ingest.v_duplicates_blocked AS
SELECT ir.source_system,
    ir.source_batch_id,
    ir.file_hash,
    ir.filename,
    COUNT(*) FILTER (
        WHERE ir2.status = 'completed'
    ) AS completed_count,
    MIN(ir.created_at) AS first_attempt,
    MAX(ir.created_at) AS last_attempt
FROM ingest.import_runs ir
    LEFT JOIN ingest.import_runs ir2 ON ir2.source_system = ir.source_system
    AND ir2.source_batch_id = ir.source_batch_id
    AND ir2.file_hash = ir.file_hash
    AND ir2.status = 'completed'
GROUP BY ir.source_system,
    ir.source_batch_id,
    ir.file_hash,
    ir.filename
HAVING COUNT(*) > 1
ORDER BY MAX(ir.created_at) DESC;
COMMENT ON VIEW ingest.v_duplicates_blocked IS 'Batches that have been imported multiple times (indicating blocked duplicates).';
-- Reconciliation failures
CREATE OR REPLACE VIEW ingest.v_reconciliation_failures AS
SELECT ir.id,
    ir.source_system,
    ir.source_batch_id,
    ir.filename,
    ir.status::text,
    ir.rows_fetched,
    ir.rows_inserted,
    ir.rows_skipped,
    ir.rows_errored,
    (
        ir.rows_fetched - COALESCE(ir.rows_inserted, 0) - COALESCE(ir.rows_skipped, 0) - COALESCE(ir.rows_errored, 0)
    ) AS unaccounted,
    ir.error_details,
    ir.completed_at
FROM ingest.import_runs ir
WHERE ir.status = 'failed'
    AND ir.error_details ? 'reconciliation_failed'
ORDER BY ir.completed_at DESC;
COMMENT ON VIEW ingest.v_reconciliation_failures IS 'Import runs that failed reconciliation (row count mismatch).';
-- Rolled back runs
CREATE OR REPLACE VIEW ingest.v_rollback_verification AS
SELECT ir.id,
    ir.source_system,
    ir.source_batch_id,
    ir.filename,
    ir.rollback_reason,
    ir.rolled_back_at,
    (
        SELECT COUNT(*)
        FROM ingest.plaintiffs_raw pr
        WHERE pr.import_run_id = ir.id
    ) AS total_rows,
    (
        SELECT COUNT(*)
        FROM ingest.plaintiffs_raw pr
        WHERE pr.import_run_id = ir.id
            AND pr.error_code = 'ROLLED_BACK'
    ) AS rolled_back_rows,
    (
        SELECT COUNT(*)
        FROM ingest.plaintiffs_raw pr
        WHERE pr.import_run_id = ir.id
            AND pr.status = 'promoted'
    ) AS promoted_rows,
    ir.error_details
FROM ingest.import_runs ir
WHERE ir.status = 'rolled_back'
ORDER BY ir.rolled_back_at DESC;
COMMENT ON VIEW ingest.v_rollback_verification IS 'Rolled back runs with row-level breakdown for audit.';
-- =============================================================================
-- STEP 9: Grants
-- =============================================================================
-- Grant execute to service_role
GRANT EXECUTE ON FUNCTION ingest.claim_import_run(text, text, text, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION ingest.reconcile_import_run(uuid, integer) TO service_role;
GRANT EXECUTE ON FUNCTION ingest.rollback_import_run(uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION ingest.finalize_import_run(
        uuid,
        integer,
        integer,
        integer,
        integer,
        jsonb,
        boolean
    ) TO service_role;
GRANT EXECUTE ON FUNCTION ingest.heartbeat_import_run(uuid) TO service_role;
-- Grant view access
GRANT SELECT ON ingest.v_latest_runs TO service_role;
GRANT SELECT ON ingest.v_duplicates_blocked TO service_role;
GRANT SELECT ON ingest.v_reconciliation_failures TO service_role;
GRANT SELECT ON ingest.v_rollback_verification TO service_role;
-- Grant to dragonfly_app if exists
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT EXECUTE ON FUNCTION ingest.claim_import_run(text, text, text, text, text, text) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ingest.reconcile_import_run(uuid, integer) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ingest.rollback_import_run(uuid, text) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ingest.finalize_import_run(
        uuid,
        integer,
        integer,
        integer,
        integer,
        jsonb,
        boolean
    ) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ingest.heartbeat_import_run(uuid) TO dragonfly_app;
GRANT SELECT ON ingest.v_latest_runs TO dragonfly_app;
GRANT SELECT ON ingest.v_duplicates_blocked TO dragonfly_app;
GRANT SELECT ON ingest.v_reconciliation_failures TO dragonfly_app;
GRANT SELECT ON ingest.v_rollback_verification TO dragonfly_app;
RAISE NOTICE '✓ Granted ingest RPC functions to dragonfly_app';
END IF;
END $$;
-- =============================================================================
-- VERIFICATION
-- =============================================================================
DO $$ BEGIN RAISE NOTICE '✅ Plaintiff Ingest Claim RPC migration complete';
RAISE NOTICE '';
RAISE NOTICE 'RPC Functions:';
RAISE NOTICE '  • ingest.claim_import_run(source_system, batch_id, file_hash, filename, import_kind, worker_id)';
RAISE NOTICE '    → Returns (run_id uuid, claim_status text: claimed|duplicate|in_progress)';
RAISE NOTICE '';
RAISE NOTICE '  • ingest.reconcile_import_run(run_id, expected_count)';
RAISE NOTICE '    → Returns (is_valid bool, expected_count, actual_count, delta)';
RAISE NOTICE '';
RAISE NOTICE '  • ingest.rollback_import_run(run_id, reason)';
RAISE NOTICE '    → Returns (success bool, rows_affected int)';
RAISE NOTICE '';
RAISE NOTICE '  • ingest.finalize_import_run(run_id, fetched, inserted, skipped, errored, errors, mark_completed)';
RAISE NOTICE '    → Returns boolean';
RAISE NOTICE '';
RAISE NOTICE '  • ingest.heartbeat_import_run(run_id)';
RAISE NOTICE '    → Returns boolean (prevents stale takeover)';
RAISE NOTICE '';
RAISE NOTICE 'Operator Views:';
RAISE NOTICE '  • ingest.v_latest_runs - Last 50 runs';
RAISE NOTICE '  • ingest.v_duplicates_blocked - Duplicate attempts';
RAISE NOTICE '  • ingest.v_reconciliation_failures - Failed reconciliations';
RAISE NOTICE '  • ingest.v_rollback_verification - Rollback audit';
END $$;
COMMIT;