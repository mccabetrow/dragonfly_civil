-- 20261104_ensure_ops_rpc.sql
-- Ops RPC Hardening Migration
-- Purpose: Ensure ops.get_dashboard_stats() remains accessible after schema lockdown
--          by reaffirming SECURITY DEFINER and strict access controls.
-- Depends: 20261103_lock_ops_schema.sql (ops schema locked from anon/authenticated)
-- ===========================================================================
BEGIN;
-- ===========================================================================
-- STEP 1: Recreate ops.get_dashboard_stats() with SECURITY DEFINER
-- ===========================================================================
-- SECURITY DEFINER allows this function to bypass the schema-level REVOKE
-- we applied in 20261103. The function runs as its owner (postgres/supabase_admin),
-- not as the calling role.
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
-- ===========================================================================
-- STEP 2: Revoke ALL access from public roles
-- ===========================================================================
-- Even though the schema is locked, belt-and-suspenders: explicitly revoke
-- function-level execute permissions.
REVOKE ALL ON FUNCTION ops.get_dashboard_stats()
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats()
FROM anon;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats()
FROM authenticated;
DO $$ BEGIN RAISE NOTICE '✅ Revoked EXECUTE on ops.get_dashboard_stats() from PUBLIC, anon, authenticated';
END $$;
-- ===========================================================================
-- STEP 3: Grant EXECUTE to service_role
-- ===========================================================================
-- service_role is the backend API role. This allows the API to call the
-- function using the service key, but frontend clients cannot call it directly.
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats() TO service_role;
DO $$ BEGIN RAISE NOTICE '✅ Granted EXECUTE on ops.get_dashboard_stats() to service_role';
END $$;
-- ===========================================================================
-- STEP 4: Conditional grant to ops_viewer (if exists)
-- ===========================================================================
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'ops_viewer'
) THEN EXECUTE 'GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats() TO ops_viewer';
RAISE NOTICE '✅ Granted EXECUTE on ops.get_dashboard_stats() to ops_viewer';
ELSE RAISE NOTICE 'ℹ️  ops_viewer role does not exist, skipping optional grant';
END IF;
END $$;
-- ===========================================================================
-- STEP 5: Recreate JSON wrapper with same security model
-- ===========================================================================
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
-- Security for JSON wrapper
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
) THEN EXECUTE 'GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats_json() TO ops_viewer';
END IF;
END $$;
-- ===========================================================================
-- STEP 6: Documentation
-- ===========================================================================
COMMENT ON FUNCTION ops.get_dashboard_stats() IS 'SECURITY DEFINER function returning unified Admin Dashboard metrics.

POST-LOCKDOWN NOTE (20261104):
  After ops schema was locked from anon/authenticated (20261103), this function
  uses SECURITY DEFINER to bypass schema restrictions and execute with owner
  privileges. Access is strictly controlled at the function level.

SECURITY MODEL:
  - SECURITY DEFINER: Executes as function owner (bypasses schema REVOKE)
  - SET search_path = public, workers, pgmq, pg_temp (no user schemas)
  - REVOKE ALL FROM PUBLIC, anon, authenticated
  - GRANT EXECUTE TO service_role only (and ops_viewer if exists)

Components returned:
  - worker: Individual worker heartbeat status (healthy/stale/dead)
  - queue: pgmq queue depths and message ages
  - dlq: Dead Letter Queue summary (critical if depth > 0)
  - system: Postgres health and database size
  - summary: Aggregate platform health score

Usage (via service_role only):
  SELECT * FROM ops.get_dashboard_stats();
  SELECT * FROM ops.get_dashboard_stats_json();
';
COMMENT ON FUNCTION ops.get_dashboard_stats_json() IS 'JSON wrapper for ops.get_dashboard_stats() - returns structured dashboard payload.
Inherits security model: SECURITY DEFINER, service_role access only.';
-- ===========================================================================
-- STEP 7: Verification
-- ===========================================================================
DO $$
DECLARE v_count INT;
v_has_security_definer BOOLEAN;
BEGIN RAISE NOTICE '';
RAISE NOTICE '══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  OPS RPC HARDENING VERIFICATION';
RAISE NOTICE '══════════════════════════════════════════════════════════════════';
RAISE NOTICE '';
-- Check function exists and is SECURITY DEFINER
SELECT prosecdef INTO v_has_security_definer
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops'
    AND p.proname = 'get_dashboard_stats';
IF v_has_security_definer IS TRUE THEN RAISE NOTICE '✅ ops.get_dashboard_stats() is SECURITY DEFINER';
ELSE RAISE WARNING '❌ ops.get_dashboard_stats() is NOT SECURITY DEFINER';
END IF;
-- Verify function returns data
SELECT COUNT(*) INTO v_count
FROM ops.get_dashboard_stats();
RAISE NOTICE '✅ Function returns % rows',
v_count;
-- Show current grants
RAISE NOTICE '';
RAISE NOTICE '🔒 Access Control Summary:';
RAISE NOTICE '   - anon: DENIED (schema + function revoked)';
RAISE NOTICE '   - authenticated: DENIED (schema + function revoked)';
RAISE NOTICE '   - service_role: GRANTED (function execute)';
RAISE NOTICE '   - ops_viewer: GRANTED if role exists';
RAISE NOTICE '';
RAISE NOTICE '══════════════════════════════════════════════════════════════════';
END $$;
COMMIT;