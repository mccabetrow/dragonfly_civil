-- 20260112_lock_ops_schema.sql
-- Ops Schema Lockdown: Strictly private, accessible only to service_role
-- ===========================================================================
-- 
-- SECURITY CONTEXT:
-- The ops schema contains internal operational data:
--   - Worker heartbeats
--   - Run/job history
--   - Alert thresholds
--   - System health metrics
--
-- This schema must NEVER be exposed to anon, authenticated, or public roles.
-- Only service_role (backend workers, internal APIs) may access it.
--
-- ===========================================================================
BEGIN;
-- ===========================================================================
-- STEP 1: REVOKE ALL ACCESS FROM PUBLIC ROLES
-- ===========================================================================
-- Deny access to the schema itself (no USAGE = no visibility)
REVOKE ALL ON SCHEMA ops
FROM public,
    anon,
    authenticated;
-- Deny access to all tables (defense in depth)
REVOKE ALL ON ALL TABLES IN SCHEMA ops
FROM public,
    anon,
    authenticated;
-- Deny access to all routines/functions (prevents RPC abuse)
REVOKE ALL ON ALL ROUTINES IN SCHEMA ops
FROM public,
    anon,
    authenticated;
-- Deny access to all sequences
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops
FROM public,
    anon,
    authenticated;
-- ===========================================================================
-- STEP 2: GRANT SERVICE_ROLE FULL ACCESS
-- ===========================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ops TO service_role;
-- ===========================================================================
-- STEP 3: ALTER DEFAULT PRIVILEGES (prevent future leaks)
-- ===========================================================================
-- Any new objects created in ops will automatically be locked down
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON TABLES
FROM public,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON ROUTINES
FROM public,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON SEQUENCES
FROM public,
    anon,
    authenticated;
-- Service role gets full access to future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON ROUTINES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON SEQUENCES TO service_role;
-- ===========================================================================
-- STEP 4: SECURITY DEFINER RPC - ops.get_system_health()
-- ===========================================================================
-- Returns JSON with worker heartbeats, queue depths, and overall status.
-- SECURITY DEFINER allows service_role to call this without direct table grants.
-- Explicit search_path prevents search_path injection attacks.
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_system_health() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE result jsonb;
worker_heartbeats jsonb;
queue_depths jsonb;
api_status jsonb;
BEGIN -- -------------------------------------------------------------------------
-- Worker Heartbeats (last 10 minutes)
-- -------------------------------------------------------------------------
SELECT COALESCE(
        jsonb_agg(
            jsonb_build_object(
                'worker_id',
                worker_id,
                'worker_type',
                worker_type,
                'last_heartbeat',
                last_heartbeat_at,
                'status',
                CASE
                    WHEN last_heartbeat_at >= NOW() - INTERVAL '2 minutes' THEN 'healthy'
                    WHEN last_heartbeat_at >= NOW() - INTERVAL '5 minutes' THEN 'stale'
                    ELSE 'dead'
                END
            )
        ),
        '[]'::jsonb
    ) INTO worker_heartbeats
FROM ops.heartbeats
WHERE last_heartbeat_at >= NOW() - INTERVAL '10 minutes';
-- -------------------------------------------------------------------------
-- Queue Depths (operational metrics)
-- -------------------------------------------------------------------------
SELECT jsonb_build_object(
        'pending_intake_jobs',
        (
            SELECT COUNT(*)
            FROM public.intake_jobs
            WHERE status IN ('pending', 'processing')
        ),
        'failed_runs_24h',
        (
            SELECT COUNT(*)
            FROM ops.runs
            WHERE status = 'failed'
                AND started_at >= NOW() - INTERVAL '24 hours'
        ),
        'pending_enforcement',
        (
            SELECT COUNT(*)
            FROM public.judgments
            WHERE pipeline_stage = 'pending_enforcement'
        )
    ) INTO queue_depths;
-- -------------------------------------------------------------------------
-- API Status (application health)
-- -------------------------------------------------------------------------
SELECT jsonb_build_object(
        'database_connected',
        true,
        'active_plaintiffs',
        (
            SELECT COUNT(*)
            FROM public.plaintiffs
            WHERE current_status NOT IN ('rejected', 'closed', 'completed')
        ),
        'judgments_in_enforcement',
        (
            SELECT COUNT(*)
            FROM public.judgments
            WHERE pipeline_stage = 'enforcement'
        ),
        'checked_at',
        NOW()
    ) INTO api_status;
-- -------------------------------------------------------------------------
-- Combine all metrics + compute overall status
-- -------------------------------------------------------------------------
result := jsonb_build_object(
    'worker_heartbeats',
    worker_heartbeats,
    'queue_depths',
    queue_depths,
    'api_status',
    api_status,
    'overall_status',
    CASE
        WHEN (queue_depths->>'failed_runs_24h')::int > 10 THEN 'critical'
        WHEN (queue_depths->>'pending_intake_jobs')::int > 500 THEN 'critical'
        WHEN (queue_depths->>'failed_runs_24h')::int > 3 THEN 'warning'
        WHEN (queue_depths->>'pending_intake_jobs')::int > 100 THEN 'warning'
        ELSE 'healthy'
    END
);
RETURN result;
END;
$$;
-- ===========================================================================
-- STEP 5: LOCK THE RPC TO SERVICE_ROLE ONLY
-- ===========================================================================
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM public,
    anon,
    authenticated;
GRANT EXECUTE ON FUNCTION ops.get_system_health() TO service_role;
COMMIT;
-- ===========================================================================
-- VERIFICATION (run with service_role key):
--   SELECT ops.get_system_health();
--
-- Should FAIL with anon or authenticated roles:
--   ERROR: permission denied for schema ops
-- ===========================================================================