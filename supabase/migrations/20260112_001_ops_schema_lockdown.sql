-- =============================================================================
-- 20260112_001_ops_schema_lockdown.sql
-- Lock ops schema: service_role only, no public/anon/authenticated access
-- =============================================================================
--
-- DESIGN PRINCIPLES:
-- 1. Fully idempotent - safe to run multiple times
-- 2. Uses pg_catalog checks before attempting changes
-- 3. Revokes all public access, grants only to service_role
-- 4. Creates/updates ops.get_system_health() with proper security
-- 5. No assumptions about column existence
--
-- =============================================================================
BEGIN;
-- ===========================================================================
-- STEP 1: Ensure ops schema exists
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS ops;
COMMENT ON SCHEMA ops IS 'Private operational schema - service_role access only. Contains system health, worker status, and audit data.';
DO $$ BEGIN RAISE NOTICE '✓ ops schema exists';
END $$;
-- ===========================================================================
-- STEP 2: Revoke all access from public, anon, authenticated
-- ===========================================================================
-- Revoke schema usage
REVOKE ALL ON SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON SCHEMA ops
FROM anon;
REVOKE ALL ON SCHEMA ops
FROM authenticated;
-- Revoke on all tables (dynamic - handles any table set)
DO $$
DECLARE v_table record;
BEGIN FOR v_table IN
SELECT tablename
FROM pg_catalog.pg_tables
WHERE schemaname = 'ops' LOOP EXECUTE format(
        'REVOKE ALL ON ops.%I FROM PUBLIC',
        v_table.tablename
    );
EXECUTE format(
    'REVOKE ALL ON ops.%I FROM anon',
    v_table.tablename
);
EXECUTE format(
    'REVOKE ALL ON ops.%I FROM authenticated',
    v_table.tablename
);
RAISE NOTICE '  Revoked access on ops.%',
v_table.tablename;
END LOOP;
END $$;
-- Revoke on all functions
DO $$
DECLARE v_func record;
v_full_sig text;
BEGIN FOR v_func IN
SELECT p.proname,
    pg_get_function_identity_arguments(p.oid) AS args
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops' LOOP v_full_sig := format('ops.%I(%s)', v_func.proname, v_func.args);
BEGIN EXECUTE format(
    'REVOKE ALL ON FUNCTION %s FROM PUBLIC',
    v_full_sig
);
EXECUTE format(
    'REVOKE ALL ON FUNCTION %s FROM anon',
    v_full_sig
);
EXECUTE format(
    'REVOKE ALL ON FUNCTION %s FROM authenticated',
    v_full_sig
);
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Could not revoke on %: %',
v_full_sig,
SQLERRM;
END;
END LOOP;
END $$;
-- Revoke on all sequences
DO $$
DECLARE v_seq record;
BEGIN FOR v_seq IN
SELECT sequencename
FROM pg_catalog.pg_sequences
WHERE schemaname = 'ops' LOOP EXECUTE format(
        'REVOKE ALL ON SEQUENCE ops.%I FROM PUBLIC',
        v_seq.sequencename
    );
EXECUTE format(
    'REVOKE ALL ON SEQUENCE ops.%I FROM anon',
    v_seq.sequencename
);
EXECUTE format(
    'REVOKE ALL ON SEQUENCE ops.%I FROM authenticated',
    v_seq.sequencename
);
END LOOP;
END $$;
DO $$ BEGIN RAISE NOTICE '✓ Revoked all public/anon/authenticated access from ops schema';
END $$;
-- ===========================================================================
-- STEP 3: Grant service_role full access
-- ===========================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA ops TO service_role;
-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON FUNCTIONS TO service_role;
DO $$ BEGIN RAISE NOTICE '✓ Granted service_role full access to ops schema';
END $$;
-- ===========================================================================
-- STEP 4: Create ops.system_health table if not exists
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ops.system_health (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    check_name text NOT NULL,
    status text NOT NULL CHECK (status IN ('healthy', 'degraded', 'unhealthy')),
    details jsonb DEFAULT '{}',
    checked_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT unique_health_check UNIQUE (check_name)
);
CREATE INDEX IF NOT EXISTS idx_system_health_checked_at ON ops.system_health (checked_at DESC);
COMMENT ON TABLE ops.system_health IS 'Current system health status - updated by workers and health checks.';
-- ===========================================================================
-- STEP 5: Create ops.worker_heartbeat table if not exists
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ops.worker_heartbeat (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id text NOT NULL,
    worker_type text NOT NULL,
    last_heartbeat timestamptz NOT NULL DEFAULT now(),
    metadata jsonb DEFAULT '{}',
    CONSTRAINT unique_worker UNIQUE (worker_id)
);
CREATE INDEX IF NOT EXISTS idx_worker_heartbeat_type ON ops.worker_heartbeat (worker_type);
CREATE INDEX IF NOT EXISTS idx_worker_heartbeat_time ON ops.worker_heartbeat (last_heartbeat DESC);
COMMENT ON TABLE ops.worker_heartbeat IS 'Worker liveness tracking - workers update on each poll cycle.';
-- ===========================================================================
-- STEP 6: Create ops.audit_log table if not exists
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ops.audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type text NOT NULL,
    actor text,
    target_table text,
    target_id uuid,
    old_values jsonb,
    new_values jsonb,
    metadata jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_audit_log_time ON ops.audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_log_event ON ops.audit_log (event_type);
CREATE INDEX IF NOT EXISTS idx_audit_log_target ON ops.audit_log (target_table, target_id);
COMMENT ON TABLE ops.audit_log IS 'Immutable audit trail for significant system events.';
-- ===========================================================================
-- STEP 7: Create/Replace ops.get_system_health() with proper security
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_system_health() RETURNS TABLE (
        check_name text,
        status text,
        details jsonb,
        checked_at timestamptz,
        age_seconds numeric
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    pg_catalog AS $$ BEGIN RETURN QUERY
SELECT h.check_name,
    h.status,
    h.details,
    h.checked_at,
    EXTRACT(
        EPOCH
        FROM (now() - h.checked_at)
    )::numeric AS age_seconds
FROM ops.system_health h
ORDER BY h.checked_at DESC;
END;
$$;
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM anon;
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM authenticated;
GRANT EXECUTE ON FUNCTION ops.get_system_health() TO service_role;
COMMENT ON FUNCTION ops.get_system_health IS 'Returns current system health status. SECURITY DEFINER to allow RPC calls from dashboard.';
-- ===========================================================================
-- STEP 8: Create/Replace ops.get_worker_status() with proper security
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_worker_status() RETURNS TABLE (
        worker_id text,
        worker_type text,
        last_heartbeat timestamptz,
        age_seconds numeric,
        is_stale boolean,
        metadata jsonb
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    pg_catalog AS $$ BEGIN RETURN QUERY
SELECT w.worker_id,
    w.worker_type,
    w.last_heartbeat,
    EXTRACT(
        EPOCH
        FROM (now() - w.last_heartbeat)
    )::numeric AS age_seconds,
    (now() - w.last_heartbeat) > interval '5 minutes' AS is_stale,
    w.metadata
FROM ops.worker_heartbeat w
ORDER BY w.last_heartbeat DESC;
END;
$$;
REVOKE ALL ON FUNCTION ops.get_worker_status()
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_worker_status()
FROM anon;
REVOKE ALL ON FUNCTION ops.get_worker_status()
FROM authenticated;
GRANT EXECUTE ON FUNCTION ops.get_worker_status() TO service_role;
COMMENT ON FUNCTION ops.get_worker_status IS 'Returns current worker heartbeat status. SECURITY DEFINER to allow RPC calls from dashboard.';
-- ===========================================================================
-- STEP 9: Create/Replace ops.get_recent_audit_events() with proper security
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_recent_audit_events(
        p_limit integer DEFAULT 100,
        p_event_type text DEFAULT NULL
    ) RETURNS TABLE (
        id uuid,
        event_type text,
        actor text,
        target_table text,
        target_id uuid,
        metadata jsonb,
        created_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    pg_catalog AS $$ BEGIN RETURN QUERY
SELECT a.id,
    a.event_type,
    a.actor,
    a.target_table,
    a.target_id,
    a.metadata,
    a.created_at
FROM ops.audit_log a
WHERE (
        p_event_type IS NULL
        OR a.event_type = p_event_type
    )
ORDER BY a.created_at DESC
LIMIT p_limit;
END;
$$;
REVOKE ALL ON FUNCTION ops.get_recent_audit_events(integer, text)
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_recent_audit_events(integer, text)
FROM anon;
REVOKE ALL ON FUNCTION ops.get_recent_audit_events(integer, text)
FROM authenticated;
GRANT EXECUTE ON FUNCTION ops.get_recent_audit_events(integer, text) TO service_role;
COMMENT ON FUNCTION ops.get_recent_audit_events IS 'Returns recent audit events. SECURITY DEFINER to allow RPC calls from dashboard.';
-- ===========================================================================
-- STEP 10: Create/Replace ops.get_dashboard_stats_json() for unified dashboard
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_dashboard_stats_json() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public,
    pg_catalog AS $$
DECLARE v_result jsonb;
v_health_status text;
v_worker_count integer;
v_stale_workers integer;
BEGIN -- Get overall health status
SELECT CASE
        WHEN COUNT(*) FILTER (
            WHERE status = 'unhealthy'
        ) > 0 THEN 'unhealthy'
        WHEN COUNT(*) FILTER (
            WHERE status = 'degraded'
        ) > 0 THEN 'degraded'
        ELSE 'healthy'
    END INTO v_health_status
FROM ops.system_health;
-- Get worker stats
SELECT COUNT(*),
    COUNT(*) FILTER (
        WHERE (now() - last_heartbeat) > interval '5 minutes'
    ) INTO v_worker_count,
    v_stale_workers
FROM ops.worker_heartbeat;
v_result := jsonb_build_object(
    'health_status',
    COALESCE(v_health_status, 'unknown'),
    'worker_count',
    v_worker_count,
    'stale_workers',
    v_stale_workers,
    'generated_at',
    now()
);
RETURN v_result;
END;
$$;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats_json()
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats_json()
FROM anon;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats_json()
FROM authenticated;
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats_json() TO service_role;
COMMENT ON FUNCTION ops.get_dashboard_stats_json IS 'Returns unified dashboard statistics as JSON. SECURITY DEFINER for cross-schema access.';
-- ===========================================================================
-- STEP 11: Verification query (commented out for migration safety)
-- ===========================================================================
DO $$ BEGIN RAISE NOTICE '✓ ops schema lockdown complete';
RAISE NOTICE '  - All public/anon/authenticated access revoked';
RAISE NOTICE '  - service_role has full access';
RAISE NOTICE '  - RPC functions created with SECURITY DEFINER + SET search_path';
END $$;
-- ===========================================================================
-- STEP 12: Reload PostgREST schema cache
-- ===========================================================================
DO $$ BEGIN PERFORM pg_notify('pgrst', 'reload schema');
RAISE NOTICE '✓ Notified PostgREST to reload schema cache';
END $$;
COMMIT;
-- ===========================================================================
-- VERIFICATION (run after migration)
-- ===========================================================================
/*
 -- Check grants on ops schema
 SELECT 
 nspname AS schema,
 pg_catalog.has_schema_privilege('anon', nspname, 'USAGE') AS anon_usage,
 pg_catalog.has_schema_privilege('authenticated', nspname, 'USAGE') AS auth_usage,
 pg_catalog.has_schema_privilege('service_role', nspname, 'USAGE') AS service_usage
 FROM pg_namespace
 WHERE nspname = 'ops';
 
 -- Check table grants
 SELECT 
 schemaname,
 tablename,
 privilege_type,
 grantee
 FROM information_schema.table_privileges
 WHERE table_schema = 'ops'
 ORDER BY tablename, grantee;
 
 -- Test RPC functions
 SELECT * FROM ops.get_system_health();
 SELECT * FROM ops.get_worker_status();
 SELECT * FROM ops.get_dashboard_stats_json();
 */