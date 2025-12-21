-- ============================================================================
-- Migration: 20251221142948_slo_observability.sql
-- SLO Observability Infrastructure - World Class Reliability Monitoring
-- ============================================================================
-- PURPOSE:
--   1. Create ops.view_slo_processing_freshness for latency tracking
--   2. Create ops.view_slo_error_budget for DLQ/failure monitoring
--   3. Create ops.view_slo_system_health for CEO dashboard
--   4. Create ops.view_slo_active_workers for worker health
-- ============================================================================
-- SLO TARGETS:
--   - Ingestion Reliability: 99.9% of uploads return 2xx
--   - Processing Freshness: 95% of jobs processed within 10 minutes
--   - Data Quality: DLQ growth < 1% of total job volume per day
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. ops.view_slo_processing_freshness
-- Tracks job processing latency metrics
-- ============================================================================
CREATE OR REPLACE VIEW ops.view_slo_processing_freshness AS WITH completed_jobs AS (
        -- Jobs completed in the last 24 hours
        SELECT id,
            job_type,
            created_at,
            updated_at AS completed_at,
            EXTRACT(
                EPOCH
                FROM (updated_at - created_at)
            ) / 60 AS latency_minutes
        FROM ops.job_queue
        WHERE status = 'completed'
            AND updated_at >= NOW() - INTERVAL '24 hours'
    ),
    pending_jobs AS (
        -- Currently pending jobs
        SELECT id,
            job_type,
            created_at,
            EXTRACT(
                EPOCH
                FROM (NOW() - created_at)
            ) / 60 AS pending_minutes
        FROM ops.job_queue
        WHERE status = 'pending'
    ),
    processing_jobs AS (
        -- Currently processing jobs
        SELECT id,
            job_type,
            created_at,
            started_at,
            EXTRACT(
                EPOCH
                FROM (NOW() - COALESCE(started_at, created_at))
            ) / 60 AS processing_minutes
        FROM ops.job_queue
        WHERE status = 'processing'
    ),
    latency_stats AS (
        SELECT COUNT(*) AS total_completed_24h,
            ROUND(AVG(latency_minutes)::numeric, 2) AS avg_latency_minutes,
            ROUND(
                PERCENTILE_CONT(0.50) WITHIN GROUP (
                    ORDER BY latency_minutes
                )::numeric,
                2
            ) AS p50_latency_minutes,
            ROUND(
                PERCENTILE_CONT(0.95) WITHIN GROUP (
                    ORDER BY latency_minutes
                )::numeric,
                2
            ) AS p95_latency_minutes,
            ROUND(
                PERCENTILE_CONT(0.99) WITHIN GROUP (
                    ORDER BY latency_minutes
                )::numeric,
                2
            ) AS p99_latency_minutes,
            ROUND(MAX(latency_minutes)::numeric, 2) AS max_latency_minutes,
            COUNT(*) FILTER (
                WHERE latency_minutes <= 10
            ) AS jobs_within_slo,
            ROUND(
                100.0 * COUNT(*) FILTER (
                    WHERE latency_minutes <= 10
                ) / NULLIF(COUNT(*), 0),
                2
            ) AS slo_compliance_pct
        FROM completed_jobs
    ),
    pending_stats AS (
        SELECT COUNT(*) AS pending_count,
            ROUND(MAX(pending_minutes)::numeric, 2) AS oldest_pending_minutes,
            ROUND(AVG(pending_minutes)::numeric, 2) AS avg_pending_minutes
        FROM pending_jobs
    ),
    processing_stats AS (
        SELECT COUNT(*) AS processing_count,
            ROUND(MAX(processing_minutes)::numeric, 2) AS longest_processing_minutes
        FROM processing_jobs
    )
SELECT -- Latency metrics
    COALESCE(ls.total_completed_24h, 0) AS total_completed_24h,
    COALESCE(ls.avg_latency_minutes, 0) AS avg_latency_minutes,
    COALESCE(ls.p50_latency_minutes, 0) AS p50_latency_minutes,
    COALESCE(ls.p95_latency_minutes, 0) AS p95_latency_minutes,
    COALESCE(ls.p99_latency_minutes, 0) AS p99_latency_minutes,
    COALESCE(ls.max_latency_minutes, 0) AS max_latency_minutes,
    COALESCE(ls.jobs_within_slo, 0) AS jobs_within_slo,
    COALESCE(ls.slo_compliance_pct, 100) AS slo_compliance_pct,
    -- Current queue state
    COALESCE(ps.pending_count, 0) AS pending_count,
    COALESCE(ps.oldest_pending_minutes, 0) AS oldest_pending_minutes,
    COALESCE(ps.avg_pending_minutes, 0) AS avg_pending_minutes,
    -- Processing state
    COALESCE(prs.processing_count, 0) AS processing_count,
    COALESCE(prs.longest_processing_minutes, 0) AS longest_processing_minutes,
    -- SLO status
    CASE
        WHEN COALESCE(ls.p95_latency_minutes, 0) <= 10 THEN 'HEALTHY'
        WHEN COALESCE(ls.p95_latency_minutes, 0) <= 15 THEN 'WARNING'
        ELSE 'BREACH'
    END AS slo_status,
    NOW() AS measured_at
FROM latency_stats ls
    CROSS JOIN pending_stats ps
    CROSS JOIN processing_stats prs;
COMMENT ON VIEW ops.view_slo_processing_freshness IS 'SLO: Processing Freshness - 95% of jobs within 10 minutes. Shows latency percentiles and queue state.';
-- ============================================================================
-- 2. ops.view_slo_error_budget
-- Tracks failure rate and DLQ metrics
-- ============================================================================
CREATE OR REPLACE VIEW ops.view_slo_error_budget AS WITH daily_stats AS (
        SELECT COUNT(*) AS total_jobs_24h,
            COUNT(*) FILTER (
                WHERE status = 'completed'
            ) AS completed_jobs_24h,
            COUNT(*) FILTER (
                WHERE status = 'failed'
            ) AS failed_jobs_24h,
            COUNT(*) FILTER (
                WHERE status = 'pending'
            ) AS pending_jobs_24h,
            COUNT(*) FILTER (
                WHERE status = 'processing'
            ) AS processing_jobs_24h
        FROM ops.job_queue
        WHERE created_at >= NOW() - INTERVAL '24 hours'
    ),
    dlq_stats AS (
        -- Jobs that exceeded max retries (true DLQ)
        SELECT COUNT(*) AS dlq_count_24h,
            COUNT(*) FILTER (
                WHERE updated_at >= NOW() - INTERVAL '1 hour'
            ) AS dlq_count_1h
        FROM ops.job_queue
        WHERE status = 'failed'
            AND attempts >= COALESCE(max_attempts, 3)
            AND updated_at >= NOW() - INTERVAL '24 hours'
    ),
    hourly_trend AS (
        -- Failure rate in the last hour
        SELECT COUNT(*) AS total_1h,
            COUNT(*) FILTER (
                WHERE status = 'failed'
            ) AS failed_1h
        FROM ops.job_queue
        WHERE created_at >= NOW() - INTERVAL '1 hour'
    ),
    reap_stats AS (
        -- Jobs recovered by reaper
        SELECT COUNT(*) AS reaped_24h,
            SUM(reap_count) AS total_reap_count_24h
        FROM ops.job_queue
        WHERE reap_count > 0
            AND updated_at >= NOW() - INTERVAL '24 hours'
    )
SELECT -- Volume
    COALESCE(ds.total_jobs_24h, 0) AS total_jobs_24h,
    COALESCE(ds.completed_jobs_24h, 0) AS completed_jobs_24h,
    COALESCE(ds.failed_jobs_24h, 0) AS failed_jobs_24h,
    COALESCE(ds.pending_jobs_24h, 0) AS pending_jobs_24h,
    COALESCE(ds.processing_jobs_24h, 0) AS processing_jobs_24h,
    -- Failure rate
    ROUND(
        100.0 * COALESCE(ds.failed_jobs_24h, 0) / NULLIF(ds.total_jobs_24h, 0),
        3
    ) AS failure_rate_percent,
    -- DLQ metrics
    COALESCE(dlq.dlq_count_24h, 0) AS dlq_count_24h,
    COALESCE(dlq.dlq_count_1h, 0) AS dlq_count_1h,
    ROUND(
        100.0 * COALESCE(dlq.dlq_count_24h, 0) / NULLIF(ds.total_jobs_24h, 0),
        3
    ) AS dlq_rate_percent,
    -- Hourly trend
    COALESCE(ht.total_1h, 0) AS total_jobs_1h,
    COALESCE(ht.failed_1h, 0) AS failed_jobs_1h,
    ROUND(
        100.0 * COALESCE(ht.failed_1h, 0) / NULLIF(ht.total_1h, 0),
        3
    ) AS failure_rate_1h_percent,
    -- Reaper activity
    COALESCE(rs.reaped_24h, 0) AS jobs_reaped_24h,
    COALESCE(rs.total_reap_count_24h, 0) AS total_reap_events_24h,
    -- SLO status (DLQ < 1%)
    CASE
        WHEN COALESCE(
            100.0 * dlq.dlq_count_24h / NULLIF(ds.total_jobs_24h, 0),
            0
        ) < 0.5 THEN 'HEALTHY'
        WHEN COALESCE(
            100.0 * dlq.dlq_count_24h / NULLIF(ds.total_jobs_24h, 0),
            0
        ) < 1.0 THEN 'WARNING'
        ELSE 'BREACH'
    END AS slo_status,
    -- Error budget remaining (1% budget = 100 basis points)
    GREATEST(
        0,
        100 - ROUND(
            100.0 * COALESCE(dlq.dlq_count_24h, 0) / NULLIF(ds.total_jobs_24h, 0) * 100,
            0
        )
    ) AS error_budget_remaining_bps,
    NOW() AS measured_at
FROM daily_stats ds
    CROSS JOIN dlq_stats dlq
    CROSS JOIN hourly_trend ht
    CROSS JOIN reap_stats rs;
COMMENT ON VIEW ops.view_slo_error_budget IS 'SLO: Data Quality - DLQ growth < 1% of total volume. Shows failure rates and error budget.';
-- ============================================================================
-- 3. ops.view_slo_active_workers
-- Tracks worker health and activity
-- ============================================================================
CREATE OR REPLACE VIEW ops.view_slo_active_workers AS
SELECT worker_id,
    worker_type,
    status,
    last_seen_at,
    EXTRACT(
        EPOCH
        FROM (NOW() - last_seen_at)
    ) / 60 AS minutes_since_heartbeat,
    CASE
        WHEN last_seen_at >= NOW() - INTERVAL '2 minutes' THEN 'ACTIVE'
        WHEN last_seen_at >= NOW() - INTERVAL '5 minutes' THEN 'STALE'
        ELSE 'DEAD'
    END AS health_status
FROM ops.worker_heartbeats
WHERE last_seen_at >= NOW() - INTERVAL '1 hour'
ORDER BY last_seen_at DESC;
COMMENT ON VIEW ops.view_slo_active_workers IS 'Worker health status: ACTIVE (<2min), STALE (2-5min), DEAD (>5min since heartbeat).';
-- ============================================================================
-- 4. ops.view_slo_system_health (CEO Dashboard)
-- Single-row system health summary
-- ============================================================================
CREATE OR REPLACE VIEW ops.view_slo_system_health AS WITH freshness AS (
        SELECT *
        FROM ops.view_slo_processing_freshness
    ),
    error_budget AS (
        SELECT *
        FROM ops.view_slo_error_budget
    ),
    worker_summary AS (
        SELECT COUNT(*) FILTER (
                WHERE health_status = 'ACTIVE'
            ) AS active_workers,
            COUNT(*) FILTER (
                WHERE health_status = 'STALE'
            ) AS stale_workers,
            COUNT(*) FILTER (
                WHERE health_status = 'DEAD'
            ) AS dead_workers,
            COUNT(*) AS total_workers
        FROM ops.view_slo_active_workers
    ),
    stuck_jobs AS (
        SELECT COUNT(*) AS stuck_count
        FROM ops.job_queue
        WHERE status = 'processing'
            AND started_at < NOW() - INTERVAL '30 minutes'
    )
SELECT -- Queue health
    f.pending_count AS queue_depth,
    f.processing_count,
    f.oldest_pending_minutes,
    -- Latency SLO
    f.p95_latency_minutes,
    10.0 AS p95_latency_target,
    f.slo_compliance_pct AS freshness_slo_pct,
    f.slo_status AS freshness_slo_status,
    -- Error rate SLO
    e.failure_rate_percent AS error_rate_pct,
    1.0 AS error_rate_target,
    e.dlq_rate_percent,
    e.slo_status AS error_budget_slo_status,
    e.error_budget_remaining_bps,
    -- Volume
    e.total_jobs_24h,
    e.completed_jobs_24h,
    e.failed_jobs_24h,
    -- Workers
    ws.active_workers,
    ws.stale_workers,
    ws.dead_workers,
    ws.total_workers,
    -- Stuck jobs
    sj.stuck_count AS stuck_jobs,
    -- Reaper health
    e.jobs_reaped_24h,
    -- Overall status
    CASE
        WHEN f.slo_status = 'BREACH'
        OR e.slo_status = 'BREACH'
        OR sj.stuck_count > 0 THEN 'CRITICAL'
        WHEN f.slo_status = 'WARNING'
        OR e.slo_status = 'WARNING'
        OR ws.dead_workers > 0 THEN 'WARNING'
        ELSE 'HEALTHY'
    END AS overall_status,
    NOW() AS measured_at
FROM freshness f
    CROSS JOIN error_budget e
    CROSS JOIN worker_summary ws
    CROSS JOIN stuck_jobs sj;
COMMENT ON VIEW ops.view_slo_system_health IS 'CEO Dashboard: Single-row system health summary with all SLO metrics.';
-- ============================================================================
-- 5. Grant permissions
-- ============================================================================
GRANT SELECT ON ops.view_slo_processing_freshness TO service_role;
GRANT SELECT ON ops.view_slo_processing_freshness TO postgres;
GRANT SELECT ON ops.view_slo_error_budget TO service_role;
GRANT SELECT ON ops.view_slo_error_budget TO postgres;
GRANT SELECT ON ops.view_slo_active_workers TO service_role;
GRANT SELECT ON ops.view_slo_active_workers TO postgres;
GRANT SELECT ON ops.view_slo_system_health TO service_role;
GRANT SELECT ON ops.view_slo_system_health TO postgres;
-- ============================================================================
-- 6. Verification
-- ============================================================================
DO $$
DECLARE v_view_count INTEGER;
BEGIN
SELECT COUNT(*) INTO v_view_count
FROM pg_views
WHERE schemaname = 'ops'
    AND viewname IN (
        'view_slo_processing_freshness',
        'view_slo_error_budget',
        'view_slo_active_workers',
        'view_slo_system_health'
    );
IF v_view_count < 4 THEN RAISE EXCEPTION 'MIGRATION FAILED: Expected 4 SLO views, found %',
v_view_count;
END IF;
RAISE NOTICE '[OK] SLO Observability views created: % views',
v_view_count;
END $$;
COMMIT;
-- Notify PostgREST to reload schema
NOTIFY pgrst,
'reload schema';