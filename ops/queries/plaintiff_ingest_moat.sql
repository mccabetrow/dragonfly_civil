-- =============================================================================
-- Operator SQL Queries for Plaintiff Ingestion Moat
-- =============================================================================
--
-- This file contains production operator queries for monitoring and
-- troubleshooting the plaintiff ingestion pipeline.
--
-- Usage:
--   Connect to Supabase via psql or SQL editor and run these queries as needed.
--
-- =============================================================================
-- =============================================================================
-- 1. LATEST RUNS - Last 20 import runs with status
-- =============================================================================
-- Shows recent import activity with success/failure breakdown
SELECT id,
    source_system,
    source_batch_id,
    filename,
    status::text,
    rows_fetched,
    rows_inserted,
    rows_skipped,
    rows_errored,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (
                    COALESCE(completed_at, rolled_back_at, now()) - created_at
                )
        )::numeric,
        1
    ) AS duration_sec,
    worker_id,
    created_at,
    completed_at
FROM ingest.import_runs
ORDER BY created_at DESC
LIMIT 20;
-- =============================================================================
-- 2. DUPLICATES BLOCKED - Batches that were rejected as duplicates
-- =============================================================================
-- Shows which batches were detected as already-imported duplicates
SELECT ir1.source_system,
    ir1.source_batch_id,
    ir1.file_hash,
    ir1.filename,
    ir1.created_at AS duplicate_attempt_at,
    ir2.id AS original_run_id,
    ir2.completed_at AS original_completed_at,
    ir2.status::text AS original_status
FROM ingest.import_runs ir1
    JOIN ingest.import_runs ir2 ON ir2.source_system = ir1.source_system
    AND ir2.source_batch_id = ir1.source_batch_id
    AND ir2.file_hash = ir1.file_hash
    AND ir2.id != ir1.id
    AND ir2.status = 'completed'
    AND ir2.created_at < ir1.created_at
ORDER BY ir1.created_at DESC
LIMIT 50;
-- =============================================================================
-- 3. RECONCILIATION FAILURES - Runs that failed row count validation
-- =============================================================================
-- Shows imports where expected vs actual row counts didn't match
SELECT id,
    source_system,
    source_batch_id,
    filename,
    rows_fetched AS expected,
    (
        COALESCE(rows_inserted, 0) + COALESCE(rows_skipped, 0) + COALESCE(rows_errored, 0)
    ) AS actual,
    (
        rows_fetched - COALESCE(rows_inserted, 0) - COALESCE(rows_skipped, 0) - COALESCE(rows_errored, 0)
    ) AS unaccounted,
    error_details->>'message' AS error_message,
    completed_at
FROM ingest.import_runs
WHERE status = 'failed'
    AND error_details ? 'reconciliation_failed'
ORDER BY completed_at DESC
LIMIT 25;
-- =============================================================================
-- 4. ROLLBACK VERIFICATION - Rolled back runs with row-level breakdown
-- =============================================================================
-- Shows runs that were rolled back and how many rows were affected
SELECT ir.id,
    ir.source_system,
    ir.source_batch_id,
    ir.filename,
    ir.rollback_reason,
    ir.rolled_back_at,
    COUNT(pr.id) AS total_rows,
    COUNT(*) FILTER (
        WHERE pr.error_code = 'ROLLED_BACK'
    ) AS rolled_back_rows,
    COUNT(*) FILTER (
        WHERE pr.status = 'promoted'
    ) AS already_promoted_rows,
    ir.error_details
FROM ingest.import_runs ir
    LEFT JOIN ingest.plaintiffs_raw pr ON pr.import_run_id = ir.id
WHERE ir.status = 'rolled_back'
GROUP BY ir.id,
    ir.source_system,
    ir.source_batch_id,
    ir.filename,
    ir.rollback_reason,
    ir.rolled_back_at,
    ir.error_details
ORDER BY ir.rolled_back_at DESC
LIMIT 20;
-- =============================================================================
-- 5. IN-PROGRESS RUNS - Currently processing batches
-- =============================================================================
-- Shows batches that are currently being processed (useful for debugging stalls)
SELECT id,
    source_system,
    source_batch_id,
    filename,
    worker_id,
    claimed_at,
    updated_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - updated_at)
        )::numeric,
        0
    ) AS seconds_since_heartbeat,
    CASE
        WHEN updated_at < now() - interval '30 minutes' THEN 'STALE - may be taken over'
        WHEN updated_at < now() - interval '5 minutes' THEN 'WARNING - no recent heartbeat'
        ELSE 'OK'
    END AS health_status
FROM ingest.import_runs
WHERE status = 'processing'
ORDER BY claimed_at DESC;
-- =============================================================================
-- 6. FAILED RUNS - Recent failures with error details
-- =============================================================================
-- Shows failed imports with error information for troubleshooting
SELECT id,
    source_system,
    source_batch_id,
    filename,
    rows_fetched,
    rows_errored,
    error_details->>'type' AS error_type,
    error_details->>'message' AS error_message,
    completed_at
FROM ingest.import_runs
WHERE status = 'failed'
ORDER BY completed_at DESC
LIMIT 25;
-- =============================================================================
-- 7. SOURCE SYSTEM STATS - Import stats by source system (last 7 days)
-- =============================================================================
-- Shows aggregate metrics per source system for capacity planning
SELECT source_system,
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS completed,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed,
    COUNT(*) FILTER (
        WHERE status = 'rolled_back'
    ) AS rolled_back,
    SUM(rows_fetched) AS total_rows_fetched,
    SUM(rows_inserted) AS total_rows_inserted,
    ROUND(
        AVG(
            EXTRACT(
                EPOCH
                FROM (completed_at - created_at)
            )
        )::numeric,
        1
    ) AS avg_duration_sec
FROM ingest.import_runs
WHERE created_at > now() - interval '7 days'
GROUP BY source_system
ORDER BY total_runs DESC;
-- =============================================================================
-- 8. ROW-LEVEL ERRORS - Errored rows with details
-- =============================================================================
-- Shows individual rows that failed during import
SELECT pr.id,
    pr.import_run_id,
    ir.filename,
    ir.source_system,
    pr.row_index,
    pr.plaintiff_name,
    pr.error_code,
    pr.error_message,
    pr.created_at
FROM ingest.plaintiffs_raw pr
    JOIN ingest.import_runs ir ON ir.id = pr.import_run_id
WHERE pr.status = 'failed'
ORDER BY pr.created_at DESC
LIMIT 50;
-- =============================================================================
-- 9. DEDUPE STATS - Row-level deduplication breakdown by run
-- =============================================================================
-- Shows how many rows were deduplicated per import run
SELECT ir.id,
    ir.filename,
    ir.source_system,
    COUNT(pr.id) AS total_rows,
    COUNT(*) FILTER (
        WHERE pr.status = 'pending'
    ) AS pending,
    COUNT(*) FILTER (
        WHERE pr.status = 'promoted'
    ) AS promoted,
    COUNT(*) FILTER (
        WHERE pr.status = 'skipped'
    ) AS skipped,
    COUNT(*) FILTER (
        WHERE pr.status = 'failed'
    ) AS failed,
    ir.created_at
FROM ingest.import_runs ir
    LEFT JOIN ingest.plaintiffs_raw pr ON pr.import_run_id = ir.id
GROUP BY ir.id,
    ir.filename,
    ir.source_system,
    ir.created_at
ORDER BY ir.created_at DESC
LIMIT 20;
-- =============================================================================
-- 10. STALE LOCK TAKEOVERS - Runs that were reclaimed from stale workers
-- =============================================================================
-- Shows cases where a crashed worker's batch was taken over
SELECT id,
    source_system,
    source_batch_id,
    filename,
    worker_id AS current_worker,
    error_details->>'previous_worker' AS previous_worker,
    error_details->>'takeover_reason' AS takeover_reason,
    error_details->>'takeover_at' AS takeover_at,
    status::text,
    updated_at
FROM ingest.import_runs
WHERE error_details ? 'takeover_reason'
ORDER BY updated_at DESC
LIMIT 20;
-- =============================================================================
-- 11. DAILY IMPORT VOLUME - Import volume over last 30 days
-- =============================================================================
-- Shows daily import activity for trend analysis
SELECT DATE(created_at) AS import_date,
    COUNT(*) AS total_runs,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS completed,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed,
    SUM(rows_fetched) AS total_rows,
    SUM(rows_inserted) AS total_inserted
FROM ingest.import_runs
WHERE created_at > now() - interval '30 days'
GROUP BY DATE(created_at)
ORDER BY import_date DESC;
-- =============================================================================
-- 12. CLAIM A NEW BATCH (Example RPC call)
-- =============================================================================
-- Example of how to claim a batch via RPC
/*
 SELECT * FROM ingest.claim_import_run(
 'simplicity',           -- source_system
 'batch-2026-01-15',     -- source_batch_id
 'abc123def456...',      -- file_hash
 'plaintiffs.csv',       -- filename
 'plaintiff',            -- import_kind
 'worker-1'              -- worker_id
 );
 */
-- =============================================================================
-- 13. ROLLBACK A RUN (Example RPC call)
-- =============================================================================
-- Example of how to rollback a batch via RPC
/*
 SELECT * FROM ingest.rollback_import_run(
 '123e4567-e89b-12d3-a456-426614174000',  -- run_id
 'Data quality issue discovered'           -- reason
 );
 */
-- =============================================================================
-- 14. RECONCILE A RUN (Example RPC call)
-- =============================================================================
-- Example of how to reconcile a batch via RPC
/*
 SELECT * FROM ingest.reconcile_import_run(
 '123e4567-e89b-12d3-a456-426614174000',  -- run_id
 100                                       -- expected_count (optional)
 );
 */