-- =============================================================================
-- Migration: claim_import_run RPC
-- Purpose: Atomic, concurrency-safe import run claiming for plaintiff ingestion
-- Date: 2025-01-14
-- =============================================================================
BEGIN;
-- =============================================================================
-- STEP 1: Create claim_import_run stored procedure
-- =============================================================================
-- This function atomically claims an import run for a given source/batch/hash.
-- Returns the run_id and a status indicating whether this is a new claim or duplicate.
--
-- Concurrency safety:
--   - Uses INSERT ... ON CONFLICT with unique constraint
--   - Single atomic operation, no TOCTOU race conditions
--   - Returns existing run_id if duplicate detected
--
-- Usage:
--   SELECT * FROM ingest.claim_import_run('simplicity', 'batch-001', 'sha256hash', 'file.csv', 'plaintiff');
--
CREATE OR REPLACE FUNCTION ingest.claim_import_run(
        p_source_system text,
        p_source_batch_id text,
        p_file_hash text,
        p_filename text DEFAULT NULL,
        p_import_kind text DEFAULT 'plaintiff'
    ) RETURNS TABLE (
        run_id uuid,
        claim_status text,
        -- 'claimed' = new run, 'duplicate' = already exists
        existing_run_id uuid,
        existing_status text,
        existing_completed_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    public AS $$
DECLARE v_new_id uuid := gen_random_uuid();
v_claimed boolean := false;
v_existing_run RECORD;
BEGIN -- =========================================================================
-- STEP 1: Attempt atomic INSERT with ON CONFLICT DO NOTHING
-- =========================================================================
-- This is the core idempotency mechanism. The unique constraint on
-- (source_system, source_batch_id, file_hash) prevents duplicate claims.
INSERT INTO ingest.import_runs (
        id,
        source_system,
        source_batch_id,
        file_hash,
        filename,
        import_kind,
        status,
        rows_fetched,
        rows_inserted,
        rows_skipped,
        rows_errored,
        created_at
    )
VALUES (
        v_new_id,
        p_source_system,
        p_source_batch_id,
        p_file_hash,
        COALESCE(p_filename, p_source_batch_id),
        p_import_kind,
        'processing',
        0,
        0,
        0,
        0,
        now()
    ) ON CONFLICT ON CONSTRAINT import_runs_batch_idempotency_key DO NOTHING;
-- Check if insert succeeded (GET DIAGNOSTICS doesn't work with ON CONFLICT)
IF FOUND THEN v_claimed := true;
END IF;
-- =========================================================================
-- STEP 2: Return appropriate result based on claim outcome
-- =========================================================================
IF v_claimed THEN -- New claim succeeded
RETURN QUERY
SELECT v_new_id,
    'claimed'::text,
    NULL::uuid,
    NULL::text,
    NULL::timestamptz;
ELSE -- Duplicate detected - fetch existing run details
SELECT ir.id,
    ir.status,
    ir.completed_at INTO v_existing_run
FROM ingest.import_runs ir
WHERE ir.source_system = p_source_system
    AND ir.source_batch_id = p_source_batch_id
    AND ir.file_hash = p_file_hash
LIMIT 1;
IF v_existing_run.id IS NOT NULL THEN RETURN QUERY
SELECT NULL::uuid,
    'duplicate'::text,
    v_existing_run.id,
    v_existing_run.status,
    v_existing_run.completed_at;
ELSE -- Edge case: constraint prevented insert but row not found (race condition cleanup?)
-- Retry the insert
INSERT INTO ingest.import_runs (
        id,
        source_system,
        source_batch_id,
        file_hash,
        filename,
        import_kind,
        status,
        rows_fetched,
        rows_inserted,
        rows_skipped,
        rows_errored
    )
VALUES (
        v_new_id,
        p_source_system,
        p_source_batch_id,
        p_file_hash,
        COALESCE(p_filename, p_source_batch_id),
        p_import_kind,
        'processing',
        0,
        0,
        0,
        0
    ) ON CONFLICT ON CONSTRAINT import_runs_batch_idempotency_key DO NOTHING;
RETURN QUERY
SELECT v_new_id,
    'claimed'::text,
    NULL::uuid,
    NULL::text,
    NULL::timestamptz;
END IF;
END IF;
END;
$$;
COMMENT ON FUNCTION ingest.claim_import_run(text, text, text, text, text) IS 'Atomically claim an import run for idempotent batch processing. Returns claim_status="claimed" for new runs, "duplicate" for already-processed batches.';
-- =============================================================================
-- STEP 2: Create reconciliation function
-- =============================================================================
-- Compares import_runs counts vs actual rows in plaintiffs_raw
-- Returns discrepancies for operator investigation
--
CREATE OR REPLACE FUNCTION ingest.reconcile_import_run(p_run_id uuid) RETURNS TABLE (
        run_id uuid,
        filename text,
        source_system text,
        status text,
        -- Counts from import_runs (reported)
        reported_fetched int,
        reported_inserted int,
        reported_skipped int,
        reported_errored int,
        -- Actual counts from plaintiffs_raw
        actual_total int,
        actual_pending int,
        actual_promoted int,
        actual_skipped int,
        actual_failed int,
        -- Discrepancies
        inserted_discrepancy int,
        total_discrepancy int,
        is_reconciled boolean
    ) LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = ingest,
    public AS $$
DECLARE v_run RECORD;
v_actual RECORD;
BEGIN -- Get import run
SELECT ir.id,
    ir.filename,
    ir.source_system,
    ir.status,
    ir.rows_fetched,
    ir.rows_inserted,
    ir.rows_skipped,
    ir.rows_errored INTO v_run
FROM ingest.import_runs ir
WHERE ir.id = p_run_id;
IF v_run.id IS NULL THEN RAISE EXCEPTION 'Import run not found: %',
p_run_id;
END IF;
-- Count actual rows in plaintiffs_raw
SELECT COUNT(*)::int as total,
    COUNT(*) FILTER (
        WHERE pr.status = 'pending'
    )::int as pending,
    COUNT(*) FILTER (
        WHERE pr.status = 'promoted'
    )::int as promoted,
    COUNT(*) FILTER (
        WHERE pr.status = 'skipped'
    )::int as skipped,
    COUNT(*) FILTER (
        WHERE pr.status = 'failed'
    )::int as failed INTO v_actual
FROM ingest.plaintiffs_raw pr
WHERE pr.import_run_id = p_run_id;
RETURN QUERY
SELECT v_run.id,
    v_run.filename,
    v_run.source_system,
    v_run.status,
    -- Reported
    v_run.rows_fetched,
    v_run.rows_inserted,
    v_run.rows_skipped,
    v_run.rows_errored,
    -- Actual
    v_actual.total,
    v_actual.pending,
    v_actual.promoted,
    v_actual.skipped,
    v_actual.failed,
    -- Discrepancies (inserted should match pending + promoted)
    (v_actual.pending + v_actual.promoted) - v_run.rows_inserted,
    v_actual.total - v_run.rows_inserted,
    -- Is reconciled if no discrepancies
    (
        (v_actual.pending + v_actual.promoted) = v_run.rows_inserted
    );
END;
$$;
COMMENT ON FUNCTION ingest.reconcile_import_run(uuid) IS 'Reconcile an import run by comparing reported counts in import_runs vs actual rows in plaintiffs_raw. Returns discrepancies for investigation.';
-- =============================================================================
-- STEP 3: Create bulk reconciliation view
-- =============================================================================
CREATE OR REPLACE VIEW ingest.v_import_reconciliation AS
SELECT ir.id,
    ir.filename,
    ir.source_system,
    ir.status,
    ir.created_at,
    ir.completed_at,
    -- Reported counts
    ir.rows_fetched,
    ir.rows_inserted,
    ir.rows_skipped,
    ir.rows_errored,
    -- Actual counts
    COALESCE(raw_counts.total, 0) as actual_total,
    COALESCE(raw_counts.pending, 0) as actual_pending,
    COALESCE(raw_counts.promoted, 0) as actual_promoted,
    COALESCE(raw_counts.skipped, 0) as actual_skipped,
    COALESCE(raw_counts.failed, 0) as actual_failed,
    -- Discrepancies
    COALESCE(raw_counts.pending + raw_counts.promoted, 0) - ir.rows_inserted as inserted_discrepancy,
    COALESCE(raw_counts.total, 0) - ir.rows_inserted as total_discrepancy,
    -- Is reconciled
    (
        COALESCE(raw_counts.pending + raw_counts.promoted, 0) = ir.rows_inserted
    ) as is_reconciled
FROM ingest.import_runs ir
    LEFT JOIN LATERAL (
        SELECT COUNT(*)::int as total,
            COUNT(*) FILTER (
                WHERE pr.status = 'pending'
            )::int as pending,
            COUNT(*) FILTER (
                WHERE pr.status = 'promoted'
            )::int as promoted,
            COUNT(*) FILTER (
                WHERE pr.status = 'skipped'
            )::int as skipped,
            COUNT(*) FILTER (
                WHERE pr.status = 'failed'
            )::int as failed
        FROM ingest.plaintiffs_raw pr
        WHERE pr.import_run_id = ir.id
    ) raw_counts ON true
ORDER BY ir.created_at DESC;
COMMENT ON VIEW ingest.v_import_reconciliation IS 'Reconciliation view comparing import_runs reported counts vs actual plaintiffs_raw rows. Use to detect count mismatches.';
-- =============================================================================
-- STEP 4: Create soft-delete function for rollback
-- =============================================================================
-- Marks an import run and its rows as deleted (soft-delete with audit trail)
-- Does NOT physically delete data - preserves for investigation
--
CREATE OR REPLACE FUNCTION ingest.rollback_import_run(
        p_run_id uuid,
        p_reason text DEFAULT 'Manual rollback'
    ) RETURNS TABLE (
        run_id uuid,
        rows_marked int,
        rollback_reason text,
        rolled_back_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ingest,
    public AS $$
DECLARE v_rows_affected int;
BEGIN -- Mark import run as rolled_back
UPDATE ingest.import_runs
SET status = 'rolled_back',
    error_details = COALESCE(error_details, '{}'::jsonb) || jsonb_build_object(
        'rollback_reason',
        p_reason,
        'rolled_back_at',
        now()::text,
        'original_status',
        status
    )
WHERE id = p_run_id
    AND status != 'rolled_back';
-- Idempotent
IF NOT FOUND THEN RAISE EXCEPTION 'Import run not found or already rolled back: %',
p_run_id;
END IF;
-- Mark all plaintiffs_raw rows as rolled_back
UPDATE ingest.plaintiffs_raw
SET status = 'rolled_back',
    error_code = 'ROLLBACK',
    error_message = p_reason
WHERE import_run_id = p_run_id
    AND status != 'rolled_back';
GET DIAGNOSTICS v_rows_affected = ROW_COUNT;
RETURN QUERY
SELECT p_run_id,
    v_rows_affected,
    p_reason,
    now();
END;
$$;
COMMENT ON FUNCTION ingest.rollback_import_run(uuid, text) IS 'Soft-delete an import run and its rows. Preserves data for audit trail. Use for bad batch rollback.';
-- Add 'rolled_back' to status check constraint
DO $$ BEGIN -- Check if constraint exists and needs updating
IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'plaintiffs_raw_status_check'
        AND conrelid = 'ingest.plaintiffs_raw'::regclass
) THEN
ALTER TABLE ingest.plaintiffs_raw DROP CONSTRAINT plaintiffs_raw_status_check;
END IF;
ALTER TABLE ingest.plaintiffs_raw
ADD CONSTRAINT plaintiffs_raw_status_check CHECK (
        status IN (
            'pending',
            'processing',
            'promoted',
            'failed',
            'skipped',
            'rolled_back'
        )
    );
RAISE NOTICE '✓ Updated plaintiffs_raw status constraint to include rolled_back';
EXCEPTION
WHEN duplicate_object THEN RAISE NOTICE '○ Status constraint already includes rolled_back';
END $$;
-- =============================================================================
-- STEP 5: Grants
-- =============================================================================
GRANT EXECUTE ON FUNCTION ingest.claim_import_run(text, text, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION ingest.reconcile_import_run(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION ingest.rollback_import_run(uuid, text) TO service_role;
GRANT SELECT ON ingest.v_import_reconciliation TO service_role;
-- Grant to dragonfly_app if exists
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT EXECUTE ON FUNCTION ingest.claim_import_run(text, text, text, text, text) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ingest.reconcile_import_run(uuid) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ingest.rollback_import_run(uuid, text) TO dragonfly_app;
GRANT SELECT ON ingest.v_import_reconciliation TO dragonfly_app;
RAISE NOTICE '✓ Granted RPC functions to dragonfly_app';
END IF;
END $$;
-- =============================================================================
-- VERIFICATION
-- =============================================================================
DO $$ BEGIN RAISE NOTICE '✅ claim_import_run RPC migration complete';
RAISE NOTICE '';
RAISE NOTICE 'New functions:';
RAISE NOTICE '  • ingest.claim_import_run(source, batch_id, hash, filename, kind)';
RAISE NOTICE '    → Returns run_id + claim_status (claimed|duplicate)';
RAISE NOTICE '';
RAISE NOTICE '  • ingest.reconcile_import_run(run_id)';
RAISE NOTICE '    → Compares reported vs actual counts';
RAISE NOTICE '';
RAISE NOTICE '  • ingest.rollback_import_run(run_id, reason)';
RAISE NOTICE '    → Soft-deletes run + rows for audit trail';
RAISE NOTICE '';
RAISE NOTICE 'New view:';
RAISE NOTICE '  • ingest.v_import_reconciliation';
RAISE NOTICE '    → Bulk reconciliation for all runs';
END $$;
COMMIT;
-- =============================================================================
-- USAGE EXAMPLES (for reference)
-- =============================================================================
/*
 -- Claim an import run (Python will call this via RPC)
 SELECT * FROM ingest.claim_import_run(
 'simplicity',           -- source_system
 'batch-2025-01-14',     -- source_batch_id  
 'a1b2c3d4e5f6...',      -- file_hash (SHA-256)
 'plaintiffs_jan14.csv', -- filename
 'plaintiff'             -- import_kind
 );
 -- Returns: run_id, claim_status, existing_run_id, existing_status, existing_completed_at
 
 -- Reconcile a specific run
 SELECT * FROM ingest.reconcile_import_run('abc-123-uuid');
 
 -- View all runs with reconciliation status
 SELECT * FROM ingest.v_import_reconciliation WHERE NOT is_reconciled;
 
 -- Rollback a bad batch
 SELECT * FROM ingest.rollback_import_run(
 'abc-123-uuid',
 'Vendor sent corrupted data - see ticket #1234'
 );
 */