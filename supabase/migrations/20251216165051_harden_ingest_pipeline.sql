-- Migration: Harden ingest pipeline with import tracking
-- Adds file_hash to ingest_batches for duplicate detection
-- Creates ops.import_errors for row-level error logging
--
-- Dependencies: ops schema must exist
-- ============================================================================
-- 1. ADD FILE_HASH TO INGEST_BATCHES
-- ============================================================================
-- Add file_hash column for duplicate detection
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS file_hash TEXT;
-- Add force_reimport flag to allow bypassing duplicate check
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS force_reimport BOOLEAN DEFAULT FALSE;
-- Create index on file_hash for fast duplicate lookup
CREATE INDEX IF NOT EXISTS idx_ingest_batches_file_hash ON ops.ingest_batches (file_hash)
WHERE file_hash IS NOT NULL;
-- Comment
COMMENT ON COLUMN ops.ingest_batches.file_hash IS 'SHA-256 hash of CSV file contents for duplicate detection';
COMMENT ON COLUMN ops.ingest_batches.force_reimport IS 'If true, allow import even if file_hash already exists';
-- ============================================================================
-- 2. CREATE OPS.IMPORT_ERRORS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS ops.import_errors (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES ops.ingest_batches(id) ON DELETE CASCADE,
    row_number INTEGER NOT NULL,
    error_type TEXT NOT NULL,
    error_message TEXT NOT NULL,
    raw_data JSONB,
    field_name TEXT,
    field_value TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- Create indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_import_errors_batch_id ON ops.import_errors (batch_id);
CREATE INDEX IF NOT EXISTS idx_import_errors_error_type ON ops.import_errors (error_type);
CREATE INDEX IF NOT EXISTS idx_import_errors_created_at ON ops.import_errors (created_at DESC);
-- Comments
COMMENT ON TABLE ops.import_errors IS 'Row-level errors from CSV import processing';
COMMENT ON COLUMN ops.import_errors.batch_id IS 'Reference to the ingest batch';
COMMENT ON COLUMN ops.import_errors.row_number IS 'CSV row number (1-indexed, excluding header)';
COMMENT ON COLUMN ops.import_errors.error_type IS 'Error category: validation, parse, duplicate, insert, etc.';
COMMENT ON COLUMN ops.import_errors.error_message IS 'Human-readable error description';
COMMENT ON COLUMN ops.import_errors.raw_data IS 'Original row data as JSON for debugging';
COMMENT ON COLUMN ops.import_errors.field_name IS 'Specific field that caused the error (if applicable)';
COMMENT ON COLUMN ops.import_errors.field_value IS 'Value that caused the error (truncated)';
-- ============================================================================
-- 3. CREATE VIEW FOR IMPORT ERROR SUMMARY
-- ============================================================================
CREATE OR REPLACE VIEW ops.v_import_error_summary AS
SELECT b.id AS batch_id,
    b.filename,
    b.source,
    b.status,
    b.created_at,
    COUNT(e.id) AS total_errors,
    COUNT(DISTINCT e.row_number) AS rows_with_errors,
    jsonb_object_agg(
        COALESCE(e.error_type, 'unknown'),
        (
            SELECT COUNT(*)
            FROM ops.import_errors e2
            WHERE e2.batch_id = b.id
                AND e2.error_type = e.error_type
        )
    ) FILTER (
        WHERE e.error_type IS NOT NULL
    ) AS error_counts
FROM ops.ingest_batches b
    LEFT JOIN ops.import_errors e ON e.batch_id = b.id
GROUP BY b.id,
    b.filename,
    b.source,
    b.status,
    b.created_at
ORDER BY b.created_at DESC;
COMMENT ON VIEW ops.v_import_error_summary IS 'Summary of import errors by batch';
-- ============================================================================
-- 4. HELPER FUNCTION: CHECK FOR DUPLICATE FILE HASH
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.check_duplicate_file_hash(
        p_file_hash TEXT,
        p_force BOOLEAN DEFAULT FALSE
    ) RETURNS TABLE (
        is_duplicate BOOLEAN,
        existing_batch_id UUID,
        existing_status TEXT,
        existing_created_at TIMESTAMPTZ
    ) AS $$ BEGIN IF p_force THEN -- Skip duplicate check when force flag is set
    RETURN QUERY
SELECT FALSE::BOOLEAN,
    NULL::UUID,
    NULL::TEXT,
    NULL::TIMESTAMPTZ;
RETURN;
END IF;
RETURN QUERY
SELECT TRUE,
    b.id,
    b.status,
    b.created_at
FROM ops.ingest_batches b
WHERE b.file_hash = p_file_hash
    AND b.status IN ('completed', 'processing')
ORDER BY b.created_at DESC
LIMIT 1;
-- If no rows returned, return not duplicate
IF NOT FOUND THEN RETURN QUERY
SELECT FALSE::BOOLEAN,
    NULL::UUID,
    NULL::TEXT,
    NULL::TIMESTAMPTZ;
END IF;
END;
$$ LANGUAGE plpgsql STABLE;
COMMENT ON FUNCTION ops.check_duplicate_file_hash IS 'Check if a file hash already exists in completed/processing batches';
-- ============================================================================
-- 5. ENABLE RLS ON IMPORT_ERRORS
-- ============================================================================
ALTER TABLE ops.import_errors ENABLE ROW LEVEL SECURITY;
-- Allow service role full access
CREATE POLICY "Service role can manage import_errors" ON ops.import_errors FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Allow authenticated users to read
CREATE POLICY "Authenticated can read import_errors" ON ops.import_errors FOR
SELECT TO authenticated USING (true);
