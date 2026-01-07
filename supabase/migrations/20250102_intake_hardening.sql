-- Migration: Intake Pipeline Hardening
-- Description: Production-grade safety mechanisms for the ingestion pipeline
-- ============================================================================
-- Goals:
--   1. Add file_hash UNIQUE constraint for idempotency
--   2. Add error budget fields for quality control
--   3. Add timing metrics for observability
--   4. Add rejection_reason for failed batch audit
-- ============================================================================
-- ============================================================================
-- 1. IDEMPOTENCY: Ensure file_hash column exists with UNIQUE constraint
-- ============================================================================
-- Add file_hash if missing (may already exist from prior migrations)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS file_hash TEXT;
-- Create unique index on file_hash (allows NULLs but unique non-nulls)
CREATE UNIQUE INDEX IF NOT EXISTS uq_simplicity_batches_file_hash_unique ON intake.simplicity_batches(file_hash)
WHERE file_hash IS NOT NULL;
COMMENT ON COLUMN intake.simplicity_batches.file_hash IS 'SHA-256 hash of source file content. Enforces batch idempotency - prevents duplicate uploads.';
-- ============================================================================
-- 2. ERROR BUDGET: Quality control thresholds
-- ============================================================================
-- Error threshold percentage (default: 10%)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS error_threshold_percent INTEGER NOT NULL DEFAULT 10;
COMMENT ON COLUMN intake.simplicity_batches.error_threshold_percent IS 'Maximum allowed error rate (percentage). Batches exceeding this threshold are rejected.';
-- Rejection reason for failed quality control
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
COMMENT ON COLUMN intake.simplicity_batches.rejection_reason IS 'Human-readable explanation for batch failure (e.g., "Error rate 15% exceeded limit 10%").';
-- ============================================================================
-- 3. OBSERVABILITY: Timing metrics
-- ============================================================================
-- Parse duration in milliseconds
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS parse_duration_ms INTEGER;
COMMENT ON COLUMN intake.simplicity_batches.parse_duration_ms IS 'Time spent parsing CSV and validating rows (milliseconds).';
-- Database duration in milliseconds (insert/upsert phase)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS db_duration_ms INTEGER;
COMMENT ON COLUMN intake.simplicity_batches.db_duration_ms IS 'Time spent inserting/upserting rows to database (milliseconds).';
-- ============================================================================
-- 4. Add check constraint for valid rejection reasons
-- ============================================================================
-- Only allow rejection_reason when status is 'failed'
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_rejection_reason_only_on_failed'
        AND conrelid = 'intake.simplicity_batches'::regclass
) THEN
ALTER TABLE intake.simplicity_batches
ADD CONSTRAINT chk_rejection_reason_only_on_failed CHECK (
        (rejection_reason IS NULL)
        OR (status = 'failed')
    );
END IF;
END $$;
-- ============================================================================
-- 5. Index for performance: find batches by status
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_simplicity_batches_status_created ON intake.simplicity_batches(status, created_at DESC);
-- ============================================================================
-- 5.5 Ensure row_count_duplicate column exists (may be missing on some envs)
-- ============================================================================
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS row_count_duplicate INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN intake.simplicity_batches.row_count_duplicate IS 'Rows skipped because they already exist in public.judgments (deduplication).';
-- ============================================================================
-- 6. Update view for batch monitoring (include new fields)
-- ============================================================================
CREATE OR REPLACE VIEW intake.view_batch_metrics AS
SELECT id AS batch_id,
    filename,
    status,
    file_hash,
    row_count_total,
    row_count_staged,
    row_count_valid,
    row_count_invalid,
    row_count_inserted,
    COALESCE(row_count_duplicate, 0) AS row_count_duplicate,
    error_threshold_percent,
    rejection_reason,
    parse_duration_ms,
    db_duration_ms,
    -- Computed error rate
    CASE
        WHEN row_count_total > 0 THEN ROUND(
            100.0 * COALESCE(row_count_invalid, 0) / row_count_total,
            2
        )
        ELSE 0
    END AS error_rate_percent,
    -- Computed throughput (rows/second)
    CASE
        WHEN COALESCE(parse_duration_ms, 0) + COALESCE(db_duration_ms, 0) > 0 THEN ROUND(
            1000.0 * row_count_total / (
                COALESCE(parse_duration_ms, 0) + COALESCE(db_duration_ms, 0)
            ),
            1
        )
        ELSE NULL
    END AS rows_per_second,
    created_at,
    completed_at,
    -- Total duration
    EXTRACT(
        EPOCH
        FROM (completed_at - created_at)
    ) * 1000 AS total_duration_ms
FROM intake.simplicity_batches
ORDER BY created_at DESC;
COMMENT ON VIEW intake.view_batch_metrics IS 'Batch performance metrics for observability dashboard. Includes error rates, timing, and throughput.';
-- Grant access to view
GRANT SELECT ON intake.view_batch_metrics TO service_role;
-- ============================================================================
-- 7. Migration complete
-- ============================================================================
DO $$ BEGIN RAISE NOTICE '✅ Migration complete: intake_hardening';
RAISE NOTICE '   Added: file_hash UNIQUE, error_threshold_percent, rejection_reason';
RAISE NOTICE '   Added: parse_duration_ms, db_duration_ms';
RAISE NOTICE '   Created: intake.view_batch_metrics';
END $$;
