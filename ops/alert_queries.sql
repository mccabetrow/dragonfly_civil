-- =============================================================================
-- Dragonfly Alert Queries - Used by backend/workers/monitor.py
-- =============================================================================
-- Each query returns rows that indicate an ALERT condition.
-- If a query returns 0 rows, the check passes (no alert).
-- If a query returns 1+ rows, those rows describe the alert.
-- =============================================================================
-- -----------------------------------------------------------------------------
-- STUCK_JOBS: Jobs in 'processing' state for over 30 minutes
-- Indicates a worker may have crashed or be deadlocked
-- -----------------------------------------------------------------------------
-- @name: stuck_jobs
-- @severity: CRITICAL
SELECT id,
    job_type,
    worker_id,
    locked_at,
    EXTRACT(
        EPOCH
        FROM (NOW() - locked_at)
    ) / 60 AS minutes_stuck
FROM ops.job_queue
WHERE status = 'processing'
    AND locked_at < NOW() - INTERVAL '30 minutes'
ORDER BY locked_at ASC
LIMIT 10;
-- -----------------------------------------------------------------------------
-- HIGH_FAILURE_RATE: More than 10% of jobs failed in the last hour
-- Indicates systematic processing issues
-- -----------------------------------------------------------------------------
-- @name: high_failure_rate
-- @severity: CRITICAL
WITH hourly_stats AS (
    SELECT COUNT(*) FILTER (
            WHERE status = 'completed'
        ) AS completed,
        COUNT(*) FILTER (
            WHERE status = 'failed'
        ) AS failed,
        COUNT(*) AS total
    FROM ops.job_queue
    WHERE updated_at >= NOW() - INTERVAL '1 hour'
)
SELECT completed,
    failed,
    total,
    ROUND(100.0 * failed / NULLIF(total, 0), 2) AS failure_rate_pct
FROM hourly_stats
WHERE total > 10 -- Only alert if meaningful sample size
    AND (100.0 * failed / NULLIF(total, 0)) > 10;
-- -----------------------------------------------------------------------------
-- DEAD_WORKERS: Workers with no heartbeat in over 5 minutes
-- Indicates worker process may have crashed without clean shutdown
-- -----------------------------------------------------------------------------
-- @name: dead_workers
-- @severity: WARNING
SELECT worker_id,
    worker_type,
    status,
    last_seen_at,
    EXTRACT(
        EPOCH
        FROM (NOW() - last_seen_at)
    ) / 60 AS minutes_since_heartbeat
FROM ops.worker_heartbeats
WHERE status NOT IN ('stopped', 'error')
    AND last_seen_at < NOW() - INTERVAL '5 minutes'
ORDER BY last_seen_at ASC
LIMIT 10;
-- -----------------------------------------------------------------------------
-- DLQ_GROWING: Dead letter queue has entries (failed jobs that exceeded retries)
-- Indicates jobs are permanently failing and need manual intervention
-- -----------------------------------------------------------------------------
-- @name: dlq_growing
-- @severity: WARNING
SELECT id,
    job_type,
    last_error,
    attempts,
    updated_at
FROM ops.job_queue
WHERE status = 'failed'
    AND attempts >= 3
    AND updated_at >= NOW() - INTERVAL '1 hour'
ORDER BY updated_at DESC
LIMIT 10;
-- -----------------------------------------------------------------------------
-- PENDING_QUEUE_BACKLOG: More than 100 pending jobs
-- Indicates workers may be under-provisioned or stuck
-- -----------------------------------------------------------------------------
-- @name: pending_backlog
-- @severity: WARNING
SELECT job_type,
    COUNT(*) AS pending_count,
    MIN(created_at) AS oldest_pending
FROM ops.job_queue
WHERE status = 'pending'
GROUP BY job_type
HAVING COUNT(*) > 100
ORDER BY pending_count DESC;