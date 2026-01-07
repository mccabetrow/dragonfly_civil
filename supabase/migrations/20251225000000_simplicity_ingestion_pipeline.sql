-- Migration: Simplicity Data Ingestion Pipeline
-- Description: Creates intake schema tables for Dec 29th vendor data export
-- Target: Dedicated pipeline for Simplicity vendor exports with staging,
--         validation, and upsert into public.judgments
-- ============================================================================
-- ============================================================================
-- 1. Ensure intake schema exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS intake;
-- ============================================================================
-- 2. intake.simplicity_batches - Track Simplicity import batches
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.simplicity_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    filename TEXT NOT NULL,
    source_reference TEXT,
    -- Vendor batch ID for idempotency
    row_count_total INTEGER NOT NULL DEFAULT 0,
    -- Total rows in CSV
    row_count_staged INTEGER NOT NULL DEFAULT 0,
    -- Rows staged to raw table
    row_count_valid INTEGER NOT NULL DEFAULT 0,
    -- Rows passing validation
    row_count_invalid INTEGER NOT NULL DEFAULT 0,
    -- Rows failing validation
    row_count_inserted INTEGER NOT NULL DEFAULT 0,
    -- Rows upserted to judgments
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'staging',
            'transforming',
            'upserting',
            'completed',
            'failed'
        )
    ),
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    staged_at TIMESTAMPTZ,
    -- When staging completed
    transformed_at TIMESTAMPTZ,
    -- When transform/validate completed
    completed_at TIMESTAMPTZ,
    -- When final upsert completed
    created_by TEXT -- Optional user reference
);
COMMENT ON TABLE intake.simplicity_batches IS 'Tracks Simplicity vendor CSV import batches with 3-step workflow';
COMMENT ON COLUMN intake.simplicity_batches.source_reference IS 'Vendor batch ID for preventing duplicate imports';
COMMENT ON COLUMN intake.simplicity_batches.status IS 'Batch status: pending → staging → transforming → upserting → completed/failed';
-- Indexes for batch management
CREATE INDEX IF NOT EXISTS idx_simplicity_batches_status ON intake.simplicity_batches(status)
WHERE status IN (
        'pending',
        'staging',
        'transforming',
        'upserting'
    );
CREATE INDEX IF NOT EXISTS idx_simplicity_batches_created_at ON intake.simplicity_batches(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_simplicity_batches_source_reference ON intake.simplicity_batches(source_reference)
WHERE source_reference IS NOT NULL;
-- ============================================================================
-- 3. intake.simplicity_raw_rows - Raw CSV rows as JSONB for audit
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.simplicity_raw_rows (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES intake.simplicity_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    -- 0-based row position in CSV
    raw_data JSONB NOT NULL,
    -- Original row as key-value pairs
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE intake.simplicity_raw_rows IS 'Raw Simplicity CSV rows stored as JSONB for audit trail and reprocessing';
CREATE INDEX IF NOT EXISTS idx_simplicity_raw_rows_batch ON intake.simplicity_raw_rows(batch_id);
CREATE INDEX IF NOT EXISTS idx_simplicity_raw_rows_batch_row ON intake.simplicity_raw_rows(batch_id, row_index);
-- ============================================================================
-- 4. intake.simplicity_validated_rows - Transformed and validated rows
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.simplicity_validated_rows (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES intake.simplicity_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    raw_row_id BIGINT REFERENCES intake.simplicity_raw_rows(id) ON DELETE
    SET NULL,
        -- Mapped canonical fields (matching public.judgments structure)
        case_number TEXT NOT NULL,
        plaintiff_name TEXT,
        defendant_name TEXT,
        judgment_amount NUMERIC(12, 2),
        -- Allow larger amounts
        entry_date DATE,
        -- Maps from Filing Date
        judgment_date DATE,
        court TEXT,
        county TEXT,
        -- Validation metadata
        validation_status TEXT NOT NULL DEFAULT 'valid' CHECK (
            validation_status IN ('valid', 'invalid', 'warning')
        ),
        validation_errors TEXT [],
        -- Array of error messages
        validation_warnings TEXT [],
        -- Array of warning messages
        -- Tracking
        created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
        -- Prevent duplicate case_number within same batch
        CONSTRAINT uq_simplicity_validated_batch_case UNIQUE (batch_id, case_number)
);
COMMENT ON TABLE intake.simplicity_validated_rows IS 'Validated Simplicity rows with canonical field mapping, ready for upsert';
COMMENT ON COLUMN intake.simplicity_validated_rows.validation_status IS 'valid = ready for upsert, invalid = blocked, warning = upsert with notes';
CREATE INDEX IF NOT EXISTS idx_simplicity_validated_rows_batch ON intake.simplicity_validated_rows(batch_id);
CREATE INDEX IF NOT EXISTS idx_simplicity_validated_rows_batch_status ON intake.simplicity_validated_rows(batch_id, validation_status);
CREATE INDEX IF NOT EXISTS idx_simplicity_validated_rows_case_number ON intake.simplicity_validated_rows(case_number);
-- ============================================================================
-- 5. intake.simplicity_failed_rows - Dead letter queue for failed rows
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.simplicity_failed_rows (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES intake.simplicity_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    raw_row_id BIGINT REFERENCES intake.simplicity_raw_rows(id) ON DELETE
    SET NULL,
        -- Error details
        error_stage TEXT NOT NULL CHECK (
            error_stage IN ('parse', 'validate', 'transform', 'upsert')
        ),
        error_code TEXT NOT NULL,
        error_message TEXT NOT NULL,
        raw_data JSONB,
        -- Copy of raw data for debugging
        -- Resolution tracking
        resolved_at TIMESTAMPTZ,
        resolved_by TEXT,
        resolution_notes TEXT,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE intake.simplicity_failed_rows IS 'Dead letter queue for Simplicity rows that failed processing';
COMMENT ON COLUMN intake.simplicity_failed_rows.error_stage IS 'Stage where error occurred: parse, validate, transform, or upsert';
CREATE INDEX IF NOT EXISTS idx_simplicity_failed_rows_batch ON intake.simplicity_failed_rows(batch_id);
CREATE INDEX IF NOT EXISTS idx_simplicity_failed_rows_unresolved ON intake.simplicity_failed_rows(batch_id)
WHERE resolved_at IS NULL;
-- ============================================================================
-- 6. Grant permissions for service role
-- ============================================================================
GRANT USAGE ON SCHEMA intake TO service_role;
GRANT ALL ON intake.simplicity_batches TO service_role;
GRANT ALL ON intake.simplicity_raw_rows TO service_role;
GRANT ALL ON intake.simplicity_validated_rows TO service_role;
GRANT ALL ON intake.simplicity_failed_rows TO service_role;
-- Grant sequence usage
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO service_role;
-- ============================================================================
-- 7. View for batch pipeline status
-- ============================================================================
CREATE OR REPLACE VIEW intake.v_simplicity_batch_status AS
SELECT b.id,
    b.filename,
    b.source_reference,
    b.status,
    b.row_count_total,
    b.row_count_staged,
    b.row_count_valid,
    b.row_count_invalid,
    b.row_count_inserted,
    b.error_summary,
    b.created_at,
    b.staged_at,
    b.transformed_at,
    b.completed_at,
    b.created_by,
    -- Calculated metrics
    CASE
        WHEN b.row_count_total > 0 THEN ROUND(
            (b.row_count_valid::NUMERIC / b.row_count_total) * 100,
            1
        )
        ELSE 0
    END AS validation_rate_pct,
    CASE
        WHEN b.row_count_valid > 0 THEN ROUND(
            (
                b.row_count_inserted::NUMERIC / b.row_count_valid
            ) * 100,
            1
        )
        ELSE 0
    END AS insert_rate_pct,
    -- Timing metrics (in seconds)
    EXTRACT(
        EPOCH
        FROM (b.staged_at - b.created_at)
    ) AS stage_duration_sec,
    EXTRACT(
        EPOCH
        FROM (b.transformed_at - b.staged_at)
    ) AS transform_duration_sec,
    EXTRACT(
        EPOCH
        FROM (b.completed_at - b.transformed_at)
    ) AS upsert_duration_sec,
    EXTRACT(
        EPOCH
        FROM (b.completed_at - b.created_at)
    ) AS total_duration_sec,
    -- Failed row count
    (
        SELECT COUNT(*)
        FROM intake.simplicity_failed_rows f
        WHERE f.batch_id = b.id
            AND f.resolved_at IS NULL
    ) AS unresolved_errors
FROM intake.simplicity_batches b
ORDER BY b.created_at DESC;
GRANT SELECT ON intake.v_simplicity_batch_status TO service_role;
COMMENT ON VIEW intake.v_simplicity_batch_status IS 'Batch status dashboard with timing metrics and error counts';
-- ============================================================================
-- 8. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';
