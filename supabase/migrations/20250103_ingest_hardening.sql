-- ============================================================================
-- Migration: 20250103_ingest_hardening.sql
-- Description: World-Class Ingestion Schema Hardening
-- ============================================================================
-- Goals:
--   1. IDEMPOTENCY: file_hash UNIQUE constraint prevents duplicate uploads
--   2. ERROR BUDGET: error_threshold_percent with rejection_reason audit trail
--   3. OBSERVABILITY: parse_duration_ms, db_duration_ms timing metrics
--   4. ERROR TRACKING: intake.row_errors for granular error logging
--   5. DEDUPLICATION: public.judgments UNIQUE on case_number + court_code
-- ============================================================================
BEGIN;
-- ============================================================================
-- SECTION 1: BATCH IDEMPOTENCY (intake.simplicity_batches)
-- ============================================================================
-- 1.1 Add file_hash column for content-addressed idempotency
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS file_hash TEXT;
-- 1.2 Create UNIQUE index on file_hash (partial: ignores NULL for legacy rows)
DROP INDEX IF EXISTS intake.uq_simplicity_batches_file_hash;
DROP INDEX IF EXISTS intake.uq_simplicity_batches_file_hash_unique;
CREATE UNIQUE INDEX uq_simplicity_batches_file_hash ON intake.simplicity_batches(file_hash)
WHERE file_hash IS NOT NULL;
COMMENT ON COLUMN intake.simplicity_batches.file_hash IS 'SHA-256 hash of source file content. Enforces batch idempotency - prevents duplicate uploads.';
-- ============================================================================
-- SECTION 2: ERROR BUDGET CONTROLS
-- ============================================================================
-- 2.1 Error threshold percentage (default: 10%)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS error_threshold_percent INTEGER NOT NULL DEFAULT 10;
COMMENT ON COLUMN intake.simplicity_batches.error_threshold_percent IS 'Maximum allowed error rate (percentage). Batches exceeding this threshold are rejected before any inserts.';
-- 2.2 Add constraint: threshold must be 0-100
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'chk_error_threshold_range'
        AND conrelid = 'intake.simplicity_batches'::regclass
) THEN
ALTER TABLE intake.simplicity_batches
ADD CONSTRAINT chk_error_threshold_range CHECK (
        error_threshold_percent >= 0
        AND error_threshold_percent <= 100
    );
END IF;
END $$;
-- 2.3 Rejection reason for failed quality control
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS rejection_reason TEXT;
COMMENT ON COLUMN intake.simplicity_batches.rejection_reason IS 'Human-readable explanation for batch failure (e.g., "Error rate 15% exceeded limit 10%").';
-- 2.4 Constraint: rejection_reason only valid when status = 'failed'
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
-- SECTION 3: OBSERVABILITY TIMING METRICS
-- ============================================================================
-- 3.1 Parse duration (CSV parsing + validation phase)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS parse_duration_ms INTEGER;
COMMENT ON COLUMN intake.simplicity_batches.parse_duration_ms IS 'Time spent parsing CSV and validating rows (milliseconds). Excludes DB operations.';
-- 3.2 Database duration (insert/upsert phase)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS db_duration_ms INTEGER;
COMMENT ON COLUMN intake.simplicity_batches.db_duration_ms IS 'Time spent inserting/upserting rows to database (milliseconds). Excludes parsing.';
-- 3.3 Ensure row_count_duplicate column exists
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS row_count_duplicate INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN intake.simplicity_batches.row_count_duplicate IS 'Rows skipped because they already exist in public.judgments (deduplication).';
-- ============================================================================
-- SECTION 4: GRANULAR ERROR TRACKING (intake.row_errors)
-- ============================================================================
-- 4.1 Create the row_errors table
CREATE TABLE IF NOT EXISTS intake.row_errors (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES intake.simplicity_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    error_code TEXT NOT NULL,
    error_message TEXT NOT NULL,
    raw_data JSONB,
    -- Metadata
    error_stage TEXT NOT NULL DEFAULT 'validate' CHECK (
        error_stage IN ('parse', 'validate', 'transform', 'upsert')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Resolution tracking (for manual remediation)
    resolved_at TIMESTAMPTZ,
    resolved_by TEXT,
    resolution_notes TEXT
);
-- 4.2 Indexes for fast UI lookups
CREATE INDEX IF NOT EXISTS idx_row_errors_batch_id ON intake.row_errors(batch_id);
CREATE INDEX IF NOT EXISTS idx_row_errors_batch_row ON intake.row_errors(batch_id, row_index);
CREATE INDEX IF NOT EXISTS idx_row_errors_unresolved ON intake.row_errors(batch_id)
WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_row_errors_code ON intake.row_errors(error_code);
-- 4.3 Unique constraint: one error per row per stage (prevents duplicate logging)
CREATE UNIQUE INDEX IF NOT EXISTS uq_row_errors_batch_row_stage ON intake.row_errors(batch_id, row_index, error_stage)
WHERE resolved_at IS NULL;
COMMENT ON TABLE intake.row_errors IS 'Granular error tracking for ingestion pipeline. One row per error per batch row.';
COMMENT ON COLUMN intake.row_errors.row_index IS 'Zero-based row index in the source CSV file.';
COMMENT ON COLUMN intake.row_errors.error_code IS 'Machine-readable error code (e.g., MISSING_CASE_NUMBER, INVALID_AMOUNT).';
COMMENT ON COLUMN intake.row_errors.error_message IS 'Human-readable error description for UI display.';
COMMENT ON COLUMN intake.row_errors.raw_data IS 'Original row data as JSONB for debugging and manual remediation.';
COMMENT ON COLUMN intake.row_errors.error_stage IS 'Pipeline stage where error occurred: parse, validate, transform, or upsert.';
-- 4.4 Grant permissions
GRANT ALL ON intake.row_errors TO service_role;
GRANT USAGE,
    SELECT ON SEQUENCE intake.row_errors_id_seq TO service_role;
-- 4.5 Enable RLS (service_role only access pattern)
ALTER TABLE intake.row_errors ENABLE ROW LEVEL SECURITY;
ALTER TABLE intake.row_errors FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS service_row_errors_all ON intake.row_errors;
CREATE POLICY service_row_errors_all ON intake.row_errors FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ============================================================================
-- SECTION 5: JUDGMENT DEDUPLICATION (public.judgments)
-- ============================================================================
-- 5.1 Ensure case_number UNIQUE constraint exists
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'judgments_case_number_key'
        AND conrelid = 'public.judgments'::regclass
) THEN
ALTER TABLE public.judgments
ADD CONSTRAINT judgments_case_number_key UNIQUE (case_number);
END IF;
END $$;
COMMENT ON CONSTRAINT judgments_case_number_key ON public.judgments IS 'Business key uniqueness: prevents duplicate case ingestion at the database level.';
-- 5.2 Add composite unique constraint for court_code + case_number (if court_code exists)
DO $$ BEGIN -- Only create if court_code column exists
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'court_code'
) THEN -- Create composite unique index if not exists
IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'public'
        AND tablename = 'judgments'
        AND indexname = 'uq_judgments_court_case'
) THEN CREATE UNIQUE INDEX uq_judgments_court_case ON public.judgments(court_code, case_number)
WHERE court_code IS NOT NULL;
END IF;
END IF;
END $$;
-- ============================================================================
-- SECTION 6: BATCH PERFORMANCE INDEX
-- ============================================================================
-- Index for finding batches by status (dashboard queries)
CREATE INDEX IF NOT EXISTS idx_simplicity_batches_status_created ON intake.simplicity_batches(status, created_at DESC);
-- Index for finding recent failed batches
CREATE INDEX IF NOT EXISTS idx_simplicity_batches_failed_recent ON intake.simplicity_batches(created_at DESC)
WHERE status = 'failed';
-- ============================================================================
-- SECTION 7: OBSERVABILITY VIEW
-- ============================================================================
CREATE OR REPLACE VIEW intake.v_batch_observability AS
SELECT b.id AS batch_id,
    b.filename,
    b.status,
    b.file_hash,
    -- Row counts
    b.row_count_total,
    b.row_count_staged,
    b.row_count_valid,
    b.row_count_invalid,
    b.row_count_inserted,
    COALESCE(b.row_count_duplicate, 0) AS row_count_duplicate,
    -- Error budget
    b.error_threshold_percent,
    b.rejection_reason,
    CASE
        WHEN b.row_count_total > 0 THEN ROUND(
            100.0 * COALESCE(b.row_count_invalid, 0) / b.row_count_total,
            2
        )
        ELSE 0
    END AS error_rate_percent,
    -- Timing metrics
    b.parse_duration_ms,
    b.db_duration_ms,
    COALESCE(b.parse_duration_ms, 0) + COALESCE(b.db_duration_ms, 0) AS total_duration_ms,
    -- Throughput (rows/second)
    CASE
        WHEN COALESCE(b.parse_duration_ms, 0) + COALESCE(b.db_duration_ms, 0) > 0 THEN ROUND(
            1000.0 * b.row_count_total / (
                COALESCE(b.parse_duration_ms, 0) + COALESCE(b.db_duration_ms, 0)
            ),
            1
        )
        ELSE NULL
    END AS rows_per_second,
    -- Error summary (from row_errors)
    (
        SELECT COUNT(*)
        FROM intake.row_errors e
        WHERE e.batch_id = b.id
    ) AS error_count,
    (
        SELECT COUNT(*)
        FROM intake.row_errors e
        WHERE e.batch_id = b.id
            AND e.resolved_at IS NULL
    ) AS unresolved_error_count,
    -- Timestamps
    b.created_at,
    b.completed_at,
    EXTRACT(
        EPOCH
        FROM (b.completed_at - b.created_at)
    ) * 1000 AS wall_clock_ms
FROM intake.simplicity_batches b
ORDER BY b.created_at DESC;
COMMENT ON VIEW intake.v_batch_observability IS 'World-class batch observability: error rates, timing, throughput, and error counts.';
GRANT SELECT ON intake.v_batch_observability TO service_role;
-- ============================================================================
-- SECTION 8: ERROR SUMMARY VIEW
-- ============================================================================
CREATE OR REPLACE VIEW intake.v_error_summary AS
SELECT e.batch_id,
    e.error_code,
    e.error_stage,
    COUNT(*) AS occurrence_count,
    MIN(e.created_at) AS first_seen,
    MAX(e.created_at) AS last_seen,
    COUNT(*) FILTER (
        WHERE e.resolved_at IS NULL
    ) AS unresolved_count
FROM intake.row_errors e
GROUP BY e.batch_id,
    e.error_code,
    e.error_stage
ORDER BY occurrence_count DESC;
COMMENT ON VIEW intake.v_error_summary IS 'Aggregated error counts by code and stage. Use for identifying systematic issues.';
GRANT SELECT ON intake.v_error_summary TO service_role;
-- ============================================================================
-- SECTION 9: MIGRATION COMPLETE
-- ============================================================================
DO $$ BEGIN RAISE NOTICE '';
RAISE NOTICE '════════════════════════════════════════════════════════════════════';
RAISE NOTICE '✅ Migration 20250103_ingest_hardening.sql COMPLETE';
RAISE NOTICE '════════════════════════════════════════════════════════════════════';
RAISE NOTICE '';
RAISE NOTICE '📦 BATCH IDEMPOTENCY:';
RAISE NOTICE '   • intake.simplicity_batches.file_hash (UNIQUE)';
RAISE NOTICE '';
RAISE NOTICE '🛡️  ERROR BUDGET:';
RAISE NOTICE '   • error_threshold_percent (default: 10%%)';
RAISE NOTICE '   • rejection_reason (audit trail)';
RAISE NOTICE '';
RAISE NOTICE '⏱️  OBSERVABILITY:';
RAISE NOTICE '   • parse_duration_ms, db_duration_ms';
RAISE NOTICE '   • intake.v_batch_observability view';
RAISE NOTICE '';
RAISE NOTICE '🚨 ERROR TRACKING:';
RAISE NOTICE '   • intake.row_errors table';
RAISE NOTICE '   • intake.v_error_summary view';
RAISE NOTICE '';
RAISE NOTICE '🔒 DEDUPLICATION:';
RAISE NOTICE '   • public.judgments.case_number UNIQUE';
RAISE NOTICE '';
RAISE NOTICE '════════════════════════════════════════════════════════════════════';
END $$;
COMMIT;
