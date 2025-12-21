-- ============================================================================
-- Dragonfly Queue Health Dashboard Queries
-- ============================================================================
-- These queries provide real-time observability into the job queue system.
-- Use for dashboards, alerting, and operational monitoring.
-- ============================================================================
-- ============================================================================
-- QUERY 1: Queue Health by Job Type (Primary Dashboard View)
-- ============================================================================
-- Returns one row per job type with all key metrics.
-- Use this as the main dashboard widget.
SELECT
    job_type::text AS job_type,
    -- Current queue depth
    COUNT(*) FILTER (
        WHERE status = 'pending'
    ) AS pending_count,
    COUNT(*) FILTER (
        WHERE status = 'processing'
    ) AS processing_count,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed_count,
    -- Critical alert metric: How old is the oldest pending job?
    ROUND(
        EXTRACT(
            EPOCH
            FROM (
                NOW() - MIN(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
        ) / 60.0,
        1
    ) AS oldest_pending_minutes,
    -- Stuck jobs: Processing for more than 1 hour (CRITICAL)
    COUNT(*) FILTER (
        WHERE status = 'processing'
        AND started_at < NOW() - interval '1 hour'
    ) AS stuck_jobs_count,
    -- Jobs waiting in backoff
    COUNT(*) FILTER (
        WHERE status = 'pending'
        AND next_run_at > NOW()
    ) AS in_backoff_count,
    -- Throughput metrics (last hour)
    COUNT(*) FILTER (
        WHERE status = 'completed'
        AND updated_at > NOW() - interval '1 hour'
    ) AS completed_last_hour,
    COUNT(*) FILTER (
        WHERE status = 'failed'
        AND updated_at > NOW() - interval '1 hour'
    ) AS failed_last_hour,
    -- Error rate (last hour)
    CASE
        WHEN
            COUNT(*) FILTER (
                WHERE updated_at > NOW() - interval '1 hour'
            ) > 0
            THEN ROUND(
                100.0 * COUNT(*) FILTER (
                    WHERE status = 'failed'
                    AND updated_at > NOW() - interval '1 hour'
                ) / COUNT(*) FILTER (
                    WHERE updated_at > NOW() - interval '1 hour'
                ),
                1
            )
        ELSE 0
    END AS error_rate_pct
FROM ops.job_queue
GROUP BY job_type
ORDER BY stuck_jobs_count DESC,
-- Critical issues first
oldest_pending_minutes DESC NULLS LAST;
-- ============================================================================
-- QUERY 2: Overall Queue Health Summary (Single Row)
-- ============================================================================
-- Use this for a top-level health indicator.
SELECT
    COUNT(*) FILTER (
        WHERE status = 'pending'
    ) AS total_pending,
    COUNT(*) FILTER (
        WHERE status = 'processing'
    ) AS total_processing,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS total_completed,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS total_failed,
    -- DLQ size (failed jobs that were reaped)
    COUNT(*) FILTER (
        WHERE status = 'failed'
        AND last_error LIKE '[DLQ]%'
    ) AS dlq_size,
    -- Critical metrics
    ROUND(
        EXTRACT(
            EPOCH
            FROM (
                NOW() - MIN(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
        ) / 60.0,
        1
    ) AS oldest_pending_minutes,
    COUNT(*) FILTER (
        WHERE status = 'processing'
        AND started_at < NOW() - interval '1 hour'
    ) AS stuck_jobs_count,
    -- Health classification
    CASE
        WHEN COUNT(*) FILTER (
            WHERE status = 'processing'
            AND started_at < NOW() - interval '1 hour'
        ) > 0 THEN 'CRITICAL'
        WHEN EXTRACT(
            EPOCH
            FROM (
                NOW() - MIN(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
        ) / 60.0 > 60 THEN 'WARNING'
        WHEN COUNT(*) FILTER (
            WHERE status = 'failed'
        ) > 100 THEN 'DEGRADED'
        ELSE 'HEALTHY'
    END AS health_status
FROM ops.job_queue;
-- ============================================================================
-- QUERY 3: Stuck Jobs Detail (For Investigation)
-- ============================================================================
-- List all currently stuck jobs with full details.
SELECT
    id AS job_id,
    job_type::text,
    payload,
    attempts,
    max_attempts,
    worker_id,
    started_at,
    last_error,
    reap_count,
    created_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (NOW() - started_at)
        ) / 60.0,
        1
    ) AS stuck_minutes
FROM ops.job_queue
WHERE
    status = 'processing'
    AND started_at < NOW() - interval '30 minutes'
ORDER BY started_at ASC;
-- ============================================================================
-- QUERY 4: Dead Letter Queue (DLQ) Contents
-- ============================================================================
-- Failed jobs that have exceeded max attempts.
SELECT
    id AS job_id,
    job_type::text,
    payload,
    attempts,
    max_attempts,
    last_error,
    reap_count,
    created_at,
    updated_at AS failed_at
FROM ops.job_queue
WHERE
    status = 'failed'
    AND last_error LIKE '[DLQ]%'
ORDER BY updated_at DESC
LIMIT 100;
-- ============================================================================
-- QUERY 5: Jobs in Backoff (Waiting for Retry)
-- ============================================================================
-- Jobs that failed and are waiting for their next retry attempt.
SELECT
    id AS job_id,
    job_type::text,
    attempts,
    max_attempts,
    next_run_at,
    last_error,
    reap_count,
    created_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (next_run_at - NOW())
        ) / 60.0,
        1
    ) AS retry_in_minutes
FROM ops.job_queue
WHERE
    status = 'pending'
    AND next_run_at > NOW()
ORDER BY next_run_at ASC;
-- ============================================================================
-- QUERY 6: Worker Activity (Last 5 Minutes)
-- ============================================================================
-- Which workers are actively processing jobs?
SELECT
    worker_id,
    COUNT(*) AS active_jobs,
    ARRAY_AGG(DISTINCT job_type::text) AS job_types,
    MIN(started_at) AS oldest_job_started,
    MAX(started_at) AS newest_job_started
FROM ops.job_queue
WHERE
    status = 'processing'
    AND worker_id IS NOT NULL
GROUP BY worker_id
ORDER BY active_jobs DESC;
-- ============================================================================
-- QUERY 7: Hourly Throughput (Last 24 Hours)
-- ============================================================================
-- For time-series charts.
SELECT
    DATE_TRUNC('hour', updated_at) AS hour_bucket,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS completed,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed,
    ROUND(
        AVG(attempts) FILTER (
            WHERE status = 'completed'
        ),
        2
    ) AS avg_attempts_success
FROM ops.job_queue
WHERE
    updated_at > NOW() - interval '24 hours'
    AND status IN ('completed', 'failed')
GROUP BY DATE_TRUNC('hour', updated_at)
ORDER BY hour_bucket DESC;
-- ============================================================================
-- QUERY 8: Alert Thresholds Check
-- ============================================================================
-- Use for automated alerting. Returns rows only when thresholds exceeded.
SELECT
    'stuck_jobs' AS alert_type,
    'CRITICAL' AS severity,
    COUNT(*) AS count,
    FORMAT(
        'Jobs stuck in processing for > 1 hour: %s',
        COUNT(*)
    ) AS message
FROM ops.job_queue
WHERE
    status = 'processing'
    AND started_at < NOW() - interval '1 hour'
HAVING COUNT(*) > 0
UNION ALL
SELECT
    'queue_backlog' AS alert_type,
    'WARNING' AS severity,
    COUNT(*) AS count,
    FORMAT('Pending jobs older than 1 hour: %s', COUNT(*)) AS message
FROM ops.job_queue
WHERE
    status = 'pending'
    AND created_at < NOW() - interval '1 hour'
    AND (
        next_run_at IS NULL
        OR next_run_at <= NOW()
    )
HAVING COUNT(*) > 0
UNION ALL
SELECT
    'dlq_growth' AS alert_type,
    'WARNING' AS severity,
    COUNT(*) AS count,
    FORMAT('DLQ jobs in last hour: %s', COUNT(*)) AS message
FROM ops.job_queue
WHERE
    status = 'failed'
    AND last_error LIKE '[DLQ]%'
    AND updated_at > NOW() - interval '1 hour'
HAVING COUNT(*) > 0;
