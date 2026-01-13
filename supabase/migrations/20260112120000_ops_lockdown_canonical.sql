-- =============================================================================
-- 20260112_ops_lockdown_canonical.sql
-- Canonical ops schema lockdown - FULLY IDEMPOTENT
-- =============================================================================
--
-- DESIGN PRINCIPLES:
-- 1. Every statement is rerunnable without errors
-- 2. All RAISE NOTICE wrapped in DO blocks (required by PostgreSQL)
-- 3. REVOKE ALL + SECURITY DEFINER RPC pattern
-- 4. Only service_role can access ops schema
-- 5. Dashboard reads via SECURITY DEFINER functions
--
-- Safe to run on fresh database OR existing database with partial state.
--
-- =============================================================================
BEGIN;
-- ===========================================================================
-- STEP 1: Create schema if missing
-- ===========================================================================
CREATE SCHEMA IF NOT EXISTS ops;
COMMENT ON SCHEMA ops IS 'Operations schema - internal system health, audit trails, and platform metrics. Access via SECURITY DEFINER RPCs only.';
-- ===========================================================================
-- STEP 2: Core ops tables (IF NOT EXISTS for all)
-- ===========================================================================
-- 2a. System health snapshots
CREATE TABLE IF NOT EXISTS ops.health_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    snapshot_time timestamptz NOT NULL DEFAULT now(),
    component text NOT NULL,
    status text NOT NULL CHECK (status IN ('healthy', 'degraded', 'unhealthy')),
    latency_ms integer,
    error_message text,
    metadata jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Guard health_snapshots indexes
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'health_snapshots'
        AND column_name = 'snapshot_time'
) THEN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ops'
        AND indexname = 'idx_health_snapshots_time'
) THEN CREATE INDEX idx_health_snapshots_time ON ops.health_snapshots (snapshot_time DESC);
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ops'
        AND indexname = 'idx_health_snapshots_component'
) THEN CREATE INDEX idx_health_snapshots_component ON ops.health_snapshots (component, snapshot_time DESC);
END IF;
END IF;
END $$;
-- 2b. Worker heartbeats
CREATE TABLE IF NOT EXISTS ops.worker_heartbeats (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    worker_id text NOT NULL UNIQUE,
    worker_type text NOT NULL,
    last_heartbeat timestamptz NOT NULL DEFAULT now(),
    status text NOT NULL DEFAULT 'active',
    metadata jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Guard index creation on column existence
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'worker_heartbeats'
        AND column_name = 'last_heartbeat'
) THEN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ops'
        AND tablename = 'worker_heartbeats'
        AND indexname = 'idx_worker_heartbeats_type'
) THEN CREATE INDEX idx_worker_heartbeats_type ON ops.worker_heartbeats (worker_type, last_heartbeat DESC);
END IF;
END IF;
END $$;
-- 2c. Audit log
CREATE TABLE IF NOT EXISTS ops.audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event_time timestamptz NOT NULL DEFAULT now(),
    event_type text NOT NULL,
    actor text,
    target_table text,
    target_id text,
    old_values jsonb,
    new_values jsonb,
    metadata jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Guard audit_log indexes
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'audit_log'
        AND column_name = 'event_time'
) THEN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ops'
        AND indexname = 'idx_audit_log_time'
) THEN CREATE INDEX idx_audit_log_time ON ops.audit_log (event_time DESC);
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ops'
        AND indexname = 'idx_audit_log_type'
) THEN CREATE INDEX idx_audit_log_type ON ops.audit_log (event_type, event_time DESC);
END IF;
END IF;
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'audit_log'
        AND column_name = 'target_table'
) THEN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ops'
        AND indexname = 'idx_audit_log_target'
) THEN CREATE INDEX idx_audit_log_target ON ops.audit_log (target_table, target_id);
END IF;
END IF;
END $$;
-- 2d. Platform metrics aggregates
CREATE TABLE IF NOT EXISTS ops.platform_metrics (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    metric_time timestamptz NOT NULL DEFAULT now(),
    metric_name text NOT NULL,
    metric_value numeric NOT NULL,
    dimensions jsonb DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Guard platform_metrics index
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'platform_metrics'
        AND column_name = 'metric_time'
) THEN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'ops'
        AND indexname = 'idx_platform_metrics_name_time'
) THEN CREATE INDEX idx_platform_metrics_name_time ON ops.platform_metrics (metric_name, metric_time DESC);
END IF;
END IF;
END $$;
DO $$ BEGIN RAISE NOTICE '✓ ops tables verified/created';
END $$;
-- ===========================================================================
-- STEP 3: REVOKE ALL from public, anon, authenticated
-- ===========================================================================
REVOKE ALL ON SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL TABLES IN SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON ALL ROUTINES IN SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
DO $$ BEGIN RAISE NOTICE '✓ Revoked all public access to ops schema';
END $$;
-- ===========================================================================
-- STEP 4: Grant to service_role only
-- ===========================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA ops TO service_role;
GRANT EXECUTE ON ALL ROUTINES IN SCHEMA ops TO service_role;
DO $$ BEGIN RAISE NOTICE '✓ Granted full access to service_role';
END $$;
-- ===========================================================================
-- STEP 5: Set default privileges for future objects
-- ===========================================================================
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON TABLES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON SEQUENCES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON ROUTINES
FROM PUBLIC,
    anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT EXECUTE ON ROUTINES TO service_role;
-- ===========================================================================
-- STEP 6: SECURITY DEFINER RPC for dashboard health read
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_system_health(p_limit integer DEFAULT 100) RETURNS TABLE (
        id uuid,
        snapshot_time timestamptz,
        component text,
        status text,
        latency_ms integer,
        error_message text,
        metadata jsonb
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN RETURN QUERY
SELECT h.id,
    h.snapshot_time,
    h.component,
    h.status,
    h.latency_ms,
    h.error_message,
    h.metadata
FROM ops.health_snapshots h
ORDER BY h.snapshot_time DESC
LIMIT p_limit;
END;
$$;
-- Secure the function
REVOKE ALL ON FUNCTION ops.get_system_health(integer)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.get_system_health(integer) TO service_role;
GRANT EXECUTE ON FUNCTION ops.get_system_health(integer) TO authenticated;
COMMENT ON FUNCTION ops.get_system_health(integer) IS 'SECURITY DEFINER RPC - safe read-only access to health snapshots for dashboard.';
-- ===========================================================================
-- STEP 7: SECURITY DEFINER RPC for worker status
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_worker_status() RETURNS TABLE (
        worker_id text,
        worker_type text,
        last_heartbeat timestamptz,
        status text,
        is_stale boolean
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN RETURN QUERY
SELECT w.worker_id,
    w.worker_type,
    w.last_heartbeat,
    w.status,
    (w.last_heartbeat < now() - interval '5 minutes') AS is_stale
FROM ops.worker_heartbeats w
ORDER BY w.last_heartbeat DESC;
END;
$$;
REVOKE ALL ON FUNCTION ops.get_worker_status()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.get_worker_status() TO service_role;
GRANT EXECUTE ON FUNCTION ops.get_worker_status() TO authenticated;
COMMENT ON FUNCTION ops.get_worker_status() IS 'SECURITY DEFINER RPC - read-only worker heartbeat status for dashboard.';
-- ===========================================================================
-- STEP 8: SECURITY DEFINER RPC for dashboard stats JSON
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_dashboard_stats_json() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_result jsonb;
v_plaintiffs_total bigint;
v_plaintiffs_active bigint;
v_judgments_total bigint;
v_judgments_value numeric;
v_workers_active bigint;
v_health_status text;
BEGIN -- Plaintiff counts (from public schema)
SELECT COUNT(*),
    COUNT(*) FILTER (
        WHERE status NOT IN ('rejected', 'closed')
    ) INTO v_plaintiffs_total,
    v_plaintiffs_active
FROM public.plaintiffs;
-- Judgment counts (from public schema)
SELECT COUNT(*),
    COALESCE(SUM(total_judgment_amount), 0) INTO v_judgments_total,
    v_judgments_value
FROM public.judgments;
-- Active workers
SELECT COUNT(*) INTO v_workers_active
FROM ops.worker_heartbeats
WHERE last_heartbeat > now() - interval '5 minutes';
-- Latest health status
SELECT h.status INTO v_health_status
FROM ops.health_snapshots h
WHERE h.component = 'system'
ORDER BY h.snapshot_time DESC
LIMIT 1;
v_result := jsonb_build_object(
    'plaintiffs_total', v_plaintiffs_total, 'plaintiffs_active', v_plaintiffs_active, 'judgments_total', v_judgments_total, 'judgments_value', v_judgments_value, 'workers_active', v_workers_active, 'system_health', COALESCE(v_health_status, 'unknown'), 'generated_at', now()
);
RETURN v_result;
END;
$$;
REVOKE ALL ON FUNCTION ops.get_dashboard_stats_json()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats_json() TO service_role;
GRANT EXECUTE ON FUNCTION ops.get_dashboard_stats_json() TO authenticated;
COMMENT ON FUNCTION ops.get_dashboard_stats_json() IS 'SECURITY DEFINER RPC - aggregated dashboard stats from ops + public schemas.';
-- ===========================================================================
-- STEP 9: SECURITY DEFINER RPC for recent audit events
-- ===========================================================================
CREATE OR REPLACE FUNCTION ops.get_recent_audit_events(
        p_limit integer DEFAULT 50,
        p_event_type text DEFAULT NULL
    ) RETURNS TABLE (
        id uuid,
        event_time timestamptz,
        event_type text,
        actor text,
        target_table text,
        target_id text,
        metadata jsonb
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN RETURN QUERY
SELECT a.id,
    a.event_time,
    a.event_type,
    a.actor,
    a.target_table,
    a.target_id,
    a.metadata
FROM ops.audit_log a
WHERE (
        p_event_type IS NULL
        OR a.event_type = p_event_type
    )
ORDER BY a.event_time DESC
LIMIT p_limit;
END;
$$;
REVOKE ALL ON FUNCTION ops.get_recent_audit_events(integer, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.get_recent_audit_events(integer, text) TO service_role;
GRANT EXECUTE ON FUNCTION ops.get_recent_audit_events(integer, text) TO authenticated;
COMMENT ON FUNCTION ops.get_recent_audit_events(integer, text) IS 'SECURITY DEFINER RPC - paginated audit log access for dashboard.';
-- ===========================================================================
-- STEP 10: Enable RLS on all ops tables (belt and suspenders)
-- ===========================================================================
ALTER TABLE ops.health_snapshots ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.worker_heartbeats ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.platform_metrics ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.health_snapshots FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.worker_heartbeats FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.audit_log FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.platform_metrics FORCE ROW LEVEL SECURITY;
-- ===========================================================================
-- STEP 11: RLS policies - service_role only (drop first for idempotency)
-- ===========================================================================
DROP POLICY IF EXISTS health_snapshots_service_role ON ops.health_snapshots;
DROP POLICY IF EXISTS worker_heartbeats_service_role ON ops.worker_heartbeats;
DROP POLICY IF EXISTS audit_log_service_role ON ops.audit_log;
DROP POLICY IF EXISTS platform_metrics_service_role ON ops.platform_metrics;
CREATE POLICY health_snapshots_service_role ON ops.health_snapshots FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY worker_heartbeats_service_role ON ops.worker_heartbeats FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY audit_log_service_role ON ops.audit_log FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY platform_metrics_service_role ON ops.platform_metrics FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ===========================================================================
-- STEP 12: Reload PostgREST schema cache
-- ===========================================================================
DO $$ BEGIN PERFORM pg_notify('pgrst', 'reload schema');
RAISE NOTICE '✓ Notified PostgREST to reload schema cache';
END $$;
DO $$ BEGIN RAISE NOTICE '✓ ops schema lockdown complete';
RAISE NOTICE '  - All tables protected with RLS + service_role-only policies';
RAISE NOTICE '  - Dashboard access via SECURITY DEFINER RPCs only';
RAISE NOTICE '  - Public/anon/authenticated revoked from schema';
END $$;
COMMIT;
-- ===========================================================================
-- VERIFICATION QUERIES (run after migration)
-- ===========================================================================
/*
 -- Check schema grants
 SELECT nspname, nspacl FROM pg_namespace WHERE nspname = 'ops';
 
 -- Check table grants
 SELECT 
 schemaname,
 tablename,
 tableowner,
 hasindexes,
 hasrules,
 hastriggers,
 rowsecurity
 FROM pg_tables 
 WHERE schemaname = 'ops';
 
 -- Check RLS policies
 SELECT schemaname, tablename, policyname, permissive, roles, cmd
 FROM pg_policies 
 WHERE schemaname = 'ops';
 
 -- Check function security
 SELECT 
 routine_schema,
 routine_name,
 security_type
 FROM information_schema.routines 
 WHERE routine_schema = 'ops';
 
 -- Test dashboard RPC (should work for authenticated)
 SELECT * FROM ops.get_system_health(5);
 SELECT ops.get_dashboard_stats_json();
 */
-- ===========================================================================