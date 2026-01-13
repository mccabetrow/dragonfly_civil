-- 20260110_lock_ops.sql
-- Ops Schema Lockdown: Inaccessible to anon/authenticated, visible to service_role
-- ===========================================================================
BEGIN;
-- ===========================================================================
-- STEP 1: Revoke all access from public/anon/authenticated
-- ===========================================================================
REVOKE ALL ON SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL ROUTINES IN SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
-- ===========================================================================
-- STEP 2: Grant service_role full access
-- ===========================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ops TO service_role;
-- ===========================================================================
-- STEP 3: Alter default privileges to prevent future leaks
-- ===========================================================================
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON TABLES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON ROUTINES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON SEQUENCES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON ROUTINES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON SEQUENCES TO service_role;
-- ===========================================================================
-- STEP 4: Secure RPC for dashboard stats (SECURITY DEFINER)
-- Returns JSON with worker heartbeats, queue depths, and API status
-- Allows service_role to fetch system health without direct table access
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_system_health() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE result jsonb;
worker_heartbeats jsonb;
queue_depths jsonb;
api_status jsonb;
BEGIN -- Worker Heartbeats (last 5 minutes)
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
-- Queue Depths
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
-- API Status
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
-- Combine all
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
-- STEP 5: Lock the RPC to service_role only
-- ===========================================================================
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM PUBLIC,
    anon,
    authenticated;
GRANT EXECUTE ON FUNCTION ops.get_system_health() TO service_role;
COMMIT;
-- ===========================================================================
-- VERIFICATION (run with service_role key):
--   SELECT * FROM ops.get_system_health();
-- Should FAIL with anon or authenticated roles.
-- ===========================================================================