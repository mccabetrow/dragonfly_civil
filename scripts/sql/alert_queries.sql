-- ============================================================================
-- Dragonfly Civil – Alert Condition Queries
-- ============================================================================
-- PURPOSE: Standalone alert queries designed for n8n/Discord webhook triggers.
--          Each query returns a single JSON row when alert condition is met,
--          or empty result when healthy.
--
-- USAGE:
--   1. Schedule via pg_cron or n8n Postgres trigger
--   2. If row returned, fire webhook to Discord
--   3. Threshold tuning in comments for each query
--
-- THRESHOLDS (configurable):
--   - STUCK_JOBS: processing > 10 minutes
--   - OLDEST_PENDING: pending > 15 minutes
--   - DLQ_GROWTH: > 3 DLQ entries in 1 hour
--   - HEARTBEAT_STALE: no heartbeat for 2 minutes
-- ============================================================================
-- ============================================================================
-- ALERT 1: Stuck Jobs (processing > 10 minutes)
-- Threshold: Jobs stuck in 'processing' for more than 10 minutes
-- Severity: CRITICAL (worker may be hung or crashed)
-- ============================================================================
-- Use: Run every 5 minutes. If result, alert immediately.
SELECT json_build_object(
        'alert_type',
        'STUCK_JOBS',
        'severity',
        'critical',
        'timestamp',
        now()::text,
        'stuck_count',
        COUNT(*),
        'oldest_stuck_minutes',
        ROUND(
            EXTRACT(
                EPOCH
                FROM (now() - MIN(started_at))
            ) / 60.0,
            1
        ),
        'job_types',
        array_agg(DISTINCT job_type::text),
        'message',
        format(
            '🔴 %s jobs stuck in processing for >10 min',
            COUNT(*)
        )
    ) AS alert_payload
FROM ops.job_queue
WHERE status = 'processing'
    AND started_at < now() - interval '10 minutes'
HAVING COUNT(*) > 0;
-- ============================================================================
-- ALERT 2: Oldest Pending > 15 minutes
-- Threshold: Any pending job older than 15 minutes
-- Severity: WARNING (queue backup, workers may be slow/offline)
-- ============================================================================
-- Use: Run every 5 minutes. Alert if queue is backing up.
SELECT json_build_object(
        'alert_type',
        'OLDEST_PENDING',
        'severity',
        'warning',
        'timestamp',
        now()::text,
        'oldest_age_minutes',
        ROUND(
            EXTRACT(
                EPOCH
                FROM (now() - MIN(created_at))
            ) / 60.0,
            1
        ),
        'pending_count',
        COUNT(*),
        'job_types',
        array_agg(DISTINCT job_type::text),
        'message',
        format(
            '🟡 Queue backup: oldest pending job is %.1f min old (%s pending)',
            ROUND(
                EXTRACT(
                    EPOCH
                    FROM (now() - MIN(created_at))
                ) / 60.0,
                1
            ),
            COUNT(*)
        )
    ) AS alert_payload
FROM ops.job_queue
WHERE status = 'pending'
    AND created_at < now() - interval '15 minutes'
HAVING COUNT(*) > 0;
-- ============================================================================
-- ALERT 3: DLQ Growth (> 3 entries in 1 hour)
-- Threshold: More than 3 jobs moved to DLQ in the last hour
-- Severity: WARNING (systematic failure pattern)
-- ============================================================================
-- Use: Run every 15 minutes. Alert on elevated failure rate.
SELECT json_build_object(
        'alert_type',
        'DLQ_GROWTH',
        'severity',
        'warning',
        'timestamp',
        now()::text,
        'dlq_count_1hr',
        COUNT(*),
        'job_types',
        array_agg(DISTINCT job_type::text),
        'latest_errors',
        (
            SELECT array_agg(DISTINCT LEFT(last_error, 100))
            FROM (
                    SELECT last_error
                    FROM ops.job_queue
                    WHERE status = 'failed'
                        AND (
                            last_error LIKE '[DLQ]%'
                            OR attempts >= max_attempts
                        )
                        AND updated_at > now() - interval '1 hour'
                    LIMIT 3
                ) sub
        ), 'message', format(
            '🟡 DLQ growth: %s jobs failed in last hour', COUNT(*)
        )
    ) AS alert_payload
FROM ops.job_queue
WHERE status = 'failed'
    AND (
        last_error LIKE '[DLQ]%'
        OR attempts >= max_attempts
    )
    AND updated_at > now() - interval '1 hour'
HAVING COUNT(*) > 3;
-- ============================================================================
-- ALERT 4: Heartbeat Stale (no heartbeat for 2 minutes)
-- Threshold: Worker marked 'running' but no heartbeat in 2 minutes
-- Severity: CRITICAL (worker process likely dead)
-- ============================================================================
-- Use: Run every 1 minute. Alert immediately if workers go dark.
SELECT json_build_object(
        'alert_type',
        'HEARTBEAT_STALE',
        'severity',
        'critical',
        'timestamp',
        now()::text,
        'stale_workers',
        array_agg(
            json_build_object(
                'worker_id',
                worker_id,
                'worker_type',
                worker_type,
                'hostname',
                hostname,
                'last_seen_at',
                last_seen_at::text,
                'seconds_stale',
                ROUND(
                    EXTRACT(
                        EPOCH
                        FROM (now() - last_seen_at)
                    )::numeric,
                    0
                )
            )
        ),
        'worker_count',
        COUNT(*),
        'message',
        format(
            '🔴 %s worker(s) have stale heartbeats (>2 min)',
            COUNT(*)
        )
    ) AS alert_payload
FROM ops.worker_heartbeats
WHERE last_seen_at < now() - interval '2 minutes'
    AND status = 'running'
HAVING COUNT(*) > 0;
-- ============================================================================
-- COMBINED: Single query for all alerts (for n8n polling)
-- Returns array of active alerts, empty array if all healthy
-- ============================================================================
-- Use: Single query to check all conditions at once
WITH alerts AS (
    -- Stuck jobs
    SELECT json_build_object(
            'alert_type',
            'STUCK_JOBS',
            'severity',
            'critical',
            'count',
            COUNT(*),
            'oldest_minutes',
            ROUND(
                EXTRACT(
                    EPOCH
                    FROM (now() - MIN(started_at))
                ) / 60.0,
                1
            )
        ) AS alert
    FROM ops.job_queue
    WHERE status = 'processing'
        AND started_at < now() - interval '10 minutes'
    HAVING COUNT(*) > 0
    UNION ALL
    -- Oldest pending
    SELECT json_build_object(
            'alert_type',
            'OLDEST_PENDING',
            'severity',
            'warning',
            'count',
            COUNT(*),
            'oldest_minutes',
            ROUND(
                EXTRACT(
                    EPOCH
                    FROM (now() - MIN(created_at))
                ) / 60.0,
                1
            )
        ) AS alert
    FROM ops.job_queue
    WHERE status = 'pending'
        AND created_at < now() - interval '15 minutes'
    HAVING COUNT(*) > 0
    UNION ALL
    -- DLQ growth
    SELECT json_build_object(
            'alert_type',
            'DLQ_GROWTH',
            'severity',
            'warning',
            'count',
            COUNT(*)
        ) AS alert
    FROM ops.job_queue
    WHERE status = 'failed'
        AND (
            last_error LIKE '[DLQ]%'
            OR attempts >= max_attempts
        )
        AND updated_at > now() - interval '1 hour'
    HAVING COUNT(*) > 3
    UNION ALL
    -- Stale heartbeats
    SELECT json_build_object(
            'alert_type',
            'HEARTBEAT_STALE',
            'severity',
            'critical',
            'count',
            COUNT(*)
        ) AS alert
    FROM ops.worker_heartbeats
    WHERE last_seen_at < now() - interval '2 minutes'
        AND status = 'running'
    HAVING COUNT(*) > 0
)
SELECT json_build_object(
        'timestamp',
        now()::text,
        'alerts',
        COALESCE(json_agg(alert), '[]'::json),
        'alert_count',
        COUNT(*),
        'status',
        CASE
            WHEN COUNT(*) = 0 THEN 'healthy'
            WHEN EXISTS (
                SELECT 1
                FROM alerts
                WHERE (alert->>'severity') = 'critical'
            ) THEN 'critical'
            ELSE 'warning'
        END
    ) AS combined_status
FROM alerts;