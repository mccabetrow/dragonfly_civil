-- ============================================================================
-- Migration: ops.get_dashboard_stats() RPC Refactor
-- Purpose:   Convert Security Definer View to Security Definer Function
-- Author:    Principal Database Architect
-- Date:      2026-10-02
-- ============================================================================
-- RATIONALE:
-- Supabase Security Advisor flags SECURITY DEFINER views as risky because they
-- bypass RLS using the owner's permissions. The correct pattern for admin
-- dashboards that need elevated access is a SECURITY DEFINER *function* with:
--   1. Explicit REVOKE ALL FROM PUBLIC
--   2. Strict SET search_path (no user-controlled schemas)
--   3. GRANT EXECUTE only to specific trusted roles
-- ============================================================================
-- ============================================================================
-- STEP 1: Drop the existing view and function (if they exist with different signatures)
-- ============================================================================
DROP VIEW IF EXISTS ops.v_dashboard_stats CASCADE;
DROP FUNCTION IF EXISTS ops.get_dashboard_stats() CASCADE;
DROP FUNCTION IF EXISTS ops.get_dashboard_stats_json() CASCADE;
-- ============================================================================
-- STEP 2: Create the SECURITY DEFINER function with strict search_path
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.get_dashboard_stats() RETURNS TABLE (
        component TEXT,
        name TEXT,
        status TEXT,
        metric_1 NUMERIC,
        metric_2 NUMERIC,
        meta JSONB
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    workers,
    pgmq,
    pg_temp AS $$ BEGIN RETURN QUERY -- ────────────────────────────────────────────────────────────────────────
    -- WORKERS: Health status based on heartbeat age
    -- ────────────────────────────────────────────────────────────────────────
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
    h.jobs_processed::numeric AS metric_2,
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
-- ────────────────────────────────────────────────────────────────────────
-- QUEUES: Depth and age metrics from pgmq
-- ────────────────────────────────────────────────────────────────────────
SELECT 'queue'::text AS component,
    m.queue_name AS name,
    CASE
        WHEN m.queue_name = 'q_dead_letter'
        AND m.queue_length > 0 THEN 'critical'
        WHEN COALESCE(m.oldest_msg_age_sec, 0) > 300 THEN 'stale'
        WHEN m.queue_length > 1000 THEN 'warning'
        ELSE 'ok'
    END AS status,
    m.queue_length::numeric AS metric_1,
    COALESCE(m.oldest_msg_age_sec, 0)::numeric AS metric_2,
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
-- ────────────────────────────────────────────────────────────────────────
-- DLQ SUMMARY: Aggregate DLQ stats for quick dashboard reference
-- ────────────────────────────────────────────────────────────────────────
SELECT 'dlq'::text AS component,
    'q_dead_letter'::text AS name,
    CASE
        WHEN COALESCE(dlq.queue_length, 0) > 0 THEN 'critical'
        ELSE 'ok'
    END AS status,
    COALESCE(dlq.queue_length, 0)::numeric AS metric_1,
    COALESCE(dlq.oldest_msg_age_sec, 0)::numeric AS metric_2,
    jsonb_build_object(
        'total_failed',
        dlq.total_messages,
        'requires_attention',
        dlq.queue_length > 0
    ) AS meta
FROM pgmq.metrics('q_dead_letter') dlq
UNION ALL
-- ────────────────────────────────────────────────────────────────────────
-- SYSTEM: Database health check
-- ────────────────────────────────────────────────────────────────────────
SELECT 'system'::text AS component,
    'postgres'::text AS name,
    'healthy'::text AS status,
    (
        SELECT COUNT(*)
        FROM pg_stat_activity
        WHERE state = 'active'
    )::numeric AS metric_1,
    (
        SELECT EXTRACT(
                EPOCH
                FROM (NOW() - pg_postmaster_start_time())
            )
    )::numeric AS metric_2,
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
-- ────────────────────────────────────────────────────────────────────────
-- SYSTEM: Database size
-- ────────────────────────────────────────────────────────────────────────
SELECT 'system'::text AS component,
    'database_size'::text AS name,
    'ok'::text AS status,
    pg_database_size(current_database())::numeric AS metric_1,
    ROUND(
        pg_database_size(current_database()) / 1024.0 / 1024.0,
        2
    )::numeric AS metric_2,
    jsonb_build_object(
        'database_name',
        current_database(),
        'size_human',
        pg_size_pretty(pg_database_size(current_database()))
    ) AS meta
UNION ALL
-- ────────────────────────────────────────────────────────────────────────
-- SUMMARY: Aggregate health score
-- ────────────────────────────────────────────────────────────────────────
SELECT 'summary'::text AS component,
    'platform_health'::text AS name,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM workers.heartbeats
            WHERE EXTRACT(
                    EPOCH
                    FROM (NOW() - last_heartbeat_at)
                ) > 300
        ) THEN 'critical'
        WHEN (
            SELECT queue_length
            FROM pgmq.metrics('q_dead_letter')
        ) > 0 THEN 'critical'
        WHEN EXISTS (
            SELECT 1
            FROM workers.heartbeats
            WHERE EXTRACT(
                    EPOCH
                    FROM (NOW() - last_heartbeat_at)
                ) > 90
        ) THEN 'warning'
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
    (
        SELECT COALESCE(SUM(queue_length), 0)
        FROM pgmq.metrics_all()
    )::numeric AS metric_2,
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
END;
$$;
-- ============================================================================
-- STEP 3: SECURITY - Strict access control
-- ============================================================================
-- Revoke all access from public and common roles
REVOKE ALL ON FUNCTION ops.get_dashboard_stats()
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats()
FROM anon;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats()
FROM authenticated;
-- Grant to service_role (backend API calls)
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats() TO service_role;
-- Grant to ops_viewer if role exists (optional admin role)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'ops_viewer'
) THEN
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats() TO ops_viewer;
RAISE NOTICE 'Granted EXECUTE on ops.get_dashboard_stats() to ops_viewer';
END IF;
END;
$$;
-- ============================================================================
-- STEP 4: COMMENTS
-- ============================================================================
COMMENT ON FUNCTION ops.get_dashboard_stats() IS 'SECURITY DEFINER function returning unified Admin Dashboard metrics.

SECURITY MODEL:
  - SECURITY DEFINER: Executes with owner privileges (bypasses RLS)
  - SET search_path = public, workers, pgmq, pg_temp (no user schemas)
  - Access restricted to service_role and ops_viewer only
  - PUBLIC, anon, authenticated explicitly revoked

Components returned:
  - worker: Individual worker heartbeat status (healthy/stale/dead)
  - queue: pgmq queue depths and message ages
  - dlq: Dead Letter Queue summary (critical if depth > 0)
  - system: Postgres health and database size
  - summary: Aggregate platform health score

Metrics:
  - metric_1: Primary metric (age_sec for workers, depth for queues)
  - metric_2: Secondary metric (jobs_processed, oldest_msg_age, uptime)

Usage:
  SELECT * FROM ops.get_dashboard_stats() WHERE component = ''worker'';
  SELECT * FROM ops.get_dashboard_stats() WHERE status IN (''critical'', ''warning'');
  SELECT * FROM ops.get_dashboard_stats() WHERE component = ''summary'';
';
-- ============================================================================
-- STEP 5: Recreate the aggregation function if it depends on the view
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.get_dashboard_stats_json() RETURNS JSONB LANGUAGE sql SECURITY DEFINER
SET search_path = ops,
    public,
    workers,
    pgmq,
    pg_temp AS $$
SELECT jsonb_build_object(
        'summary',
        (
            SELECT jsonb_agg(row_to_json(s))
            FROM ops.get_dashboard_stats() s
            WHERE s.component = 'summary'
        ),
        'workers',
        (
            SELECT jsonb_agg(row_to_json(w))
            FROM ops.get_dashboard_stats() w
            WHERE w.component = 'worker'
        ),
        'queues',
        (
            SELECT jsonb_agg(row_to_json(q))
            FROM ops.get_dashboard_stats() q
            WHERE q.component = 'queue'
        ),
        'dlq',
        (
            SELECT jsonb_agg(row_to_json(d))
            FROM ops.get_dashboard_stats() d
            WHERE d.component = 'dlq'
        ),
        'system',
        (
            SELECT jsonb_agg(row_to_json(s))
            FROM ops.get_dashboard_stats() s
            WHERE s.component = 'system'
        ),
        'generated_at',
        NOW()
    );
$$;
-- Security for JSON function
REVOKE ALL ON FUNCTION ops.get_dashboard_stats_json()
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats_json()
FROM anon;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats_json()
FROM authenticated;
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats_json() TO service_role;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'ops_viewer'
) THEN
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats_json() TO ops_viewer;
END IF;
END;
$$;
COMMENT ON FUNCTION ops.get_dashboard_stats_json() IS 'JSON wrapper for ops.get_dashboard_stats() - returns structured dashboard payload.
Inherits security model from ops.get_dashboard_stats().';
-- ============================================================================
-- VERIFICATION
-- ============================================================================
DO $$
DECLARE v_count INT;
BEGIN -- Verify function exists and returns data
SELECT COUNT(*) INTO v_count
FROM ops.get_dashboard_stats();
IF v_count > 0 THEN RAISE NOTICE 'ops.get_dashboard_stats() verified: % rows returned',
v_count;
ELSE RAISE WARNING 'ops.get_dashboard_stats() returned 0 rows - check data sources';
END IF;
-- Verify view is gone
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'ops'
        AND viewname = 'v_dashboard_stats'
) THEN RAISE WARNING 'View ops.v_dashboard_stats still exists - migration incomplete';
ELSE RAISE NOTICE 'View ops.v_dashboard_stats successfully dropped';
END IF;
END;
$$;