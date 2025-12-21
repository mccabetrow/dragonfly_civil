-- ============================================================================
-- Dragonfly Observability Dashboard Queries
-- ============================================================================
-- High-performance queries for operational monitoring.
-- Save these as views in the ops schema for dashboard use.
-- ============================================================================
-- ============================================================================
-- 1. HEARTBEAT LIVENESS (Last 25 heartbeats with latency)
-- ============================================================================
-- Shows worker health status with human-readable latency
-- Table definition (for reference):
-- CREATE TABLE ops.worker_heartbeats (
--     worker_id TEXT PRIMARY KEY,
--     worker_type TEXT NOT NULL,
--     hostname TEXT,
--     last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--     status TEXT NOT NULL DEFAULT 'running',
--     created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
--     updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
-- );
SELECT
    worker_id,
    worker_type,
    status,
    hostname,
    last_seen_at,
    -- Human-readable latency
    created_at,
    -- Is this worker considered alive? (heartbeat within last 2 minutes)
    CASE
        WHEN now() - last_seen_at < interval '1 minute'
            THEN round(
                extract(
                    EPOCH
                    FROM now() - last_seen_at
                )
            )::text || 's ago'
        WHEN now() - last_seen_at < interval '1 hour'
            THEN round(
                extract(
                    EPOCH
                    FROM now() - last_seen_at
                ) / 60
            )::text || 'm ago'
        ELSE round(
            extract(
                EPOCH
                FROM now() - last_seen_at
            ) / 3600,
            1
        )::text || 'h ago'
    END AS latency,
    CASE
        WHEN now() - last_seen_at < interval '2 minutes' THEN 'ALIVE'
        WHEN now() - last_seen_at < interval '5 minutes' THEN 'STALE'
        ELSE 'DEAD'
    END AS liveness
FROM ops.worker_heartbeats
ORDER BY last_seen_at DESC
LIMIT 25;
-- ============================================================================
-- 2. QUEUE HEALTH DASHBOARD (Primary monitoring query)
-- ============================================================================
-- Single high-performance query returning all key metrics per job_type
SELECT
    job_type::text AS job_type,
    -- Status breakdown
    count(*) FILTER (
        WHERE status = 'pending'
    ) AS pending,
    count(*) FILTER (
        WHERE status = 'processing'
    ) AS processing,
    count(*) FILTER (
        WHERE status = 'completed'
    ) AS completed,
    count(*) FILTER (
        WHERE status = 'failed'
    ) AS failed,
    -- Oldest pending job age (minutes) - CRITICAL METRIC
    round(
        extract(
            EPOCH
            FROM (
                now() - min(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
        ) / 60.0,
        1
    ) AS oldest_pending_minutes,
    -- Stuck count: jobs processing for > 10 minutes
    count(*) FILTER (
        WHERE status = 'processing'
        AND started_at IS NOT NULL
        AND started_at < now() - interval '10 minutes'
    ) AS stuck_count,
    -- DLQ size (failed jobs marked with [DLQ])
    count(*) FILTER (
        WHERE status = 'failed'
        AND last_error LIKE '[DLQ]%'
    ) AS dlq_count,
    -- Jobs in backoff (pending but scheduled for future)
    count(*) FILTER (
        WHERE status = 'pending'
        AND next_run_at IS NOT NULL
        AND next_run_at > now()
    ) AS backoff_count,
    -- Throughput (completed in last hour)
    count(*) FILTER (
        WHERE status = 'completed'
        AND updated_at > now() - interval '1 hour'
    ) AS completed_last_hour,
    -- Failure rate (last hour)
    CASE
        WHEN
            count(*) FILTER (
                WHERE updated_at > now() - interval '1 hour'
            ) > 0
            THEN round(
                100.0 * count(*) FILTER (
                    WHERE status = 'failed'
                    AND updated_at > now() - interval '1 hour'
                ) / count(*) FILTER (
                    WHERE updated_at > now() - interval '1 hour'
                ),
                1
            )
        ELSE 0
    END AS failure_rate_pct,
    -- Health status classification
    CASE
        WHEN count(*) FILTER (
            WHERE status = 'processing'
            AND started_at < now() - interval '10 minutes'
        ) > 0 THEN 'CRITICAL'
        WHEN extract(
            EPOCH
            FROM (
                now() - min(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
        ) / 60.0 > 30 THEN 'WARNING'
        WHEN count(*) FILTER (
            WHERE status = 'failed'
        ) > 50 THEN 'DEGRADED'
        ELSE 'HEALTHY'
    END AS health_status
FROM ops.job_queue
GROUP BY job_type
ORDER BY -- Show critical issues first
    CASE
        WHEN count(*) FILTER (
            WHERE status = 'processing'
            AND started_at < now() - interval '10 minutes'
        ) > 0 THEN 0
        ELSE 1
    END,
    oldest_pending_minutes DESC NULLS LAST;
-- ============================================================================
-- 3. OVERALL QUEUE HEALTH SUMMARY (Single row for alerts)
-- ============================================================================
SELECT
    count(*) FILTER (
        WHERE status = 'pending'
    ) AS total_pending,
    count(*) FILTER (
        WHERE status = 'processing'
    ) AS total_processing,
    count(*) FILTER (
        WHERE status = 'completed'
    ) AS total_completed,
    count(*) FILTER (
        WHERE status = 'failed'
    ) AS total_failed,
    -- Critical metrics
    count(*) FILTER (
        WHERE status = 'processing'
        AND started_at < now() - interval '10 minutes'
    ) AS stuck_jobs_total,
    round(
        extract(
            EPOCH
            FROM (
                now() - min(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
        ) / 60.0,
        1
    ) AS oldest_pending_minutes,
    count(*) FILTER (
        WHERE status = 'failed'
        AND last_error LIKE '[DLQ]%'
    ) AS dlq_total,
    -- Overall health
    CASE
        WHEN count(*) FILTER (
            WHERE status = 'processing'
            AND started_at < now() - interval '10 minutes'
        ) > 0 THEN 'CRITICAL'
        WHEN extract(
            EPOCH
            FROM (
                now() - min(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
        ) / 60.0 > 60 THEN 'WARNING'
        WHEN count(*) FILTER (
            WHERE status = 'failed'
        ) > 100 THEN 'DEGRADED'
        ELSE 'HEALTHY'
    END AS health_status
FROM ops.job_queue;
-- ============================================================================
-- 4. CREATE VIEWS FOR DASHBOARD (Optional - run once)
-- ============================================================================
-- Uncomment to create persistent views:
-- CREATE OR REPLACE VIEW ops.v_heartbeat_liveness AS
-- SELECT ... (query 1 above);
-- CREATE OR REPLACE VIEW ops.v_queue_health_by_type AS  
-- SELECT ... (query 2 above);
-- CREATE OR REPLACE VIEW ops.v_queue_health_summary AS
-- SELECT ... (query 3 above);
