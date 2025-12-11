-- ============================================================================
-- Migration: Entity Audit Log & Batch Verification
-- Created: 2025-12-25
-- Purpose: Add entity-level audit logging and batch verification functions
-- ============================================================================
--
-- This migration adds:
--   1. ops.audit_log - Entity-level change tracking (INSERT/UPDATE/DELETE)
--   2. ops.check_batch_integrity() - SQL function for batch verification
--   3. integrity_status column on ops.ingest_batches
--   4. ops.v_batch_integrity - View for batch verification dashboard
--
-- Business Goal: Mathematical guarantee that no data is lost during ingestion.
-- Every judgment insertion/update is logged, and batches can be verified.
--
-- ============================================================================
-- ============================================================================
-- 1. Entity-Level Audit Log
-- ============================================================================
-- Tracks all changes to key entities (judgments, plaintiffs, etc.)
-- This is different from ingest_audit_log which tracks row lifecycle.
CREATE TABLE IF NOT EXISTS ops.audit_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Entity reference
    entity_id TEXT NOT NULL,
    -- UUID or ID of the entity
    table_name TEXT NOT NULL,
    -- e.g., 'public.judgments', 'public.plaintiffs'
    -- Change details
    action TEXT NOT NULL CHECK (action IN ('INSERT', 'UPDATE', 'DELETE')),
    old_values JSONB,
    -- Previous state (NULL for INSERT)
    new_values JSONB,
    -- New state (NULL for DELETE)
    changed_fields TEXT [],
    -- List of fields that changed (for UPDATE)
    -- Context
    worker_id TEXT,
    -- Which worker/process made the change
    batch_id UUID,
    -- Associated batch (if from ingestion)
    source_file TEXT,
    -- Source file (if applicable)
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT -- User or service account
);
COMMENT ON TABLE ops.audit_log IS 'Entity-level audit log tracking all INSERT/UPDATE/DELETE operations on key tables';
COMMENT ON COLUMN ops.audit_log.entity_id IS 'Primary key of the affected entity (as text for flexibility)';
COMMENT ON COLUMN ops.audit_log.old_values IS 'Complete entity state before change (NULL for INSERT)';
COMMENT ON COLUMN ops.audit_log.new_values IS 'Complete entity state after change (NULL for DELETE)';
COMMENT ON COLUMN ops.audit_log.changed_fields IS 'Array of field names that changed (for UPDATE operations)';
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON ops.audit_log(table_name, entity_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_batch ON ops.audit_log(batch_id)
WHERE batch_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_audit_log_created ON ops.audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_action ON ops.audit_log(action, created_at DESC);
-- ============================================================================
-- 2. Add Integrity Status to Batches
-- ============================================================================
-- Track verification status for each batch
DO $$ BEGIN -- Add integrity_status column if it doesn't exist
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'ingest_batches'
        AND column_name = 'integrity_status'
) THEN
ALTER TABLE ops.ingest_batches
ADD COLUMN integrity_status TEXT CHECK (
        integrity_status IN ('pending', 'verified', 'discrepancy', 'skipped')
    );
END IF;
-- Add verified_at timestamp
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'ingest_batches'
        AND column_name = 'verified_at'
) THEN
ALTER TABLE ops.ingest_batches
ADD COLUMN verified_at TIMESTAMPTZ;
END IF;
-- Add verification_notes
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'ingest_batches'
        AND column_name = 'verification_notes'
) THEN
ALTER TABLE ops.ingest_batches
ADD COLUMN verification_notes TEXT;
END IF;
END $$;
-- Set default for existing rows
UPDATE ops.ingest_batches
SET integrity_status = 'pending'
WHERE integrity_status IS NULL;
-- ============================================================================
-- 3. Batch Integrity Check Function
-- ============================================================================
-- Core function for verifying batch data integrity
CREATE OR REPLACE FUNCTION ops.check_batch_integrity(p_batch_id UUID) RETURNS TABLE (
        batch_id UUID,
        csv_row_count INTEGER,
        db_row_count INTEGER,
        audit_log_count INTEGER,
        discrepancy_count INTEGER,
        integrity_score NUMERIC(6, 3),
        status TEXT,
        is_verified BOOLEAN,
        verification_message TEXT
    ) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_csv_count INTEGER;
v_db_count INTEGER;
v_audit_count INTEGER;
v_discrepancy_count INTEGER;
v_score NUMERIC(6, 3);
v_status TEXT;
v_is_verified BOOLEAN;
v_message TEXT;
BEGIN -- Get CSV row count from batch metadata
SELECT COALESCE(b.row_count_raw, 0) INTO v_csv_count
FROM ops.ingest_batches b
WHERE b.id = p_batch_id;
IF v_csv_count IS NULL THEN RAISE EXCEPTION 'Batch % not found',
p_batch_id;
END IF;
-- Count rows in public.judgments for this batch
SELECT COUNT(*) INTO v_db_count
FROM public.judgments j
WHERE j.source_file = 'batch:' || p_batch_id::text
    OR j.source_file = 'simplicity-batch:' || p_batch_id::text
    OR j.source_file = 'foil-batch:' || p_batch_id::text;
-- Count audit log entries for this batch (INSERT operations)
SELECT COUNT(*) INTO v_audit_count
FROM ops.audit_log a
WHERE a.batch_id = p_batch_id
    AND a.action = 'INSERT';
-- Count discrepancies (failed rows)
SELECT COUNT(*) INTO v_discrepancy_count
FROM ops.data_discrepancies d
WHERE d.batch_id = p_batch_id
    AND d.status = 'pending';
-- Calculate integrity score
IF v_csv_count > 0 THEN v_score := ROUND((v_db_count::NUMERIC / v_csv_count) * 100, 3);
ELSE v_score := 100.000;
END IF;
-- Determine verification status
IF v_csv_count = v_db_count
AND v_discrepancy_count = 0 THEN v_status := 'verified';
v_is_verified := TRUE;
v_message := format(
    'Perfect match: %s rows CSV = %s rows DB',
    v_csv_count,
    v_db_count
);
ELSIF v_csv_count = v_db_count + v_discrepancy_count THEN v_status := 'verified';
v_is_verified := TRUE;
v_message := format(
    'Accounted: %s CSV = %s stored + %s discrepancies',
    v_csv_count,
    v_db_count,
    v_discrepancy_count
);
ELSE v_status := 'discrepancy';
v_is_verified := FALSE;
v_message := format(
    'MISMATCH: %s CSV != %s stored + %s discrepancies (gap=%s)',
    v_csv_count,
    v_db_count,
    v_discrepancy_count,
    v_csv_count - v_db_count - v_discrepancy_count
);
END IF;
-- Update batch with verification results
UPDATE ops.ingest_batches
SET integrity_status = v_status,
    verified_at = now(),
    verification_notes = v_message
WHERE id = p_batch_id;
-- Return results
RETURN QUERY
SELECT p_batch_id,
    v_csv_count,
    v_db_count,
    v_audit_count,
    v_discrepancy_count,
    v_score,
    v_status,
    v_is_verified,
    v_message;
END;
$$;
COMMENT ON FUNCTION ops.check_batch_integrity IS 'Verify batch data integrity by comparing CSV row count vs DB row count. Updates batch status.';
-- ============================================================================
-- 4. Batch Integrity Dashboard View
-- ============================================================================
CREATE OR REPLACE VIEW ops.v_batch_integrity AS
SELECT b.id AS batch_id,
    b.source,
    b.filename,
    b.row_count_raw AS csv_row_count,
    b.row_count_valid AS valid_row_count,
    b.row_count_invalid AS invalid_row_count,
    b.status AS batch_status,
    b.integrity_status,
    b.verified_at,
    b.verification_notes,
    -- Count actual rows in judgments
    (
        SELECT COUNT(*)
        FROM public.judgments j
        WHERE j.source_file = 'batch:' || b.id::text
            OR j.source_file = 'simplicity-batch:' || b.id::text
            OR j.source_file = 'foil-batch:' || b.id::text
    ) AS db_row_count,
    -- Count audit log entries
    (
        SELECT COUNT(*)
        FROM ops.audit_log a
        WHERE a.batch_id = b.id
            AND a.action = 'INSERT'
    ) AS audit_entries,
    -- Count pending discrepancies
    (
        SELECT COUNT(*)
        FROM ops.data_discrepancies d
        WHERE d.batch_id = b.id
            AND d.status = 'pending'
    ) AS pending_discrepancies,
    -- Integrity score
    CASE
        WHEN b.row_count_raw > 0 THEN ROUND(
            (b.row_count_valid::NUMERIC / b.row_count_raw) * 100,
            3
        )
        ELSE 100.000
    END AS integrity_score,
    -- Visual status
    CASE
        WHEN b.integrity_status = 'verified' THEN 'GREEN'
        WHEN b.integrity_status = 'discrepancy' THEN 'RED'
        WHEN b.integrity_status = 'pending' THEN 'YELLOW'
        ELSE 'GRAY'
    END AS status_color,
    b.created_at,
    b.processed_at
FROM ops.ingest_batches b
ORDER BY b.created_at DESC;
COMMENT ON VIEW ops.v_batch_integrity IS 'Dashboard view showing batch integrity status with color coding (Green=Verified, Red=Discrepancy)';
-- ============================================================================
-- 5. RLS Policies
-- ============================================================================
ALTER TABLE ops.audit_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_audit_log_all" ON ops.audit_log;
CREATE POLICY "service_role_audit_log_all" ON ops.audit_log FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "authenticated_read_audit_log" ON ops.audit_log;
CREATE POLICY "authenticated_read_audit_log" ON ops.audit_log FOR
SELECT TO authenticated USING (true);
-- ============================================================================
-- 6. Grants
-- ============================================================================
GRANT SELECT,
    INSERT ON ops.audit_log TO service_role;
GRANT SELECT ON ops.audit_log TO authenticated;
GRANT SELECT ON ops.v_batch_integrity TO service_role,
    authenticated;
GRANT EXECUTE ON FUNCTION ops.check_batch_integrity TO service_role;
-- ============================================================================
-- 7. Notify PostgREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';