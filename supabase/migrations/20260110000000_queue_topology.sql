-- ============================================================================
-- Migration: Queue Topology (pgmq)
-- Purpose: Postgres-based worker queue system with idempotency and DLQ
-- Date: 2026-01-10
-- ============================================================================
-- ============================================================================
-- PART 1: Enable pgmq Extension
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pgmq;
-- ============================================================================
-- PART 2: Workers Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS workers;
COMMENT ON SCHEMA workers IS 'Worker queue infrastructure and job tracking';
-- ============================================================================
-- PART 3: Queue Topology
-- Create 6 distinct queues for workload isolation
-- ============================================================================
-- q_ingest_raw: New CSVs/API payloads arriving for processing
SELECT pgmq.create('q_ingest_raw');
-- q_enrich_skiptrace: Data enhancement via skip trace services
SELECT pgmq.create('q_enrich_skiptrace');
-- q_score_collectability: Tier A/B/C calculation for prioritization
SELECT pgmq.create('q_score_collectability');
-- q_monitoring_recheck: Periodic status checks on active cases
SELECT pgmq.create('q_monitoring_recheck');
-- q_comms_outbound: Outbound communications (emails, letters, SMS)
SELECT pgmq.create('q_comms_outbound');
-- q_dead_letter: Failed jobs that exceeded retry limits
SELECT pgmq.create('q_dead_letter');
-- ============================================================================
-- PART 4: Job Status Enum
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
    WHERE t.typname = 'job_status'
        AND n.nspname = 'workers'
) THEN CREATE TYPE workers.job_status AS ENUM (
    'processing',
    'completed',
    'failed'
);
END IF;
END $$;
-- ============================================================================
-- PART 5: Idempotency Registry
-- Prevents double-processing of jobs across all queues
-- ============================================================================
CREATE TABLE IF NOT EXISTS workers.processed_jobs (
    idempotency_key TEXT PRIMARY KEY,
    job_id BIGINT NOT NULL,
    queue_name TEXT NOT NULL,
    status workers.job_status NOT NULL DEFAULT 'processing',
    result JSONB,
    processed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    worker_id UUID,
    -- Tracking metadata
    attempts INTEGER NOT NULL DEFAULT 1,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE workers.processed_jobs IS '{"description": "Idempotency registry for worker job deduplication", "sensitivity": "LOW"}';
COMMENT ON COLUMN workers.processed_jobs.idempotency_key IS 'Unique key derived from job payload (e.g., hash of case_id + action)';
COMMENT ON COLUMN workers.processed_jobs.job_id IS 'pgmq message ID';
COMMENT ON COLUMN workers.processed_jobs.queue_name IS 'Source queue name';
COMMENT ON COLUMN workers.processed_jobs.worker_id IS 'UUID of the worker instance that processed this job';
-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_processed_jobs_queue_name ON workers.processed_jobs(queue_name);
CREATE INDEX IF NOT EXISTS idx_processed_jobs_status ON workers.processed_jobs(status);
CREATE INDEX IF NOT EXISTS idx_processed_jobs_processed_at ON workers.processed_jobs(processed_at DESC);
CREATE INDEX IF NOT EXISTS idx_processed_jobs_worker_id ON workers.processed_jobs(worker_id)
WHERE worker_id IS NOT NULL;
-- ============================================================================
-- PART 6: Dead Letter Tracking
-- Extended metadata for failed jobs moved to DLQ
-- ============================================================================
CREATE TABLE IF NOT EXISTS workers.dead_letter_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    original_queue TEXT NOT NULL,
    original_job_id BIGINT NOT NULL,
    idempotency_key TEXT,
    payload JSONB NOT NULL,
    error_message TEXT NOT NULL,
    error_stack TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 1,
    first_attempt_at TIMESTAMPTZ NOT NULL,
    last_attempt_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    worker_id UUID,
    moved_to_dlq_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Resolution tracking
    resolved_at TIMESTAMPTZ,
    resolved_by UUID,
    resolution_notes TEXT
);
COMMENT ON TABLE workers.dead_letter_log IS '{"description": "Detailed log of jobs moved to dead letter queue", "sensitivity": "MEDIUM"}';
CREATE INDEX IF NOT EXISTS idx_dead_letter_original_queue ON workers.dead_letter_log(original_queue);
CREATE INDEX IF NOT EXISTS idx_dead_letter_moved_at ON workers.dead_letter_log(moved_to_dlq_at DESC);
CREATE INDEX IF NOT EXISTS idx_dead_letter_unresolved ON workers.dead_letter_log(original_queue, moved_to_dlq_at DESC)
WHERE resolved_at IS NULL;
-- ============================================================================
-- PART 7: Auto-Update Trigger for processed_jobs
-- ============================================================================
CREATE OR REPLACE FUNCTION workers.update_timestamp() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_processed_jobs_updated_at ON workers.processed_jobs;
CREATE TRIGGER trg_processed_jobs_updated_at BEFORE
UPDATE ON workers.processed_jobs FOR EACH ROW EXECUTE FUNCTION workers.update_timestamp();
-- ============================================================================
-- PART 8: Helper Functions
-- ============================================================================
-- Check if a job has already been processed (for idempotency)
CREATE OR REPLACE FUNCTION workers.is_job_processed(p_idempotency_key TEXT) RETURNS BOOLEAN LANGUAGE sql STABLE AS $$
SELECT EXISTS (
        SELECT 1
        FROM workers.processed_jobs
        WHERE idempotency_key = p_idempotency_key
            AND status = 'completed'
    );
$$;
-- Register a job as being processed (returns false if already registered)
CREATE OR REPLACE FUNCTION workers.claim_job(
        p_idempotency_key TEXT,
        p_job_id BIGINT,
        p_queue_name TEXT,
        p_worker_id UUID DEFAULT NULL
    ) RETURNS BOOLEAN LANGUAGE plpgsql AS $$ BEGIN
INSERT INTO workers.processed_jobs (
        idempotency_key,
        job_id,
        queue_name,
        worker_id,
        status
    )
VALUES (
        p_idempotency_key,
        p_job_id,
        p_queue_name,
        p_worker_id,
        'processing'
    ) ON CONFLICT (idempotency_key) DO NOTHING;
RETURN FOUND;
END;
$$;
-- Mark a job as completed
CREATE OR REPLACE FUNCTION workers.complete_job(
        p_idempotency_key TEXT,
        p_result JSONB DEFAULT NULL
    ) RETURNS VOID LANGUAGE sql AS $$
UPDATE workers.processed_jobs
SET status = 'completed',
    result = p_result,
    processed_at = now()
WHERE idempotency_key = p_idempotency_key;
$$;
-- Mark a job as failed
CREATE OR REPLACE FUNCTION workers.fail_job(
        p_idempotency_key TEXT,
        p_error TEXT
    ) RETURNS VOID LANGUAGE sql AS $$
UPDATE workers.processed_jobs
SET status = 'failed',
    last_error = p_error,
    attempts = attempts + 1
WHERE idempotency_key = p_idempotency_key;
$$;
-- Move a job to the dead letter queue
CREATE OR REPLACE FUNCTION workers.move_to_dlq(
        p_original_queue TEXT,
        p_original_job_id BIGINT,
        p_idempotency_key TEXT,
        p_payload JSONB,
        p_error_message TEXT,
        p_error_stack TEXT DEFAULT NULL,
        p_attempt_count INTEGER DEFAULT 1,
        p_first_attempt_at TIMESTAMPTZ DEFAULT now(),
        p_worker_id UUID DEFAULT NULL
    ) RETURNS UUID LANGUAGE plpgsql AS $$
DECLARE v_dlq_id UUID;
BEGIN -- Log to dead letter tracking table
INSERT INTO workers.dead_letter_log (
        original_queue,
        original_job_id,
        idempotency_key,
        payload,
        error_message,
        error_stack,
        attempt_count,
        first_attempt_at,
        worker_id
    )
VALUES (
        p_original_queue,
        p_original_job_id,
        p_idempotency_key,
        p_payload,
        p_error_message,
        p_error_stack,
        p_attempt_count,
        p_first_attempt_at,
        p_worker_id
    )
RETURNING id INTO v_dlq_id;
-- Enqueue to DLQ for potential reprocessing
PERFORM pgmq.send(
    'q_dead_letter',
    jsonb_build_object(
        'dlq_log_id',
        v_dlq_id,
        'original_queue',
        p_original_queue,
        'original_job_id',
        p_original_job_id,
        'idempotency_key',
        p_idempotency_key,
        'payload',
        p_payload,
        'error_message',
        p_error_message,
        'attempt_count',
        p_attempt_count
    )
);
RETURN v_dlq_id;
END;
$$;
-- ============================================================================
-- PART 9: Queue Statistics View
-- ============================================================================
CREATE OR REPLACE VIEW workers.v_queue_stats AS
SELECT queue_name,
    COUNT(*) FILTER (
        WHERE status = 'processing'
    ) AS processing_count,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS completed_count,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed_count,
    COUNT(*) AS total_count,
    MAX(processed_at) AS last_processed_at,
    AVG(
        EXTRACT(
            EPOCH
            FROM (processed_at - created_at)
        )
    ) FILTER (
        WHERE status = 'completed'
    ) AS avg_processing_seconds
FROM workers.processed_jobs
GROUP BY queue_name;
COMMENT ON VIEW workers.v_queue_stats IS 'Aggregated statistics per queue';
-- ============================================================================
-- PART 10: Security Grants
-- ============================================================================
-- Grant schema usage
GRANT USAGE ON SCHEMA pgmq TO service_role;
GRANT USAGE ON SCHEMA workers TO service_role;
-- Grant table permissions to service_role
GRANT ALL ON ALL TABLES IN SCHEMA workers TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA workers TO service_role;
-- Grant function permissions
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA workers TO service_role;
-- Grant pgmq function access (needed for queue operations)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA pgmq TO service_role;
-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================