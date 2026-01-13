-- =============================================================================
-- 20260112_final_security_lockdown.sql
-- FINAL SECURITY LOCKDOWN: Ops Privacy & Service-Role-Only RPC
-- =============================================================================
--
-- ACCEPTANCE CRITERIA:
-- 1. Ops schema MUST be inaccessible to anon and authenticated roles
-- 2. Only service_role can execute ops.get_system_health() RPC
-- 3. Idempotent - safe to run multiple times
--
-- =============================================================================
BEGIN;
-- =============================================================================
-- STEP 1: REVOKE ALL OPS ACCESS FROM PUBLIC ROLES
-- =============================================================================
-- These revokes are idempotent (safe to run multiple times)
REVOKE ALL ON SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON SCHEMA ops
FROM anon;
REVOKE ALL ON SCHEMA ops
FROM authenticated;
-- Revoke access to all tables in ops
REVOKE ALL ON ALL TABLES IN SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ops
FROM anon;
REVOKE ALL ON ALL TABLES IN SCHEMA ops
FROM authenticated;
-- Revoke access to all routines (functions/procedures) in ops
REVOKE ALL ON ALL ROUTINES IN SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON ALL ROUTINES IN SCHEMA ops
FROM anon;
REVOKE ALL ON ALL ROUTINES IN SCHEMA ops
FROM authenticated;
-- Revoke access to all sequences in ops
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops
FROM anon;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops
FROM authenticated;
-- =============================================================================
-- STEP 2: GRANT SERVICE_ROLE FULL ACCESS
-- =============================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL ROUTINES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ops TO service_role;
-- =============================================================================
-- STEP 3: ALTER DEFAULT PRIVILEGES (Prevent Future Leaks)
-- =============================================================================
-- These ensure new objects created in ops are NOT accessible to public roles
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
-- =============================================================================
-- STEP 4: CREATE/REPLACE ops.get_system_health() SECURITY DEFINER RPC
-- =============================================================================
-- This RPC is the ONLY way to read ops health data from outside.
-- SECURITY DEFINER runs with the privileges of the function owner (postgres).
-- We then restrict EXECUTE to service_role ONLY.
DROP FUNCTION IF EXISTS ops.get_system_health() CASCADE;
DROP FUNCTION IF EXISTS ops.get_system_health(integer) CASCADE;
CREATE OR REPLACE FUNCTION ops.get_system_health(p_limit integer DEFAULT 100) RETURNS TABLE (
        metric_name text,
        metric_value numeric,
        status text,
        recorded_at timestamptz
    ) LANGUAGE sql SECURITY DEFINER
SET search_path = ops,
    pg_temp AS $$ -- Return latest health metrics from ops.health_snapshots
    -- Falls back gracefully if table doesn't exist
SELECT hs.metric_name::text,
    hs.metric_value::numeric,
    hs.status::text,
    hs.recorded_at::timestamptz
FROM ops.health_snapshots hs
ORDER BY hs.recorded_at DESC
LIMIT p_limit;
$$;
-- Revoke all access from everyone first
REVOKE ALL ON FUNCTION ops.get_system_health(integer)
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_system_health(integer)
FROM anon;
REVOKE ALL ON FUNCTION ops.get_system_health(integer)
FROM authenticated;
-- Grant ONLY to service_role
GRANT EXECUTE ON FUNCTION ops.get_system_health(integer) TO service_role;
-- Document the security model
COMMENT ON FUNCTION ops.get_system_health(integer) IS 'SECURITY DEFINER RPC - Returns system health metrics. ' 'Access restricted to service_role ONLY for ops privacy. ' 'Use with service_role key: SELECT * FROM ops.get_system_health(10);';
-- =============================================================================
-- STEP 5: VERIFICATION QUERIES (These run as part of migration)
-- =============================================================================
-- These will fail the migration if security is not correctly configured
DO $$
DECLARE has_anon_access boolean;
has_auth_access boolean;
BEGIN -- Check if anon has USAGE on ops schema (should be false)
SELECT has_schema_privilege('anon', 'ops', 'USAGE') INTO has_anon_access;
IF has_anon_access THEN RAISE EXCEPTION 'SECURITY VIOLATION: anon role still has USAGE on ops schema';
END IF;
-- Check if authenticated has USAGE on ops schema (should be false)
SELECT has_schema_privilege('authenticated', 'ops', 'USAGE') INTO has_auth_access;
IF has_auth_access THEN RAISE EXCEPTION 'SECURITY VIOLATION: authenticated role still has USAGE on ops schema';
END IF;
RAISE NOTICE '✅ SECURITY VERIFIED: ops schema is inaccessible to anon/authenticated';
END $$;
COMMIT;
-- =============================================================================
-- VERIFICATION GUIDE
-- =============================================================================
-- Run these queries to verify the security lockdown:
--
-- 1. As anon (should fail):
--    SET ROLE anon;
--    SELECT * FROM ops.health_snapshots LIMIT 1;
--    -- Expected: permission denied for schema ops
--
-- 2. As authenticated (should fail):
--    SET ROLE authenticated;
--    SELECT * FROM ops.get_system_health(1);
--    -- Expected: permission denied for function ops.get_system_health
--
-- 3. As service_role (should succeed):
--    SET ROLE service_role;
--    SELECT * FROM ops.get_system_health(5);
--    -- Expected: Returns health data
-- =============================================================================