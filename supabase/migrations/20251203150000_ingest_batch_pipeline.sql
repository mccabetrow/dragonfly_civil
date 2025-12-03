-- Migration: Enterprise-grade ingest batch pipeline
-- Version: Dragonfly Engine v0.2.x
-- Description: Creates tables for batch-based CSV ingestion with staging and validation
-- ============================================================================
-- 1. Ensure schemas exist
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS judgments;
-- ============================================================================
-- 2. ops.ingest_batches - Track all ingestion batches
-- ============================================================================
CREATE TABLE IF NOT EXISTS ops.ingest_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
    -- e.g., 'simplicity', 'jbi', 'manual'
    filename TEXT NOT NULL,
    row_count_raw INTEGER NOT NULL DEFAULT 0,
    row_count_valid INTEGER NOT NULL DEFAULT 0,
    row_count_invalid INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processing', 'completed', 'failed')
    ),
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    created_by TEXT -- nullable for now, will wire to auth.users later
);
COMMENT ON TABLE ops.ingest_batches IS 'Tracks all CSV ingestion batches with status and row counts';
COMMENT ON COLUMN ops.ingest_batches.source IS 'Source system: simplicity, jbi, manual, etc.';
COMMENT ON COLUMN ops.ingest_batches.status IS 'Batch status: pending, processing, completed, failed';
-- Index for querying pending batches (scheduler job)
CREATE INDEX IF NOT EXISTS idx_ingest_batches_status ON ops.ingest_batches(status)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_ingest_batches_created_at ON ops.ingest_batches(created_at DESC);
-- ============================================================================
-- 3. judgments.staging_simplicity_raw - Raw rows as jsonb
-- ============================================================================
CREATE TABLE IF NOT EXISTS judgments.staging_simplicity_raw (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES ops.ingest_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    raw_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE judgments.staging_simplicity_raw IS 'Raw CSV rows stored as JSONB for audit and reprocessing';
CREATE INDEX IF NOT EXISTS idx_staging_simplicity_raw_batch ON judgments.staging_simplicity_raw(batch_id);
CREATE INDEX IF NOT EXISTS idx_staging_simplicity_raw_batch_row ON judgments.staging_simplicity_raw(batch_id, row_index);
-- ============================================================================
-- 4. judgments.staging_simplicity_clean - Normalized and validated rows
-- ============================================================================
CREATE TABLE IF NOT EXISTS judgments.staging_simplicity_clean (
    id BIGSERIAL PRIMARY KEY,
    batch_id UUID NOT NULL REFERENCES ops.ingest_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    -- Normalized fields
    plaintiff_name TEXT,
    defendant_name TEXT,
    case_number TEXT,
    judgment_amount NUMERIC,
    judgment_date DATE,
    court TEXT,
    county TEXT,
    source_batch TEXT,
    -- Validation metadata
    validation_status TEXT NOT NULL DEFAULT 'valid' CHECK (validation_status IN ('valid', 'invalid')),
    validation_errors TEXT [],
    -- null for valid rows
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE judgments.staging_simplicity_clean IS 'Normalized and validated CSV rows ready for processing';
COMMENT ON COLUMN judgments.staging_simplicity_clean.validation_status IS 'valid or invalid based on parsing';
COMMENT ON COLUMN judgments.staging_simplicity_clean.validation_errors IS 'Array of error messages for invalid rows';
CREATE INDEX IF NOT EXISTS idx_staging_simplicity_clean_batch ON judgments.staging_simplicity_clean(batch_id);
CREATE INDEX IF NOT EXISTS idx_staging_simplicity_clean_batch_status ON judgments.staging_simplicity_clean(batch_id, validation_status);
-- ============================================================================
-- 5. judgments.imported_simplicity_cases - Canonical imported cases
-- ============================================================================
CREATE TABLE IF NOT EXISTS judgments.imported_simplicity_cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    case_number TEXT NOT NULL,
    court TEXT,
    plaintiff_name TEXT,
    defendant_name TEXT,
    judgment_amount NUMERIC,
    judgment_date DATE,
    county TEXT,
    source_batch_id UUID REFERENCES ops.ingest_batches(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Uniqueness constraint for idempotent upserts
    CONSTRAINT uq_imported_simplicity_case_court UNIQUE (case_number, court)
);
COMMENT ON TABLE judgments.imported_simplicity_cases IS 'Canonical imported Simplicity cases with deduplication';
CREATE INDEX IF NOT EXISTS idx_imported_simplicity_cases_case_number ON judgments.imported_simplicity_cases(case_number);
CREATE INDEX IF NOT EXISTS idx_imported_simplicity_cases_batch ON judgments.imported_simplicity_cases(source_batch_id);
-- Trigger for updated_at
CREATE OR REPLACE FUNCTION judgments.set_updated_at() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_imported_simplicity_cases_updated_at ON judgments.imported_simplicity_cases;
CREATE TRIGGER trg_imported_simplicity_cases_updated_at BEFORE
UPDATE ON judgments.imported_simplicity_cases FOR EACH ROW EXECUTE FUNCTION judgments.set_updated_at();
-- ============================================================================
-- 6. Grant permissions for service role access
-- ============================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT USAGE ON SCHEMA judgments TO service_role;
GRANT ALL ON ops.ingest_batches TO service_role;
GRANT ALL ON judgments.staging_simplicity_raw TO service_role;
GRANT ALL ON judgments.staging_simplicity_clean TO service_role;
GRANT ALL ON judgments.imported_simplicity_cases TO service_role;
-- Grant sequence usage for serial columns
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA judgments TO service_role;
-- ============================================================================
-- 7. View for batch summary with error preview
-- ============================================================================
CREATE OR REPLACE VIEW ops.v_ingest_batches AS
SELECT b.id,
    b.source,
    b.filename,
    b.row_count_raw,
    b.row_count_valid,
    b.row_count_invalid,
    b.status,
    b.error_summary,
    b.created_at,
    b.processed_at,
    b.created_by,
    CASE
        WHEN b.row_count_raw > 0 THEN ROUND(
            (b.row_count_valid::NUMERIC / b.row_count_raw) * 100,
            1
        )
        ELSE 0
    END AS success_rate_pct,
    EXTRACT(
        EPOCH
        FROM (b.processed_at - b.created_at)
    ) AS processing_seconds
FROM ops.ingest_batches b
ORDER BY b.created_at DESC;
GRANT SELECT ON ops.v_ingest_batches TO service_role;
COMMENT ON VIEW ops.v_ingest_batches IS 'Batch summary with success rate and timing metrics';