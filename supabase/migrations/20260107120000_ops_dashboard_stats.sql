-- ============================================================================
-- Migration: ops.v_dashboard_stats
-- Purpose:   Unified Admin Dashboard view for system observability
-- Author:    Principal Database Architect
-- Date:      2026-01-07
-- ============================================================================
-- Create ops schema if not exists
CREATE SCHEMA IF NOT EXISTS ops;
-- ============================================================================
-- VIEW: ops.v_dashboard_stats
-- Consolidates worker health, queue depths, and system status into one query
-- ============================================================================
CREATE OR REPLACE VIEW ops.v_dashboard_stats AS -- ────────────────────────────────────────────────────────────────────────────
    -- WORKERS: Health status based on heartbeat age
    -- ────────────────────────────────────────────────────────────────────────────
SELECT 'worker'::text AS component,
    h.queue_name AS name,
    CASE
        WHEN EXTRACT(
            EPOCH
            FROM (NOW() - h.last_heartbeat_at)
        ) > 300 THEN 'dead'
        WHEN EXTRACT(
            EPOCH
            FROM (NOW() - h.last_heartbeat_at)
        ) > 90 THEN 'stale'
        ELSE 'healthy'
    END AS status,
    ROUND(
        EXTRACT(
            EPOCH
            FROM (NOW() - h.last_heartbeat_at)
        )
    )::numeric AS metric_1,
    -- heartbeat_age_sec
    h.jobs_processed::numeric AS metric_2,
    -- total jobs processed
    jsonb_build_object(
        'worker_id',
        h.worker_id,
        'hostname',
        h.hostname,
        'pid',
        h.pid,
        'status',
        h.status,
        'jobs_failed',
        h.jobs_failed,
        'last_heartbeat_at',
        h.last_heartbeat_at
    ) AS meta
FROM workers.heartbeats h
UNION ALL
-- ────────────────────────────────────────────────────────────────────────────
-- QUEUES: Depth and age metrics from pgmq
-- ────────────────────────────────────────────────────────────────────────────
SELECT 'queue'::text AS component,
    m.queue_name AS name,
    CASE
        -- DLQ with messages is critical
        WHEN m.queue_name = 'q_dead_letter'
        AND m.queue_length > 0 THEN 'critical' -- Any queue with oldest message > 5 min is stale
        WHEN COALESCE(m.oldest_msg_age_sec, 0) > 300 THEN 'stale' -- Queue depth > 1000 is warning
        WHEN m.queue_length > 1000 THEN 'warning'
        ELSE 'ok'
    END AS status,
    m.queue_length::numeric AS metric_1,
    -- depth
    COALESCE(m.oldest_msg_age_sec, 0)::numeric AS metric_2,
    -- oldest_msg_age_sec
    jsonb_build_object(
        'newest_msg_age_sec',
        m.newest_msg_age_sec,
        'total_messages',
        m.total_messages,
        'scrape_time',
        m.scrape_time
    ) AS meta
FROM pgmq.metrics_all() m
UNION ALL
-- ────────────────────────────────────────────────────────────────────────────
-- DLQ SUMMARY: Aggregate DLQ stats for quick dashboard reference
-- ────────────────────────────────────────────────────────────────────────────
SELECT 'dlq'::text AS component,
    'q_dead_letter'::text AS name,
    CASE
        WHEN COALESCE(m.queue_length, 0) > 0 THEN 'critical'
        ELSE 'ok'
    END AS status,
    COALESCE(m.queue_length, 0)::numeric AS metric_1,
    -- dlq_depth
    COALESCE(m.oldest_msg_age_sec, 0)::numeric AS metric_2,
    -- oldest_failed_job_age_sec
    jsonb_build_object(
        'total_failed',
        m.total_messages,
        'requires_attention',
        m.queue_length > 0
    ) AS meta
FROM pgmq.metrics('q_dead_letter') m
UNION ALL
-- ────────────────────────────────────────────────────────────────────────────
-- SYSTEM: Database health check
-- ────────────────────────────────────────────────────────────────────────────
SELECT 'system'::text AS component,
    'postgres'::text AS name,
    'healthy'::text AS status,
    (
        SELECT COUNT(*)
        FROM pg_stat_activity
        WHERE state = 'active'
    )::numeric AS metric_1,
    -- active_connections
    (
        SELECT EXTRACT(
                EPOCH
                FROM (NOW() - pg_postmaster_start_time())
            )
    )::numeric AS metric_2,
    -- uptime_sec
    jsonb_build_object(
        'version',
        version(),
        'max_connections',
        current_setting('max_connections'),
        'current_connections',
        (
            SELECT COUNT(*)
            FROM pg_stat_activity
        ),
        'postmaster_start',
        pg_postmaster_start_time()
    ) AS meta
UNION ALL
-- ────────────────────────────────────────────────────────────────────────────
-- SYSTEM: Database size
-- ────────────────────────────────────────────────────────────────────────────
SELECT 'system'::text AS component,
    'database_size'::text AS name,
    'ok'::text AS status,
    pg_database_size(current_database())::numeric AS metric_1,
    -- size_bytes
    ROUND(
        pg_database_size(current_database()) / 1024.0 / 1024.0,
        2
    )::numeric AS metric_2,
    -- size_mb
    jsonb_build_object(
        'database_name',
        current_database(),
        'size_human',
        pg_size_pretty(pg_database_size(current_database()))
    ) AS meta
UNION ALL
-- ────────────────────────────────────────────────────────────────────────────
-- SUMMARY: Aggregate health score
-- ────────────────────────────────────────────────────────────────────────────
SELECT 'summary'::text AS component,
    'platform_health'::text AS name,
    CASE
        -- Any dead workers = critical
        WHEN EXISTS (
            SELECT 1
            FROM workers.heartbeats
            WHERE EXTRACT(
                    EPOCH
                    FROM (NOW() - last_heartbeat_at)
                ) > 300
        ) THEN 'critical' -- DLQ has messages = critical
        WHEN (
            SELECT queue_length
            FROM pgmq.metrics('q_dead_letter')
        ) > 0 THEN 'critical' -- Any stale workers = warning
        WHEN EXISTS (
            SELECT 1
            FROM workers.heartbeats
            WHERE EXTRACT(
                    EPOCH
                    FROM (NOW() - last_heartbeat_at)
                ) > 90
        ) THEN 'warning' -- Any queue traffic jam = warning
        WHEN EXISTS (
            SELECT 1
            FROM pgmq.metrics_all()
            WHERE oldest_msg_age_sec > 300
        ) THEN 'warning'
        ELSE 'healthy'
    END AS status,
    (
        SELECT COUNT(*)
        FROM workers.heartbeats
        WHERE EXTRACT(
                EPOCH
                FROM (NOW() - last_heartbeat_at)
            ) <= 90
    )::numeric AS metric_1,
    -- healthy_workers
    (
        SELECT COALESCE(SUM(queue_length), 0)
        FROM pgmq.metrics_all()
    )::numeric AS metric_2,
    -- total_queue_depth
    jsonb_build_object(
        'dead_workers',
        (
            SELECT COUNT(*)
            FROM workers.heartbeats
            WHERE EXTRACT(
                    EPOCH
                    FROM (NOW() - last_heartbeat_at)
                ) > 300
        ),
        'stale_workers',
        (
            SELECT COUNT(*)
            FROM workers.heartbeats
            WHERE EXTRACT(
                    EPOCH
                    FROM (NOW() - last_heartbeat_at)
                ) BETWEEN 90 AND 300
        ),
        'dlq_depth',
        (
            SELECT queue_length
            FROM pgmq.metrics('q_dead_letter')
        ),
        'queues_with_traffic_jam',
        (
            SELECT COUNT(*)
            FROM pgmq.metrics_all()
            WHERE oldest_msg_age_sec > 300
        ),
        'checked_at',
        NOW()
    ) AS meta;
-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON VIEW ops.v_dashboard_stats IS 'Unified Admin Dashboard view consolidating worker health, queue metrics, and system status.

Components:
  - worker: Individual worker heartbeat status (healthy/stale/dead)
  - queue: pgmq queue depths and message ages
  - dlq: Dead Letter Queue summary (critical if depth > 0)
  - system: Postgres health and database size
  - summary: Aggregate platform health score

Metrics:
  - metric_1: Primary metric (age_sec for workers, depth for queues, connections for system)
  - metric_2: Secondary metric (jobs_processed, oldest_msg_age, uptime)

Status Values:
  - healthy: All good
  - ok: Normal operation
  - warning: Attention needed soon
  - stale: Worker heartbeat > 90s
  - dead: Worker heartbeat > 300s
  - critical: Immediate attention required (DLQ has messages, dead workers)

Usage:
  SELECT * FROM ops.v_dashboard_stats WHERE component = ''worker'';
  SELECT * FROM ops.v_dashboard_stats WHERE status IN (''critical'', ''warning'');
  SELECT * FROM ops.v_dashboard_stats WHERE component = ''summary'';
';
-- ============================================================================
-- SECURITY: Grant access to appropriate roles
-- ============================================================================
-- Service role (for API backend)
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT SELECT ON ops.v_dashboard_stats TO service_role;
-- Authenticated users with dashboard access (if using RLS)
GRANT USAGE ON SCHEMA ops TO authenticated;
GRANT SELECT ON ops.v_dashboard_stats TO authenticated;
-- Create ops_viewer role if it doesn't exist and grant access
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'ops_viewer'
) THEN
GRANT USAGE ON SCHEMA ops TO ops_viewer;
GRANT SELECT ON ops.v_dashboard_stats TO ops_viewer;
END IF;
END $$;
-- ============================================================================
-- HELPER FUNCTION: Get dashboard stats as JSON
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.get_dashboard_stats() RETURNS jsonb LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = ops,
    public,
    pg_temp AS $$
SELECT jsonb_build_object(
        'generated_at',
        NOW(),
        'summary',
        (
            SELECT row_to_json(s.*)
            FROM ops.v_dashboard_stats s
            WHERE component = 'summary'
            LIMIT 1
        ), 'workers', (
            SELECT jsonb_agg(row_to_json(w.*))
            FROM ops.v_dashboard_stats w
            WHERE component = 'worker'
        ),
        'queues',
        (
            SELECT jsonb_agg(row_to_json(q.*))
            FROM ops.v_dashboard_stats q
            WHERE component = 'queue'
        ),
        'dlq',
        (
            SELECT row_to_json(d.*)
            FROM ops.v_dashboard_stats d
            WHERE component = 'dlq'
            LIMIT 1
        ), 'system', (
            SELECT jsonb_agg(row_to_json(s.*))
            FROM ops.v_dashboard_stats s
            WHERE component = 'system'
        )
    );
$$;
COMMENT ON FUNCTION ops.get_dashboard_stats() IS 'Returns all dashboard stats as a structured JSON object for API consumption.';
-- Grant execute to service_role
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats() TO service_role;
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats() TO authenticated;
-- ============================================================================
-- DONE
-- ============================================================================