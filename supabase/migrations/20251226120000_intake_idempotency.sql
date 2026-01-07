-- Migration: Intake Idempotency Hardening
-- Description: Enforce strict uniqueness constraints on intake pipeline tables
--              to guarantee 100% reliability and prevent duplicate processing.
-- ============================================================================
-- ============================================================================
-- 1. UNIQUE constraint on intake.simplicity_batches (file_hash)
-- Prevents processing the same CSV file twice
-- ============================================================================
-- Add file_hash column if not exists
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS file_hash TEXT;
-- Create unique index on file_hash (allows NULLs but unique non-nulls)
CREATE UNIQUE INDEX IF NOT EXISTS uq_simplicity_batches_file_hash ON intake.simplicity_batches(file_hash)
WHERE file_hash IS NOT NULL;
COMMENT ON COLUMN intake.simplicity_batches.file_hash IS 'SHA-256 hash of source file for idempotent processing';
-- ============================================================================
-- 2. UNIQUE constraint on intake.simplicity_raw_rows (batch_id, row_index)
-- Prevents duplicate raw rows within a batch
-- ============================================================================
-- Drop if exists and recreate to ensure correctness
DROP INDEX IF EXISTS intake.uq_simplicity_raw_rows_batch_row;
CREATE UNIQUE INDEX uq_simplicity_raw_rows_batch_row ON intake.simplicity_raw_rows(batch_id, row_index);
COMMENT ON INDEX intake.uq_simplicity_raw_rows_batch_row IS 'Ensures each row index is unique within a batch';
-- ============================================================================
-- 3. UNIQUE constraint on intake.simplicity_validated_rows (raw_row_id)
-- Prevents validating the same raw row twice
-- ============================================================================
-- Add unique constraint on raw_row_id (one validated row per raw row)
DROP INDEX IF EXISTS intake.uq_simplicity_validated_raw_row;
CREATE UNIQUE INDEX uq_simplicity_validated_raw_row ON intake.simplicity_validated_rows(raw_row_id)
WHERE raw_row_id IS NOT NULL;
COMMENT ON INDEX intake.uq_simplicity_validated_raw_row IS 'Ensures each raw row is validated at most once';
-- ============================================================================
-- 4. UNIQUE constraint on ops.job_queue (job_type, dedup_key)
-- Prevents duplicate job submissions
-- ============================================================================
-- Add dedup_key column if not exists
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS dedup_key TEXT;
-- Create unique index on (job_type, dedup_key) for idempotent job submission
DROP INDEX IF EXISTS ops.uq_job_queue_type_dedup;
CREATE UNIQUE INDEX uq_job_queue_type_dedup ON ops.job_queue(job_type, dedup_key)
WHERE dedup_key IS NOT NULL
    AND status NOT IN ('completed', 'failed');
COMMENT ON COLUMN ops.job_queue.dedup_key IS 'Optional deduplication key. Jobs with same (job_type, dedup_key) are deduplicated.';
COMMENT ON INDEX ops.uq_job_queue_type_dedup IS 'Prevents duplicate active jobs with same type and dedup_key';
-- ============================================================================
-- 5. Enhanced error tracking on intake.simplicity_failed_rows
-- Add retryable flag and correlation_id for error analysis
-- ============================================================================
-- Add retryable column
ALTER TABLE intake.simplicity_failed_rows
ADD COLUMN IF NOT EXISTS retryable BOOLEAN NOT NULL DEFAULT true;
-- Add correlation_id for tracing
ALTER TABLE intake.simplicity_failed_rows
ADD COLUMN IF NOT EXISTS correlation_id UUID;
-- Add index for finding retryable errors
CREATE INDEX IF NOT EXISTS idx_simplicity_failed_rows_retryable ON intake.simplicity_failed_rows(batch_id, retryable)
WHERE resolved_at IS NULL
    AND retryable = true;
COMMENT ON COLUMN intake.simplicity_failed_rows.retryable IS 'Whether this error can be retried (validation errors are not retryable)';
COMMENT ON COLUMN intake.simplicity_failed_rows.correlation_id IS 'UUID for correlating errors across pipeline stages';
-- ============================================================================
-- 6. UNIQUE constraint on intake.simplicity_failed_rows (batch_id, row_index, error_stage)
-- Prevents duplicate error records for the same row at the same stage
-- ============================================================================
DROP INDEX IF EXISTS intake.uq_simplicity_failed_rows_batch_row_stage;
CREATE UNIQUE INDEX uq_simplicity_failed_rows_batch_row_stage ON intake.simplicity_failed_rows(batch_id, row_index, error_stage)
WHERE resolved_at IS NULL;
COMMENT ON INDEX intake.uq_simplicity_failed_rows_batch_row_stage IS 'One unresolved error per row per stage';
-- ============================================================================
-- 7. intake.view_batch_progress - Dashboard view for batch monitoring
-- ============================================================================
CREATE OR REPLACE VIEW intake.view_batch_progress AS WITH batch_counts AS (
        SELECT b.id AS batch_id,
            b.filename,
            b.source_reference,
            b.status AS batch_status,
            b.created_at,
            b.row_count_total AS total_rows,
            b.row_count_staged AS staged_count,
            b.row_count_valid AS valid_count,
            b.row_count_invalid AS invalid_count,
            b.row_count_inserted AS inserted_count,
            b.error_summary,
            -- Count raw rows
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM intake.simplicity_raw_rows r
                    WHERE r.batch_id = b.id
                ),
                0
            ) AS raw_row_count,
            -- Count validated rows
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM intake.simplicity_validated_rows v
                    WHERE v.batch_id = b.id
                ),
                0
            ) AS validated_row_count,
            -- Count successful validations
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM intake.simplicity_validated_rows v
                    WHERE v.batch_id = b.id
                        AND v.validation_status = 'valid'
                ),
                0
            ) AS success_count,
            -- Count failed rows (unresolved)
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM intake.simplicity_failed_rows f
                    WHERE f.batch_id = b.id
                        AND f.resolved_at IS NULL
                ),
                0
            ) AS failed_count,
            -- Count jobs created for this batch
            COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue j
                    WHERE j.payload->>'batch_id' = b.id::text
                ),
                0
            ) AS job_count
        FROM intake.simplicity_batches b
    )
SELECT batch_id,
    filename,
    source_reference,
    batch_status,
    total_rows,
    raw_row_count AS processed_count,
    success_count,
    failed_count,
    job_count,
    -- Computed status for dashboard
    CASE
        WHEN batch_status = 'completed' THEN 'Complete'
        WHEN batch_status = 'failed' THEN 'Failed'
        WHEN batch_status IN ('staging', 'transforming', 'upserting') THEN 'Processing'
        WHEN batch_status = 'pending' THEN 'Pending'
        ELSE 'Unknown'
    END AS status,
    -- Progress percentage
    CASE
        WHEN total_rows > 0 THEN ROUND((raw_row_count::NUMERIC / total_rows) * 100, 1)
        ELSE 0
    END AS progress_pct,
    -- Success rate
    CASE
        WHEN raw_row_count > 0 THEN ROUND(
            (success_count::NUMERIC / raw_row_count) * 100,
            1
        )
        ELSE 0
    END AS success_rate_pct,
    created_at,
    error_summary
FROM batch_counts
ORDER BY created_at DESC;
GRANT SELECT ON intake.view_batch_progress TO service_role;
COMMENT ON VIEW intake.view_batch_progress IS 'Dashboard view for monitoring batch import progress with live counts';
-- ============================================================================
-- 8. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';
