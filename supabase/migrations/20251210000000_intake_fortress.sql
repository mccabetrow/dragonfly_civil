-- ===========================================================================
-- Migration: Intake Fortress
-- ===========================================================================
-- The hardened intake system for the 900-plaintiff asset.
-- Self-contained: Creates base tables if missing, then adds enhancements.
--
-- Components:
--   1. ops schema and base ingest_batches table
--   2. ops.intake_source_type - Enum for source systems
--   3. ops.intake_batches - Enhanced batch tracking
--   4. ops.intake_logs - Row-level processing logs
--   5. ops.v_intake_monitor - Real-time monitoring view
--   6. RLS Policies - service_role writes, authenticated reads
-- ===========================================================================
-- Ensure schema exists
CREATE SCHEMA IF NOT EXISTS ops;
-- ===========================================================================
-- 1A. BASE: Create ops.ingest_batches if not exists (from 20251203150000)
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ops.ingest_batches (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL,
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
    created_by TEXT
);
-- Create base indexes if they don't exist
CREATE INDEX IF NOT EXISTS idx_ingest_batches_status ON ops.ingest_batches(status)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_ingest_batches_created_at ON ops.ingest_batches(created_at DESC);
-- ===========================================================================
-- 1B. Source Type Enum
-- ===========================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'intake_source_type'
) THEN CREATE TYPE ops.intake_source_type AS ENUM (
    'simplicity',
    'jbi',
    'manual',
    'csv_upload',
    'api'
);
END IF;
END $$;
-- ===========================================================================
-- 2. Enhanced Intake Batches (adds columns if missing)
-- ===========================================================================
-- Add stats column if not exists
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS stats JSONB DEFAULT '{}';
COMMENT ON COLUMN ops.ingest_batches.stats IS 'Extended statistics: {"total": N, "valid": N, "error": N, "warnings": [], "timing_ms": N}';
-- Add processing metadata columns
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS worker_id TEXT;
COMMENT ON COLUMN ops.ingest_batches.worker_id IS 'ID of the worker process handling this batch';
-- ===========================================================================
-- 3. Intake Logs - Row-level processing audit trail
-- ===========================================================================
-- NOTE: judgment_id FK to public.judgments is intentionally omitted.
-- The FK will be added by a later migration once the judgments table exists.
-- This allows intake_fortress to bootstrap an empty PROD database.
CREATE TABLE IF NOT EXISTS ops.intake_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES ops.ingest_batches(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('success', 'error', 'skipped', 'duplicate')
    ),
    judgment_id UUID,
    -- FK added later once public.judgments exists
    error_code TEXT,
    error_details TEXT,
    processing_time_ms INTEGER,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Prevent duplicate log entries per batch/row
    CONSTRAINT uq_intake_log_batch_row UNIQUE (batch_id, row_index)
);
COMMENT ON TABLE ops.intake_logs IS 'Row-level audit log for intake processing. Every row processed gets an entry.';
COMMENT ON COLUMN ops.intake_logs.status IS 'Processing result: success, error, skipped (validation), duplicate (already exists)';
COMMENT ON COLUMN ops.intake_logs.error_code IS 'Machine-readable error code: PARSE_ERROR, VALIDATION_ERROR, DB_ERROR, DUPLICATE, etc.';
COMMENT ON COLUMN ops.intake_logs.error_details IS 'Human-readable error message with context';
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_intake_logs_batch_id ON ops.intake_logs(batch_id);
CREATE INDEX IF NOT EXISTS idx_intake_logs_batch_status ON ops.intake_logs(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_intake_logs_status_created ON ops.intake_logs(status, created_at DESC)
WHERE status = 'error';
CREATE INDEX IF NOT EXISTS idx_intake_logs_judgment_id ON ops.intake_logs(judgment_id)
WHERE judgment_id IS NOT NULL;
-- ===========================================================================
-- 4. Intake Monitor View - Dashboard-ready metrics
-- ===========================================================================
CREATE OR REPLACE VIEW ops.v_intake_monitor AS WITH batch_stats AS (
        SELECT b.id,
            b.filename,
            b.source,
            b.status,
            b.row_count_raw AS total_rows,
            b.row_count_valid AS valid_rows,
            b.row_count_invalid AS error_rows,
            b.stats,
            b.created_at,
            b.started_at,
            b.completed_at,
            b.created_by,
            b.worker_id,
            -- Calculate success rate
            CASE
                WHEN b.row_count_raw > 0 THEN ROUND(
                    (b.row_count_valid::NUMERIC / b.row_count_raw) * 100,
                    1
                )
                ELSE 0
            END AS success_rate,
            -- Calculate processing duration
            CASE
                WHEN b.completed_at IS NOT NULL
                AND b.started_at IS NOT NULL THEN EXTRACT(
                    EPOCH
                    FROM (b.completed_at - b.started_at)
                )::INTEGER
                ELSE NULL
            END AS duration_seconds
        FROM ops.ingest_batches b
    ),
    error_preview AS (
        SELECT batch_id,
            jsonb_agg(
                jsonb_build_object(
                    'row',
                    row_index,
                    'code',
                    error_code,
                    'message',
                    LEFT(error_details, 100)
                )
                ORDER BY row_index
            ) FILTER (
                WHERE status = 'error'
            ) AS recent_errors
        FROM (
                SELECT batch_id,
                    row_index,
                    error_code,
                    error_details,
                    status
                FROM ops.intake_logs
                WHERE status = 'error'
                ORDER BY created_at DESC
                LIMIT 5
            ) sub
        GROUP BY batch_id
    )
SELECT bs.id,
    bs.filename,
    bs.source,
    bs.status,
    bs.total_rows,
    bs.valid_rows,
    bs.error_rows,
    bs.success_rate,
    bs.duration_seconds,
    bs.created_at,
    bs.started_at,
    bs.completed_at,
    bs.created_by,
    bs.worker_id,
    bs.stats,
    COALESCE(ep.recent_errors, '[]'::jsonb) AS recent_errors,
    -- Health indicator
    CASE
        WHEN bs.status = 'failed' THEN 'critical'
        WHEN bs.error_rows > 0
        AND bs.success_rate < 90 THEN 'warning'
        WHEN bs.status = 'completed' THEN 'healthy'
        WHEN bs.status = 'processing' THEN 'running'
        ELSE 'pending'
    END AS health_status
FROM batch_stats bs
    LEFT JOIN error_preview ep ON bs.id = ep.batch_id
ORDER BY bs.created_at DESC;
COMMENT ON VIEW ops.v_intake_monitor IS 'Real-time intake monitoring dashboard. Shows batch status, success rates, and error previews.';
-- ===========================================================================
-- 5. RLS Policies - Secure access control
-- ===========================================================================
-- Enable RLS on new table
ALTER TABLE ops.intake_logs ENABLE ROW LEVEL SECURITY;
-- Service role has full access (for backend workers)
CREATE POLICY "service_role_full_access_intake_logs" ON ops.intake_logs FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated users can read logs
CREATE POLICY "authenticated_read_intake_logs" ON ops.intake_logs FOR
SELECT TO authenticated USING (true);
-- Enable RLS on ingest_batches if not already
ALTER TABLE ops.ingest_batches ENABLE ROW LEVEL SECURITY;
-- Drop existing policies to recreate
DROP POLICY IF EXISTS "service_role_full_access_ingest_batches" ON ops.ingest_batches;
DROP POLICY IF EXISTS "authenticated_read_ingest_batches" ON ops.ingest_batches;
-- Service role has full access
CREATE POLICY "service_role_full_access_ingest_batches" ON ops.ingest_batches FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated users can read batches
CREATE POLICY "authenticated_read_ingest_batches" ON ops.ingest_batches FOR
SELECT TO authenticated USING (true);
-- ===========================================================================
-- 6. Grants
-- ===========================================================================
-- Grants for service_role (backend workers)
GRANT ALL ON ops.intake_logs TO service_role;
GRANT SELECT ON ops.v_intake_monitor TO service_role;
-- Grants for authenticated (dashboard users)
GRANT SELECT ON ops.intake_logs TO authenticated;
GRANT SELECT ON ops.v_intake_monitor TO authenticated;
GRANT SELECT ON ops.ingest_batches TO authenticated;
-- ===========================================================================
-- 7. Helper Functions
-- ===========================================================================
-- Function to create a new batch with proper initialization
CREATE OR REPLACE FUNCTION ops.create_intake_batch(
        p_filename TEXT,
        p_source TEXT DEFAULT 'simplicity',
        p_created_by TEXT DEFAULT NULL
    ) RETURNS UUID AS $$
DECLARE v_batch_id UUID;
BEGIN
INSERT INTO ops.ingest_batches (
        filename,
        source,
        status,
        created_by,
        stats
    )
VALUES (
        p_filename,
        p_source,
        'pending',
        p_created_by,
        jsonb_build_object('total', 0, 'valid', 0, 'error', 0)
    )
RETURNING id INTO v_batch_id;
RETURN v_batch_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
COMMENT ON FUNCTION ops.create_intake_batch IS 'Creates a new intake batch with proper initialization. Returns batch ID.';
-- Function to finalize a batch with computed stats
CREATE OR REPLACE FUNCTION ops.finalize_intake_batch(
        p_batch_id UUID,
        p_status TEXT DEFAULT 'completed'
    ) RETURNS VOID AS $$
DECLARE v_stats RECORD;
BEGIN -- Compute stats from intake_logs
SELECT COUNT(*) AS total,
    COUNT(*) FILTER (
        WHERE status = 'success'
    ) AS valid,
    COUNT(*) FILTER (
        WHERE status = 'error'
    ) AS errors,
    COUNT(*) FILTER (
        WHERE status = 'duplicate'
    ) AS duplicates,
    COUNT(*) FILTER (
        WHERE status = 'skipped'
    ) AS skipped INTO v_stats
FROM ops.intake_logs
WHERE batch_id = p_batch_id;
-- Update the batch
UPDATE ops.ingest_batches
SET status = p_status,
    row_count_raw = v_stats.total,
    row_count_valid = v_stats.valid,
    row_count_invalid = v_stats.errors,
    completed_at = now(),
    stats = jsonb_build_object(
        'total',
        v_stats.total,
        'valid',
        v_stats.valid,
        'error',
        v_stats.errors,
        'duplicates',
        v_stats.duplicates,
        'skipped',
        v_stats.skipped
    )
WHERE id = p_batch_id;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;
COMMENT ON FUNCTION ops.finalize_intake_batch IS 'Computes final stats from intake_logs and updates batch status.';
-- Grant execute on functions
GRANT EXECUTE ON FUNCTION ops.create_intake_batch TO service_role;
GRANT EXECUTE ON FUNCTION ops.finalize_intake_batch TO service_role;
