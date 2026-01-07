-- =============================================================================
-- BREAK GLASS: Disable RLS on ops.* internal tables
-- =============================================================================
--
-- PURPOSE:
-- These are internal backend tables used by workers running with service_role.
-- RLS is NOT needed for these tables since they:
-- 1. Never expose data to end users (internal ops only)
-- 2. Are only accessed by backend services with service_role key
-- 3. Need unrestricted access for job claiming and heartbeat registration
--
-- SECURITY MODEL:
-- - ONLY postgres and service_role receive DML (INSERT/UPDATE/DELETE) privileges
-- - authenticated and anon roles receive SELECT-only (read for monitoring dashboards)
-- - All writes MUST go through SECURITY DEFINER RPCs
--
-- This migration:
-- 1. Disables RLS on internal ops tables
-- 2. REVOKES any dangerous grants from authenticated/anon
-- 3. Grants ALL to postgres/service_role only
-- 4. Grants SELECT-only to authenticated for dashboard visibility
-- 5. Verifies no dangerous grants remain
--
-- IDEMPOTENT: Safe to run multiple times
-- =============================================================================
BEGIN;
-- =============================================================================
-- 1. SCHEMA GRANTS (USAGE only - no CREATE)
-- =============================================================================
GRANT USAGE ON SCHEMA ops TO postgres,
    service_role;
GRANT USAGE ON SCHEMA ops TO authenticated;
-- Explicitly revoke CREATE from non-admin roles
REVOKE CREATE ON SCHEMA ops
FROM authenticated,
    anon;
-- =============================================================================
-- 2. DISABLE RLS ON OPS TABLES
-- =============================================================================
-- ops.job_queue - worker job processing
ALTER TABLE ops.job_queue DISABLE ROW LEVEL SECURITY;
-- ops.worker_heartbeats - worker health tracking
ALTER TABLE ops.worker_heartbeats DISABLE ROW LEVEL SECURITY;
-- ops.intake_logs - worker logging
ALTER TABLE IF EXISTS ops.intake_logs DISABLE ROW LEVEL SECURITY;
-- ops.ingest_batches - batch tracking
ALTER TABLE IF EXISTS ops.ingest_batches DISABLE ROW LEVEL SECURITY;
-- ops.import_errors - error tracking
ALTER TABLE IF EXISTS ops.import_errors DISABLE ROW LEVEL SECURITY;
-- ops.data_discrepancies - data quality tracking
ALTER TABLE IF EXISTS ops.data_discrepancies DISABLE ROW LEVEL SECURITY;
-- =============================================================================
-- 3. REVOKE ALL DANGEROUS GRANTS FROM authenticated/anon
-- =============================================================================
-- CRITICAL: Remove any INSERT/UPDATE/DELETE from authenticated/anon
-- This is the security fix - these roles should NEVER have write access
-- Revoke all DML from authenticated on all ops tables
REVOKE
INSERT,
    UPDATE,
    DELETE ON ALL TABLES IN SCHEMA ops
FROM authenticated;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ALL TABLES IN SCHEMA ops
FROM anon;
-- Explicit revokes on specific tables (belt and suspenders)
REVOKE
INSERT,
    UPDATE,
    DELETE ON TABLE ops.job_queue
FROM authenticated,
    anon;
REVOKE
INSERT,
    UPDATE,
    DELETE ON TABLE ops.worker_heartbeats
FROM authenticated,
    anon;
REVOKE
INSERT,
    UPDATE,
    DELETE ON TABLE ops.intake_logs
FROM authenticated,
    anon;
REVOKE
INSERT,
    UPDATE,
    DELETE ON TABLE ops.ingest_batches
FROM authenticated,
    anon;
-- Revoke from any tables that might exist
DO $$
DECLARE tbl RECORD;
BEGIN FOR tbl IN
SELECT tablename
FROM pg_tables
WHERE schemaname = 'ops' LOOP EXECUTE format(
        'REVOKE INSERT, UPDATE, DELETE ON TABLE ops.%I FROM authenticated, anon',
        tbl.tablename
    );
END LOOP;
END $$;
-- =============================================================================
-- 4. GRANT PRIVILEGES TO PRIVILEGED ROLES ONLY
-- =============================================================================
-- postgres and service_role get full DML access
-- job_queue
GRANT ALL ON TABLE ops.job_queue TO postgres;
GRANT ALL ON TABLE ops.job_queue TO service_role;
GRANT SELECT ON TABLE ops.job_queue TO authenticated;
-- Read-only for dashboards
-- worker_heartbeats
GRANT ALL ON TABLE ops.worker_heartbeats TO postgres;
GRANT ALL ON TABLE ops.worker_heartbeats TO service_role;
GRANT SELECT ON TABLE ops.worker_heartbeats TO authenticated;
-- Read-only for dashboards
-- intake_logs
GRANT ALL ON TABLE ops.intake_logs TO postgres;
GRANT ALL ON TABLE ops.intake_logs TO service_role;
GRANT SELECT ON TABLE ops.intake_logs TO authenticated;
-- Read-only for dashboards
-- ingest_batches
GRANT ALL ON TABLE ops.ingest_batches TO postgres;
GRANT ALL ON TABLE ops.ingest_batches TO service_role;
GRANT SELECT ON TABLE ops.ingest_batches TO authenticated;
-- Read-only for dashboards
-- import_errors (if exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'ops'
        AND tablename = 'import_errors'
) THEN EXECUTE 'GRANT ALL ON TABLE ops.import_errors TO postgres';
EXECUTE 'GRANT ALL ON TABLE ops.import_errors TO service_role';
EXECUTE 'GRANT SELECT ON TABLE ops.import_errors TO authenticated';
END IF;
END $$;
-- data_discrepancies (if exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'ops'
        AND tablename = 'data_discrepancies'
) THEN EXECUTE 'GRANT ALL ON TABLE ops.data_discrepancies TO postgres';
EXECUTE 'GRANT ALL ON TABLE ops.data_discrepancies TO service_role';
EXECUTE 'GRANT SELECT ON TABLE ops.data_discrepancies TO authenticated';
END IF;
END $$;
-- =============================================================================
-- 5. SEQUENCE GRANTS (privileged roles only)
-- =============================================================================
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA ops TO postgres,
    service_role;
-- authenticated can read sequences (for dashboard queries) but not modify
GRANT SELECT ON ALL SEQUENCES IN SCHEMA ops TO authenticated;
REVOKE USAGE ON ALL SEQUENCES IN SCHEMA ops
FROM authenticated,
    anon;
-- =============================================================================
-- 6. FUNCTION EXECUTE GRANTS
-- =============================================================================
-- All SECURITY DEFINER functions can be called by authenticated (the function
-- itself runs as postgres and controls what operations are performed)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO postgres,
    service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO authenticated;
-- =============================================================================
-- 7. VERIFICATION - Fail if dangerous grants exist
-- =============================================================================
DO $$
DECLARE dangerous_grant RECORD;
violation_count INTEGER := 0;
BEGIN -- Check for any INSERT/UPDATE/DELETE grants to authenticated or anon on ops tables
FOR dangerous_grant IN
SELECT grantee,
    table_name,
    privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
    AND grantee IN ('authenticated', 'anon')
    AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE') LOOP RAISE WARNING 'DANGEROUS GRANT: % has % on ops.%',
    dangerous_grant.grantee,
    dangerous_grant.privilege_type,
    dangerous_grant.table_name;
violation_count := violation_count + 1;
END LOOP;
IF violation_count > 0 THEN RAISE EXCEPTION 'SECURITY VIOLATION: % dangerous grants found on ops schema. Migration aborted.',
violation_count;
END IF;
RAISE NOTICE 'SECURITY CHECK PASSED: No dangerous grants to authenticated/anon on ops schema';
END $$;
-- =============================================================================
-- 8. FINAL VERIFICATION REPORT
-- =============================================================================
DO $$
DECLARE tbl RECORD;
BEGIN RAISE NOTICE '=== BREAK GLASS MIGRATION COMPLETE ===';
RAISE NOTICE 'RLS Status:';
FOR tbl IN
SELECT tablename,
    NOT relrowsecurity AS rls_disabled
FROM pg_tables t
    JOIN pg_class c ON c.relname = t.tablename
    JOIN pg_namespace n ON n.oid = c.relnamespace
    AND n.nspname = t.schemaname
WHERE t.schemaname = 'ops' LOOP RAISE NOTICE '  ops.%: RLS %',
    tbl.tablename,
    CASE
        WHEN tbl.rls_disabled THEN 'DISABLED'
        ELSE 'ENABLED'
    END;
END LOOP;
END $$;
COMMIT;
-- =============================================================================
-- POST-MIGRATION VERIFICATION QUERIES (run separately to confirm)
-- =============================================================================
-- 
-- 1. Check RLS is disabled:
-- SELECT tablename, rowsecurity 
-- FROM pg_tables 
-- WHERE schemaname = 'ops';
-- Expected: rowsecurity = false for all tables
--
-- 2. Check NO dangerous grants exist:
-- SELECT grantee, table_name, privilege_type
-- FROM information_schema.table_privileges
-- WHERE table_schema = 'ops'
--   AND grantee IN ('authenticated', 'anon')
--   AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE');
-- Expected: 0 rows
--
-- 3. Check service_role HAS write access:
-- SELECT grantee, table_name, privilege_type
-- FROM information_schema.table_privileges
-- WHERE table_schema = 'ops'
--   AND grantee = 'service_role'
--   AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE');
-- Expected: Multiple rows for each table
