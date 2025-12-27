-- ===========================================================================
-- Migration: Ingest North Star - Canonical Idempotency Architecture
-- ===========================================================================
-- The "North Star" rules for 100% reliable, idempotent ingestion:
--
-- 1. BATCH IDEMPOTENCY: Same file hash = same batch (no duplicates)
-- 2. ROW IDEMPOTENCY: Same (batch_id, row_index) = same row
-- 3. JOB IDEMPOTENCY: Same (job_type, dedup_key) = same job (for active jobs)
-- 4. TRACEABILITY: Every action logged to ops.ingest_event_log
--
-- Architecture:
--   - Vercel (UI): Read-Only via authenticated role
--   - Railway (API/Worker): Sole Writer via service_role
-- ===========================================================================
-- ===========================================================================
-- 1. BATCH IDEMPOTENCY: intake.simplicity_batches
-- ===========================================================================
-- Ensure file_hash column exists
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS file_hash TEXT;
-- Unique constraint on file_hash (allows NULLs for legacy batches)
CREATE UNIQUE INDEX IF NOT EXISTS idx_batches_file_hash ON intake.simplicity_batches(file_hash)
WHERE file_hash IS NOT NULL;
COMMENT ON COLUMN intake.simplicity_batches.file_hash IS 'SHA-256 hash of source file. Enforces batch idempotency.';
-- ===========================================================================
-- 2. ROW IDEMPOTENCY: intake.simplicity_raw_rows
-- ===========================================================================
-- Unique constraint on (batch_id, row_index)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'intake'
        AND indexname = 'idx_raw_rows_batch_row'
) THEN CREATE UNIQUE INDEX idx_raw_rows_batch_row ON intake.simplicity_raw_rows(batch_id, row_index);
END IF;
END $$;
-- ===========================================================================
-- 3. JOB IDEMPOTENCY: ops.job_queue
-- ===========================================================================
-- Ensure dedup_key column exists
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS dedup_key TEXT;
-- CRITICAL: Partial unique index that EXCLUDES completed/failed jobs
-- This allows re-submission of failed jobs while preventing double-queuing active ones
DROP INDEX IF EXISTS ops.idx_job_dedup;
CREATE UNIQUE INDEX idx_job_dedup ON ops.job_queue(job_type, dedup_key)
WHERE dedup_key IS NOT NULL
    AND status IN ('pending', 'processing');
COMMENT ON COLUMN ops.job_queue.dedup_key IS 'Deduplication key. Format: {stage}-{batch_id}-{row_index}';
COMMENT ON INDEX ops.idx_job_dedup IS 'Prevents double-queuing active jobs. Allows retry of failed/completed jobs.';
-- ===========================================================================
-- 4. TRACEABILITY: ops.ingest_event_log (canonical audit log)
-- ===========================================================================
-- Note: ops.ingest_audit_log exists with a different schema (row-level tracking)
-- We use ops.ingest_event_log for event-level traceability
-- Indexes for common queries (columns already exist)
CREATE INDEX IF NOT EXISTS idx_event_log_batch_id ON ops.ingest_event_log(batch_id);
CREATE INDEX IF NOT EXISTS idx_event_log_correlation_id ON ops.ingest_event_log(correlation_id);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON ops.ingest_event_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_stage_event ON ops.ingest_event_log(stage, event);
-- RLS: service_role only (if not already set)
ALTER TABLE ops.ingest_event_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.ingest_event_log FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS service_event_log_all ON ops.ingest_event_log;
CREATE POLICY service_event_log_all ON ops.ingest_event_log FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Grants
GRANT ALL ON ops.ingest_event_log TO service_role;
GRANT SELECT ON ops.ingest_event_log TO authenticated;
COMMENT ON TABLE ops.ingest_event_log IS 'Canonical audit trail for all ingest operations. Every action is logged.';
-- ===========================================================================
-- 5. Traceability View: ops.v_ingest_timeline
-- ===========================================================================
CREATE OR REPLACE VIEW ops.v_ingest_timeline AS
SELECT iel.id,
    iel.batch_id,
    iel.correlation_id,
    iel.stage,
    iel.event,
    iel.metadata,
    iel.created_at,
    sb.filename,
    sb.status AS batch_status,
    -- Timeline ordering
    ROW_NUMBER() OVER (
        PARTITION BY iel.batch_id
        ORDER BY iel.created_at
    ) AS step_number
FROM ops.ingest_event_log iel
    LEFT JOIN intake.simplicity_batches sb ON iel.batch_id = sb.id
ORDER BY iel.created_at DESC;
GRANT SELECT ON ops.v_ingest_timeline TO service_role;
GRANT SELECT ON ops.v_ingest_timeline TO authenticated;
COMMENT ON VIEW ops.v_ingest_timeline IS 'Timeline view of all ingest operations for a batch';
-- ===========================================================================
-- Done: North Star Idempotency Architecture Complete
-- ===========================================================================