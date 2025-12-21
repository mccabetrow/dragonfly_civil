-- ============================================================================
-- Dragonfly Civil – Queue & Worker Observability Dashboard
-- ============================================================================
-- PURPOSE: Single-file observability queries for queue health, worker liveness,
--          and alerting. Run via psql, n8n, or scheduled Supabase RPC.
--
-- USAGE:
--   psql "$SUPABASE_DB_URL" -f scripts/sql/observability_dashboard.sql
--
-- SECTIONS:
--   1. Queue Depth by Job Type
--   2. Oldest Pending Age
--   3. Stuck Processing Jobs
--   4. DLQ Growth Rate
--   5. Worker Liveness Classification
--   6. Combined Health Summary
--   7. Alert Condition Queries
-- ============================================================================
\ echo '══════════════════════════════════════════════════════════════════════════════' \ echo '  DRAGONFLY QUEUE & WORKER OBSERVABILITY DASHBOARD' \ echo '══════════════════════════════════════════════════════════════════════════════' \ echo '' -- ============================================================================
-- SECTION 1: Queue Depth by Job Type
-- ============================================================================
\ echo '── 1. QUEUE DEPTH BY JOB TYPE ──'
SELECT job_type,
    pending_count,
    processing_count,
    completed_count,
    failed_count,
    scheduled_count,
    completed_last_hour AS "throughput/hr"
FROM ops.v_queue_health
ORDER BY pending_count DESC,
    job_type;
\ echo '' -- ============================================================================
-- SECTION 2: Oldest Pending Age (minutes)
-- ============================================================================
\ echo '── 2. OLDEST PENDING AGE ──'
SELECT job_type,
    ROUND(oldest_pending_minutes::numeric, 1) AS oldest_pending_min,
    CASE
        WHEN oldest_pending_minutes > 60 THEN '🔴 CRITICAL'
        WHEN oldest_pending_minutes > 15 THEN '🟡 WARNING'
        WHEN oldest_pending_minutes > 5 THEN '🟢 OK'
        ELSE '✅ FRESH'
    END AS status
FROM ops.v_queue_health
WHERE pending_count > 0
ORDER BY oldest_pending_minutes DESC NULLS LAST;
\ echo '' -- ============================================================================
-- SECTION 3: Stuck Processing Jobs (processing > 1 hour)
-- ============================================================================
\ echo '── 3. STUCK PROCESSING JOBS ──' -- Summary by type
SELECT job_type,
    stuck_jobs_count,
    CASE
        WHEN stuck_jobs_count > 0 THEN '🔴 STUCK DETECTED'
        ELSE '✅ CLEAR'
    END AS status
FROM ops.v_queue_health
WHERE processing_count > 0
    OR stuck_jobs_count > 0;
-- Detailed stuck jobs (if any)
\ echo '' \ echo 'Detailed stuck jobs (processing > 1 hour):'
SELECT id,
    job_type::text AS job_type,
    worker_id,
    started_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - started_at)
        ) / 60.0,
        1
    ) AS stuck_minutes,
    attempts,
    reap_count
FROM ops.job_queue
WHERE status = 'processing'
    AND started_at < now() - interval '1 hour'
ORDER BY started_at ASC
LIMIT 20;
\ echo '' -- ============================================================================
-- SECTION 4: DLQ (Dead Letter Queue) Growth Rate
-- ============================================================================
\ echo '── 4. DLQ GROWTH RATE ──' WITH dlq_stats AS (
    SELECT -- Current DLQ size (jobs marked failed with [DLQ] prefix in error)
        COUNT(*) FILTER (
            WHERE status = 'failed'
                AND (
                    last_error LIKE '[DLQ]%'
                    OR attempts >= max_attempts
                )
        ) AS dlq_current,
        -- DLQ entries in last hour
        COUNT(*) FILTER (
            WHERE status = 'failed'
                AND (
                    last_error LIKE '[DLQ]%'
                    OR attempts >= max_attempts
                )
                AND updated_at > now() - interval '1 hour'
        ) AS dlq_last_hour,
        -- DLQ entries in last 24 hours
        COUNT(*) FILTER (
            WHERE status = 'failed'
                AND (
                    last_error LIKE '[DLQ]%'
                    OR attempts >= max_attempts
                )
                AND updated_at > now() - interval '24 hours'
        ) AS dlq_last_24h,
        -- Total failed (for context)
        COUNT(*) FILTER (
            WHERE status = 'failed'
        ) AS total_failed
    FROM ops.job_queue
)
SELECT dlq_current AS "DLQ Total",
    dlq_last_hour AS "DLQ/1hr",
    dlq_last_24h AS "DLQ/24hr",
    total_failed AS "Failed Total",
    CASE
        WHEN dlq_last_hour > 10 THEN '🔴 HIGH RATE'
        WHEN dlq_last_hour > 3 THEN '🟡 ELEVATED'
        WHEN dlq_last_hour > 0 THEN '🟢 LOW'
        ELSE '✅ CLEAR'
    END AS status
FROM dlq_stats;
\ echo '' -- ============================================================================
-- SECTION 5: Worker Liveness Classification
-- ============================================================================
\ echo '── 5. WORKER LIVENESS ──'
SELECT worker_id,
    worker_type,
    hostname,
    status AS reported_status,
    last_seen_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - last_seen_at)
        )::numeric,
        0
    ) AS seconds_ago,
    CASE
        WHEN last_seen_at > now() - interval '60 seconds'
        AND status = 'running' THEN '🟢 ONLINE'
        WHEN last_seen_at > now() - interval '2 minutes' THEN '🟡 STALE'
        WHEN last_seen_at > now() - interval '5 minutes' THEN '🟠 WARNING'
        ELSE '🔴 OFFLINE'
    END AS liveness
FROM ops.worker_heartbeats
ORDER BY worker_type,
    last_seen_at DESC;
\ echo '' -- Worker type summary
\ echo 'Worker Type Summary:'
SELECT worker_type,
    COUNT(*) AS total_workers,
    COUNT(*) FILTER (
        WHERE last_seen_at > now() - interval '60 seconds'
            AND status = 'running'
    ) AS online,
    COUNT(*) FILTER (
        WHERE last_seen_at <= now() - interval '60 seconds'
            OR status != 'running'
    ) AS offline_or_stale,
    MAX(last_seen_at) AS newest_heartbeat
FROM ops.worker_heartbeats
GROUP BY worker_type
ORDER BY worker_type;
\ echo '' -- ============================================================================
-- SECTION 6: Combined Health Summary (single row)
-- ============================================================================
\ echo '── 6. COMBINED HEALTH SUMMARY ──'
SELECT *
FROM ops.get_queue_health_summary();
\ echo '' -- ============================================================================
-- SECTION 7: Alert Condition Queries
-- ============================================================================
\ echo '══════════════════════════════════════════════════════════════════════════════' \ echo '  ALERT CONDITIONS' \ echo '══════════════════════════════════════════════════════════════════════════════' \ echo '' -- These queries return rows only when alert conditions are met.
-- Use with n8n, pg_cron, or external monitoring.
\ echo '── ALERT: Stuck Jobs (processing > 10 min) ──'
SELECT 'STUCK_JOBS' AS alert_type,
    COUNT(*) AS count,
    MIN(started_at) AS oldest_stuck,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - MIN(started_at))
        ) / 60.0,
        1
    ) AS oldest_stuck_minutes
FROM ops.job_queue
WHERE status = 'processing'
    AND started_at < now() - interval '10 minutes'
HAVING COUNT(*) > 0;
\ echo '' \ echo '── ALERT: Oldest Pending > 15 min ──'
SELECT 'OLDEST_PENDING' AS alert_type,
    job_type::text AS job_type,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - created_at)
        ) / 60.0,
        1
    ) AS age_minutes
FROM ops.job_queue
WHERE status = 'pending'
    AND created_at < now() - interval '15 minutes'
ORDER BY created_at ASC
LIMIT 5;
\ echo '' \ echo '── ALERT: DLQ Growth (>3 in last hour) ──'
SELECT 'DLQ_GROWTH' AS alert_type,
    COUNT(*) AS dlq_count_last_hour
FROM ops.job_queue
WHERE status = 'failed'
    AND (
        last_error LIKE '[DLQ]%'
        OR attempts >= max_attempts
    )
    AND updated_at > now() - interval '1 hour'
HAVING COUNT(*) > 3;
\ echo '' \ echo '── ALERT: Heartbeat Stale (no heartbeat in 2 min) ──'
SELECT 'HEARTBEAT_STALE' AS alert_type,
    worker_id,
    worker_type,
    last_seen_at,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (now() - last_seen_at)
        )::numeric,
        0
    ) AS seconds_stale
FROM ops.worker_heartbeats
WHERE last_seen_at < now() - interval '2 minutes'
    AND status = 'running';
\ echo '' \ echo '══════════════════════════════════════════════════════════════════════════════' \ echo '  END OF OBSERVABILITY DASHBOARD' \ echo '══════════════════════════════════════════════════════════════════════════════'