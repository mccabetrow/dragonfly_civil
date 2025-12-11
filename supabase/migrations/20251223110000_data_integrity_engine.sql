-- ============================================================================
-- Migration: Data Integrity & Reconciliation Engine
-- Created: 2025-12-23
-- Purpose: Create audit log and dead letter queue for data integrity tracking
-- ============================================================================
-- 
-- This migration creates the foundational tables for:
--   1. ops.ingest_audit_log - Tracks every row's lifecycle through ingestion
--   2. ops.data_discrepancies - Dead letter queue for failed/rejected rows
--   3. ops.v_integrity_dashboard - Real-time integrity metrics for dashboard
--
-- Business Goal: Absolute proof that every row ingested from Simplicity or
-- FOIL is stored perfectly. If a row fails, it goes to the Dead Letter Queue
-- for manual inspection and retry.
--
-- ============================================================================
-- ============================================================================
-- 1. Row Lifecycle Audit Log
-- ============================================================================
-- Tracks every row through its lifecycle: received -> parsed -> validated -> stored
-- This provides complete traceability for compliance and debugging.
CREATE TABLE IF NOT EXISTS ops.ingest_audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Batch context
    batch_id uuid NOT NULL REFERENCES ops.ingest_batches(id) ON DELETE CASCADE,
    row_index integer NOT NULL,
    -- Lifecycle stage tracking
    stage text NOT NULL CHECK (
        stage IN (
            'received',
            'parsed',
            'validated',
            'stored',
            'failed'
        )
    ),
    -- Timing
    received_at timestamptz NOT NULL DEFAULT now(),
    parsed_at timestamptz,
    validated_at timestamptz,
    stored_at timestamptz,
    -- Data snapshot (for debugging failed rows)
    raw_data jsonb,
    parsed_data jsonb,
    -- Result tracking
    judgment_id uuid,
    -- Set when stage = 'stored'
    case_number text,
    -- Extracted for quick lookup
    -- Error info (for stage = 'failed')
    error_stage text,
    -- Which stage failed: 'parse', 'validate', 'store'
    error_code text,
    error_message text,
    -- Checksums for integrity verification
    raw_checksum text,
    -- MD5/SHA256 of raw row
    stored_checksum text,
    -- Checksum after storage for verification
    created_at timestamptz NOT NULL DEFAULT now(),
    -- Each row in a batch can only have one audit entry
    CONSTRAINT uq_audit_log_batch_row UNIQUE (batch_id, row_index)
);
COMMENT ON TABLE ops.ingest_audit_log IS 'Complete lifecycle audit trail for every ingested row. Provides proof of data integrity.';
COMMENT ON COLUMN ops.ingest_audit_log.stage IS 'Current lifecycle stage: received, parsed, validated, stored, failed';
COMMENT ON COLUMN ops.ingest_audit_log.raw_checksum IS 'Checksum of raw input data for tamper detection';
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_audit_log_batch_id ON ops.ingest_audit_log(batch_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_stage ON ops.ingest_audit_log(stage);
CREATE INDEX IF NOT EXISTS idx_audit_log_stage_created ON ops.ingest_audit_log(stage, created_at DESC)
WHERE stage = 'failed';
CREATE INDEX IF NOT EXISTS idx_audit_log_case_number ON ops.ingest_audit_log(case_number)
WHERE case_number IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_log_judgment_id ON ops.ingest_audit_log(judgment_id)
WHERE judgment_id IS NOT NULL;
-- ============================================================================
-- 2. Data Discrepancies - Dead Letter Queue
-- ============================================================================
-- Stores rows that failed validation with exact error details.
-- Supports manual inspection, editing, and retry.
CREATE TABLE IF NOT EXISTS ops.data_discrepancies (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Source tracking
    batch_id uuid NOT NULL REFERENCES ops.ingest_batches(id) ON DELETE CASCADE,
    row_index integer NOT NULL,
    source_file text,
    -- Original data (for editing and retry)
    raw_data jsonb NOT NULL,
    -- Error details
    error_type text NOT NULL CHECK (
        error_type IN (
            'parse_error',
            -- CSV parsing failed
            'validation_error',
            -- Required field missing or invalid
            'transform_error',
            -- Data transformation failed
            'db_error',
            -- Database insert/update failed
            'duplicate',
            -- Row already exists
            'constraint_error',
            -- DB constraint violation
            'unknown' -- Unexpected error
        )
    ),
    error_code text,
    error_message text NOT NULL,
    error_details jsonb,
    -- Stack trace, field-level errors, etc.
    -- Resolution tracking
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            -- Awaiting review
            'reviewing',
            -- User is editing
            'retrying',
            -- Retry in progress
            'resolved',
            -- Successfully reprocessed
            'dismissed' -- Marked as not fixable
        )
    ),
    -- Resolution metadata
    resolved_at timestamptz,
    resolved_by text,
    resolution_notes text,
    retry_count integer NOT NULL DEFAULT 0,
    last_retry_at timestamptz,
    -- For successful retries, link to created judgment
    resolved_judgment_id uuid,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- Each discrepancy is unique per batch/row
    CONSTRAINT uq_discrepancy_batch_row UNIQUE (batch_id, row_index)
);
COMMENT ON TABLE ops.data_discrepancies IS 'Dead Letter Queue for failed rows. Supports inspection, editing, and retry.';
COMMENT ON COLUMN ops.data_discrepancies.raw_data IS 'Original row data as JSONB. Can be edited before retry.';
COMMENT ON COLUMN ops.data_discrepancies.status IS 'Resolution status: pending, reviewing, retrying, resolved, dismissed';
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_discrepancies_batch_id ON ops.data_discrepancies(batch_id);
CREATE INDEX IF NOT EXISTS idx_discrepancies_status ON ops.data_discrepancies(status)
WHERE status IN ('pending', 'reviewing');
CREATE INDEX IF NOT EXISTS idx_discrepancies_error_type ON ops.data_discrepancies(error_type);
CREATE INDEX IF NOT EXISTS idx_discrepancies_created ON ops.data_discrepancies(created_at DESC);
-- Trigger for updated_at
CREATE OR REPLACE FUNCTION ops.touch_discrepancy_updated_at() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_discrepancy_updated_at ON ops.data_discrepancies;
CREATE TRIGGER trg_discrepancy_updated_at BEFORE
UPDATE ON ops.data_discrepancies FOR EACH ROW EXECUTE FUNCTION ops.touch_discrepancy_updated_at();
-- ============================================================================
-- 3. Integrity Dashboard View
-- ============================================================================
-- Real-time metrics for the Vault Status dashboard
CREATE OR REPLACE VIEW ops.v_integrity_dashboard AS WITH -- All-time ingestion stats
    all_time_stats AS (
        SELECT COALESCE(SUM(row_count_raw), 0) AS total_rows_received,
            COALESCE(SUM(row_count_valid), 0) AS total_rows_stored,
            COALESCE(SUM(row_count_invalid), 0) AS total_rows_failed,
            COUNT(*) AS total_batches
        FROM ops.ingest_batches
    ),
    -- Discrepancy stats
    discrepancy_stats AS (
        SELECT COUNT(*) AS total_discrepancies,
            COUNT(*) FILTER (
                WHERE status = 'pending'
            ) AS pending_discrepancies,
            COUNT(*) FILTER (
                WHERE status = 'resolved'
            ) AS resolved_discrepancies,
            COUNT(*) FILTER (
                WHERE status = 'dismissed'
            ) AS dismissed_discrepancies
        FROM ops.data_discrepancies
    ),
    -- Recent activity (last 24 hours)
    recent_stats AS (
        SELECT COALESCE(SUM(row_count_raw), 0) AS rows_24h,
            COALESCE(SUM(row_count_valid), 0) AS valid_24h,
            COALESCE(SUM(row_count_invalid), 0) AS failed_24h
        FROM ops.ingest_batches
        WHERE created_at >= now() - interval '24 hours'
    ),
    -- Batch status breakdown
    batch_status AS (
        SELECT COUNT(*) FILTER (
                WHERE status = 'pending'
            ) AS batches_pending,
            COUNT(*) FILTER (
                WHERE status = 'processing'
            ) AS batches_processing,
            COUNT(*) FILTER (
                WHERE status = 'completed'
            ) AS batches_completed,
            COUNT(*) FILTER (
                WHERE status = 'failed'
            ) AS batches_failed
        FROM ops.ingest_batches
    )
SELECT -- All-time metrics
    a.total_rows_received,
    a.total_rows_stored,
    a.total_rows_failed,
    a.total_batches,
    -- Integrity score (percentage of successful rows)
    CASE
        WHEN a.total_rows_received > 0 THEN ROUND(
            (
                a.total_rows_stored::numeric / a.total_rows_received
            ) * 100,
            3
        )
        ELSE 100.000
    END AS integrity_score,
    -- Discrepancy metrics
    d.total_discrepancies,
    d.pending_discrepancies,
    d.resolved_discrepancies,
    d.dismissed_discrepancies,
    -- Recent activity
    r.rows_24h AS rows_received_24h,
    r.valid_24h AS rows_stored_24h,
    r.failed_24h AS rows_failed_24h,
    -- Batch pipeline status
    b.batches_pending,
    b.batches_processing,
    b.batches_completed,
    b.batches_failed,
    -- Computed at timestamp
    now() AS computed_at
FROM all_time_stats a
    CROSS JOIN discrepancy_stats d
    CROSS JOIN recent_stats r
    CROSS JOIN batch_status b;
COMMENT ON VIEW ops.v_integrity_dashboard IS 'Real-time data integrity metrics for the Vault Status dashboard';
-- ============================================================================
-- 4. RLS Policies
-- ============================================================================
-- Enable RLS
ALTER TABLE ops.ingest_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.data_discrepancies ENABLE ROW LEVEL SECURITY;
-- Service role full access
DROP POLICY IF EXISTS "service_role_audit_log" ON ops.ingest_audit_log;
CREATE POLICY "service_role_audit_log" ON ops.ingest_audit_log FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "service_role_discrepancies" ON ops.data_discrepancies;
CREATE POLICY "service_role_discrepancies" ON ops.data_discrepancies FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated read access
DROP POLICY IF EXISTS "authenticated_read_audit_log" ON ops.ingest_audit_log;
CREATE POLICY "authenticated_read_audit_log" ON ops.ingest_audit_log FOR
SELECT TO authenticated USING (true);
DROP POLICY IF EXISTS "authenticated_read_discrepancies" ON ops.data_discrepancies;
CREATE POLICY "authenticated_read_discrepancies" ON ops.data_discrepancies FOR
SELECT TO authenticated USING (true);
-- Authenticated can update discrepancies (for editing/retry)
DROP POLICY IF EXISTS "authenticated_update_discrepancies" ON ops.data_discrepancies;
CREATE POLICY "authenticated_update_discrepancies" ON ops.data_discrepancies FOR
UPDATE TO authenticated USING (true) WITH CHECK (true);
-- ============================================================================
-- 5. Grants
-- ============================================================================
GRANT SELECT,
    INSERT,
    UPDATE ON ops.ingest_audit_log TO service_role;
GRANT SELECT ON ops.ingest_audit_log TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ops.data_discrepancies TO service_role;
GRANT SELECT,
    UPDATE ON ops.data_discrepancies TO authenticated;
GRANT SELECT ON ops.v_integrity_dashboard TO service_role,
    authenticated;