-- ============================================================================
-- Migration: 20251226130000_ops_audit_logging.sql
-- Purpose: Ops-Grade Observability - Audit logging and traceability
-- ============================================================================
--
-- This migration adds:
-- 1. ops.ingest_event_log table for pipeline event tracing
-- 2. correlation_id on ops.job_queue for end-to-end traceability
-- 3. Index improvements for efficient audit queries
--
-- Note: Using ingest_event_log (not ingest_audit_log) to avoid collision
-- with existing ops.ingest_audit_log which has different schema.
-- ============================================================================
-- ============================================================================
-- 1. Create ops.ingest_event_log table
-- Central event log for all intake pipeline events
-- ============================================================================
CREATE TABLE IF NOT EXISTS ops.ingest_event_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL,
    correlation_id UUID,
    stage TEXT NOT NULL,
    event TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.ingest_event_log IS 'Event log for intake pipeline - enables traceability and debugging';
COMMENT ON COLUMN ops.ingest_event_log.batch_id IS 'The batch this event belongs to';
COMMENT ON COLUMN ops.ingest_event_log.correlation_id IS 'Correlation ID for tracing across pipeline stages';
COMMENT ON COLUMN ops.ingest_event_log.stage IS 'Pipeline stage: upload, parse, validate, transform, enrich, complete';
COMMENT ON COLUMN ops.ingest_event_log.event IS 'Event type: started, completed, failed, retried, skipped';
COMMENT ON COLUMN ops.ingest_event_log.metadata IS 'Additional event context (row counts, error details, timing)';
-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_ingest_event_log_batch_id ON ops.ingest_event_log(batch_id);
CREATE INDEX IF NOT EXISTS idx_ingest_event_log_created_at ON ops.ingest_event_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ingest_event_log_correlation ON ops.ingest_event_log(correlation_id)
WHERE correlation_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_ingest_event_log_batch_stage ON ops.ingest_event_log(batch_id, stage, created_at DESC);
-- ============================================================================
-- 2. Add correlation_id to ops.job_queue
-- Enables tracing jobs back to their originating batch/row
-- ============================================================================
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS correlation_id UUID;
COMMENT ON COLUMN ops.job_queue.correlation_id IS 'UUID for correlating job to originating batch/row for traceability';
-- Index for correlation lookups
CREATE INDEX IF NOT EXISTS idx_job_queue_correlation ON ops.job_queue(correlation_id)
WHERE correlation_id IS NOT NULL;
-- ============================================================================
-- 3. RLS and Permissions
-- ============================================================================
-- Enable RLS on event log (restrict to service_role)
ALTER TABLE ops.ingest_event_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.ingest_event_log FORCE ROW LEVEL SECURITY;
-- Allow service_role full access
DROP POLICY IF EXISTS ingest_event_log_service_role ON ops.ingest_event_log;
CREATE POLICY ingest_event_log_service_role ON ops.ingest_event_log FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Grant permissions
GRANT ALL ON ops.ingest_event_log TO service_role;
-- ============================================================================
-- 4. Helper view: v_event_log_recent (last 24h of events)
-- ============================================================================
CREATE OR REPLACE VIEW ops.v_event_log_recent AS
SELECT l.id,
    l.batch_id,
    b.filename AS batch_filename,
    l.correlation_id,
    l.stage,
    l.event,
    l.metadata,
    l.created_at
FROM ops.ingest_event_log l
    LEFT JOIN intake.simplicity_batches b ON b.id = l.batch_id
WHERE l.created_at > NOW() - INTERVAL '24 hours'
ORDER BY l.created_at DESC;
COMMENT ON VIEW ops.v_event_log_recent IS 'Recent event log entries (last 24h) with batch metadata';
-- Grant access to view
GRANT SELECT ON ops.v_event_log_recent TO service_role;
-- ============================================================================
-- 5. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';
