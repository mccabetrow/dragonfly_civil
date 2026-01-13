-- ============================================================================
-- Migration: 20260601000000_worker_observability.sql
-- Purpose: Worker Observability Infrastructure
--
-- Creates heartbeat tracking and performance metrics tables for monitoring
-- worker health and job processing statistics in real-time.
--
-- Tables:
--   workers.heartbeats  - Real-time worker health status
--   workers.metrics     - Per-queue performance metrics
--
-- Security: service_role only (no authenticated access)
-- ============================================================================
-- ============================================================================
-- PART 0: Ensure workers schema exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS workers;
-- ============================================================================
-- PART 1: Worker Status Enum
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'worker_status'
) THEN CREATE TYPE workers.worker_status AS ENUM (
    'starting',
    -- Worker is initializing
    'healthy',
    -- Worker is actively processing
    'draining',
    -- Worker is finishing current jobs before shutdown
    'stopped' -- Worker has stopped (final heartbeat)
);
RAISE NOTICE 'Created enum workers.worker_status';
END IF;
END $$;
-- ============================================================================
-- PART 2: Heartbeats Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS workers.heartbeats (
    -- Identity
    worker_id UUID PRIMARY KEY,
    queue_name TEXT NOT NULL,
    -- Worker metadata
    hostname TEXT NOT NULL DEFAULT 'unknown',
    version TEXT NOT NULL DEFAULT '0.0.0',
    pid INTEGER NOT NULL DEFAULT 0,
    -- Status tracking
    status workers.worker_status NOT NULL DEFAULT 'starting',
    last_heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Performance snapshot
    jobs_processed BIGINT NOT NULL DEFAULT 0,
    jobs_failed BIGINT NOT NULL DEFAULT 0,
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB DEFAULT '{}'::jsonb
);
COMMENT ON TABLE workers.heartbeats IS 'Real-time worker health tracking. Workers update their row every 30 seconds.';
COMMENT ON COLUMN workers.heartbeats.worker_id IS 'Unique identifier for the worker instance (UUID generated at startup)';
COMMENT ON COLUMN workers.heartbeats.queue_name IS 'The pgmq queue this worker consumes from';
COMMENT ON COLUMN workers.heartbeats.status IS 'Current lifecycle state: starting -> healthy -> draining -> stopped';
COMMENT ON COLUMN workers.heartbeats.last_heartbeat_at IS 'Last time this worker sent a heartbeat. Stale = worker is dead.';
-- Index for finding stale workers (no heartbeat in X minutes)
CREATE INDEX IF NOT EXISTS ix_heartbeats_stale ON workers.heartbeats (last_heartbeat_at)
WHERE status NOT IN ('stopped');
-- Index for queue-level aggregation
CREATE INDEX IF NOT EXISTS ix_heartbeats_queue ON workers.heartbeats (queue_name, status);
-- ============================================================================
-- PART 3: Queue Metrics Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS workers.metrics (
    -- Primary key: one row per queue
    queue_name TEXT PRIMARY KEY,
    -- Last success tracking
    last_job_id UUID,
    last_success_at TIMESTAMPTZ,
    -- Aggregate stats (updated on each job completion)
    total_processed BIGINT NOT NULL DEFAULT 0,
    total_failed BIGINT NOT NULL DEFAULT 0,
    -- Latency tracking (rolling average in ms)
    avg_latency_ms INTEGER NOT NULL DEFAULT 0,
    max_latency_ms INTEGER NOT NULL DEFAULT 0,
    min_latency_ms INTEGER,
    -- Throughput (jobs per minute, computed from recent window)
    throughput_jpm NUMERIC(10, 2) DEFAULT 0.0,
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE workers.metrics IS 'Per-queue performance metrics. Updated on each job completion.';
COMMENT ON COLUMN workers.metrics.queue_name IS 'The pgmq queue name (matches workers.heartbeats.queue_name)';
COMMENT ON COLUMN workers.metrics.last_job_id IS 'UUID of the most recently completed job (from envelope.job_id)';
COMMENT ON COLUMN workers.metrics.avg_latency_ms IS 'Rolling average processing time in milliseconds';
COMMENT ON COLUMN workers.metrics.throughput_jpm IS 'Estimated jobs per minute based on recent completions';
-- ============================================================================
-- PART 4: Helper Functions
-- ============================================================================
-- Upsert heartbeat (called by worker every 30s)
CREATE OR REPLACE FUNCTION workers.upsert_heartbeat(
        p_worker_id UUID,
        p_queue_name TEXT,
        p_hostname TEXT,
        p_version TEXT,
        p_pid INTEGER,
        p_status workers.worker_status,
        p_jobs_processed BIGINT DEFAULT 0,
        p_jobs_failed BIGINT DEFAULT 0,
        p_metadata JSONB DEFAULT '{}'::jsonb
    ) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = workers,
    pg_catalog AS $$ BEGIN
INSERT INTO workers.heartbeats (
        worker_id,
        queue_name,
        hostname,
        version,
        pid,
        status,
        last_heartbeat_at,
        jobs_processed,
        jobs_failed,
        metadata
    )
VALUES (
        p_worker_id,
        p_queue_name,
        p_hostname,
        p_version,
        p_pid,
        p_status,
        now(),
        p_jobs_processed,
        p_jobs_failed,
        p_metadata
    ) ON CONFLICT (worker_id) DO
UPDATE
SET queue_name = EXCLUDED.queue_name,
    hostname = EXCLUDED.hostname,
    version = EXCLUDED.version,
    pid = EXCLUDED.pid,
    status = EXCLUDED.status,
    last_heartbeat_at = now(),
    jobs_processed = EXCLUDED.jobs_processed,
    jobs_failed = EXCLUDED.jobs_failed,
    metadata = EXCLUDED.metadata;
END;
$$;
COMMENT ON FUNCTION workers.upsert_heartbeat IS 'Update worker heartbeat. Call every 30 seconds from worker loop.';
-- Update queue metrics on job completion
CREATE OR REPLACE FUNCTION workers.update_metrics(
        p_queue_name TEXT,
        p_job_id UUID,
        p_latency_ms INTEGER,
        p_success BOOLEAN DEFAULT TRUE
    ) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = workers,
    pg_catalog AS $$
DECLARE v_current_avg INTEGER;
v_current_total BIGINT;
v_new_avg INTEGER;
BEGIN -- Upsert metrics row with rolling average calculation
INSERT INTO workers.metrics (
        queue_name,
        last_job_id,
        last_success_at,
        total_processed,
        total_failed,
        avg_latency_ms,
        max_latency_ms,
        min_latency_ms,
        updated_at
    )
VALUES (
        p_queue_name,
        CASE
            WHEN p_success THEN p_job_id
            ELSE NULL
        END,
        CASE
            WHEN p_success THEN now()
            ELSE NULL
        END,
        CASE
            WHEN p_success THEN 1
            ELSE 0
        END,
        CASE
            WHEN p_success THEN 0
            ELSE 1
        END,
        p_latency_ms,
        p_latency_ms,
        p_latency_ms,
        now()
    ) ON CONFLICT (queue_name) DO
UPDATE
SET last_job_id = CASE
        WHEN p_success THEN p_job_id
        ELSE workers.metrics.last_job_id
    END,
    last_success_at = CASE
        WHEN p_success THEN now()
        ELSE workers.metrics.last_success_at
    END,
    total_processed = workers.metrics.total_processed + CASE
        WHEN p_success THEN 1
        ELSE 0
    END,
    total_failed = workers.metrics.total_failed + CASE
        WHEN p_success THEN 0
        ELSE 1
    END,
    -- Exponential moving average: new_avg = 0.9 * old_avg + 0.1 * new_value
    avg_latency_ms = CASE
        WHEN p_success THEN (
            (
                workers.metrics.avg_latency_ms * 9 + p_latency_ms
            ) / 10
        )::INTEGER
        ELSE workers.metrics.avg_latency_ms
    END,
    max_latency_ms = GREATEST(workers.metrics.max_latency_ms, p_latency_ms),
    min_latency_ms = LEAST(
        COALESCE(workers.metrics.min_latency_ms, p_latency_ms),
        p_latency_ms
    ),
    updated_at = now();
END;
$$;
COMMENT ON FUNCTION workers.update_metrics IS 'Update queue metrics after job completion. Maintains rolling averages.';
-- Find stale workers (no heartbeat in X minutes)
CREATE OR REPLACE FUNCTION workers.find_stale_workers(
        p_stale_threshold_minutes INTEGER DEFAULT 5
    ) RETURNS TABLE (
        worker_id UUID,
        queue_name TEXT,
        hostname TEXT,
        status workers.worker_status,
        last_heartbeat_at TIMESTAMPTZ,
        minutes_stale NUMERIC
    ) LANGUAGE sql SECURITY DEFINER
SET search_path = workers,
    pg_catalog STABLE AS $$
SELECT h.worker_id,
    h.queue_name,
    h.hostname,
    h.status,
    h.last_heartbeat_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - h.last_heartbeat_at)
        ) / 60,
        1
    ) AS minutes_stale
FROM workers.heartbeats h
WHERE h.status NOT IN ('stopped')
    AND h.last_heartbeat_at < now() - (p_stale_threshold_minutes || ' minutes')::INTERVAL
ORDER BY h.last_heartbeat_at ASC;
$$;
COMMENT ON FUNCTION workers.find_stale_workers IS 'Find workers that have not sent a heartbeat recently. Used for alerting.';
-- ============================================================================
-- PART 5: Views for Monitoring
-- ============================================================================
CREATE OR REPLACE VIEW workers.v_worker_health AS
SELECT h.queue_name,
    h.worker_id,
    h.hostname,
    h.status,
    h.last_heartbeat_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - h.last_heartbeat_at)
        )
    )::INTEGER AS seconds_since_heartbeat,
    h.jobs_processed,
    h.jobs_failed,
    h.version,
    h.pid,
    CASE
        WHEN h.status = 'stopped' THEN 'stopped'
        WHEN h.last_heartbeat_at < now() - INTERVAL '5 minutes' THEN 'dead'
        WHEN h.last_heartbeat_at < now() - INTERVAL '2 minutes' THEN 'stale'
        ELSE 'alive'
    END AS health_status
FROM workers.heartbeats h
ORDER BY h.queue_name,
    h.last_heartbeat_at DESC;
COMMENT ON VIEW workers.v_worker_health IS 'Worker health dashboard view with computed health status';
CREATE OR REPLACE VIEW workers.v_queue_metrics AS
SELECT m.queue_name,
    m.total_processed,
    m.total_failed,
    ROUND(
        m.total_failed::NUMERIC / NULLIF(m.total_processed + m.total_failed, 0) * 100,
        2
    ) AS failure_rate_pct,
    m.avg_latency_ms,
    m.min_latency_ms,
    m.max_latency_ms,
    m.last_success_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - m.last_success_at)
        ) / 60,
        1
    ) AS minutes_since_last_success,
    m.throughput_jpm,
    -- Count active workers for this queue
    (
        SELECT COUNT(*)
        FROM workers.heartbeats h
        WHERE h.queue_name = m.queue_name
            AND h.status = 'healthy'
            AND h.last_heartbeat_at > now() - INTERVAL '2 minutes'
    ) AS active_workers
FROM workers.metrics m
ORDER BY m.queue_name;
COMMENT ON VIEW workers.v_queue_metrics IS 'Queue-level performance metrics with active worker counts';
-- ============================================================================
-- PART 6: Security - service_role only
-- ============================================================================
-- Revoke all from public
REVOKE ALL ON workers.heartbeats
FROM PUBLIC;
REVOKE ALL ON workers.metrics
FROM PUBLIC;
REVOKE ALL ON workers.v_worker_health
FROM PUBLIC;
REVOKE ALL ON workers.v_queue_metrics
FROM PUBLIC;
-- Grant to service_role only (workers run as service_role)
GRANT SELECT,
    INSERT,
    UPDATE ON workers.heartbeats TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON workers.metrics TO service_role;
GRANT SELECT ON workers.v_worker_health TO service_role;
GRANT SELECT ON workers.v_queue_metrics TO service_role;
-- Grant execute on functions
GRANT EXECUTE ON FUNCTION workers.upsert_heartbeat TO service_role;
GRANT EXECUTE ON FUNCTION workers.update_metrics TO service_role;
GRANT EXECUTE ON FUNCTION workers.find_stale_workers TO service_role;
-- ============================================================================
-- Migration Complete
-- ============================================================================
DO $$ BEGIN RAISE NOTICE '✅ Worker Observability migration complete';
RAISE NOTICE '   - workers.heartbeats table created';
RAISE NOTICE '   - workers.metrics table created';
RAISE NOTICE '   - Helper functions installed';
RAISE NOTICE '   - Monitoring views created';
END $$;