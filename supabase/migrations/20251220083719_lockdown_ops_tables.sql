-- ============================================================================
-- LOCKDOWN: ops.job_queue and ops.worker_heartbeats
-- ============================================================================
-- Purpose: Ensure dragonfly_app (frontend/API role) has NO direct access to
--          internal ops tables. Only service_role and postgres should touch them.
--
-- Access model:
--   postgres, service_role  → ALL (direct table access)
--   dragonfly_worker        → via SECURITY DEFINER RPCs only
--   dragonfly_app           → NO ACCESS (revoked)
--   authenticated, anon     → NO ACCESS (revoked)
--
-- Safety net: RLS enabled with deny-all policy for public roles
-- ============================================================================
BEGIN;
-- ============================================================================
-- STEP 1: REVOKE ALL from dangerous roles
-- ============================================================================
-- Revoke from authenticated (Supabase auth users)
REVOKE ALL PRIVILEGES ON ops.job_queue
FROM authenticated;
REVOKE ALL PRIVILEGES ON ops.worker_heartbeats
FROM authenticated;
-- Revoke from anon (unauthenticated requests)
REVOKE ALL PRIVILEGES ON ops.job_queue
FROM anon;
REVOKE ALL PRIVILEGES ON ops.worker_heartbeats
FROM anon;
-- Revoke from dragonfly_app (API/frontend role - should use RPCs only)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN REVOKE ALL PRIVILEGES ON ops.job_queue
FROM dragonfly_app;
REVOKE ALL PRIVILEGES ON ops.worker_heartbeats
FROM dragonfly_app;
RAISE NOTICE 'Revoked privileges from dragonfly_app on ops tables';
END IF;
END $$;
-- ============================================================================
-- STEP 2: GRANT ALL to privileged roles only
-- ============================================================================
-- postgres (superuser)
GRANT ALL PRIVILEGES ON ops.job_queue TO postgres;
GRANT ALL PRIVILEGES ON ops.worker_heartbeats TO postgres;
-- service_role (Supabase service role - used by backend workers)
GRANT ALL PRIVILEGES ON ops.job_queue TO service_role;
GRANT ALL PRIVILEGES ON ops.worker_heartbeats TO service_role;
-- dragonfly_worker (if exists) - for SECURITY DEFINER functions
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN -- Worker needs SELECT/UPDATE for job claiming via RPCs
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ops.job_queue TO dragonfly_worker;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats TO dragonfly_worker;
RAISE NOTICE 'Granted privileges to dragonfly_worker on ops tables';
END IF;
END $$;
-- ============================================================================
-- STEP 3: ENABLE RLS (safety net)
-- ============================================================================
-- Enable RLS on ops tables
ALTER TABLE ops.job_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.worker_heartbeats ENABLE ROW LEVEL SECURITY;
-- Force RLS for table owners too (extra paranoia)
ALTER TABLE ops.job_queue FORCE ROW LEVEL SECURITY;
ALTER TABLE ops.worker_heartbeats FORCE ROW LEVEL SECURITY;
-- ============================================================================
-- STEP 4: CREATE DENY-ALL POLICIES for public roles
-- ============================================================================
-- Drop any existing policies first
DROP POLICY IF EXISTS deny_authenticated_job_queue ON ops.job_queue;
DROP POLICY IF EXISTS deny_anon_job_queue ON ops.job_queue;
DROP POLICY IF EXISTS deny_dragonfly_app_job_queue ON ops.job_queue;
DROP POLICY IF EXISTS allow_service_role_job_queue ON ops.job_queue;
DROP POLICY IF EXISTS deny_authenticated_worker_heartbeats ON ops.worker_heartbeats;
DROP POLICY IF EXISTS deny_anon_worker_heartbeats ON ops.worker_heartbeats;
DROP POLICY IF EXISTS deny_dragonfly_app_worker_heartbeats ON ops.worker_heartbeats;
DROP POLICY IF EXISTS allow_service_role_worker_heartbeats ON ops.worker_heartbeats;
-- Allow service_role full access (bypass policy for privileged ops)
CREATE POLICY allow_service_role_job_queue ON ops.job_queue FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY allow_service_role_worker_heartbeats ON ops.worker_heartbeats FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Deny authenticated role (RLS enforced, no rows visible)
CREATE POLICY deny_authenticated_job_queue ON ops.job_queue FOR ALL TO authenticated USING (false) WITH CHECK (false);
CREATE POLICY deny_authenticated_worker_heartbeats ON ops.worker_heartbeats FOR ALL TO authenticated USING (false) WITH CHECK (false);
-- Deny anon role
CREATE POLICY deny_anon_job_queue ON ops.job_queue FOR ALL TO anon USING (false) WITH CHECK (false);
CREATE POLICY deny_anon_worker_heartbeats ON ops.worker_heartbeats FOR ALL TO anon USING (false) WITH CHECK (false);
-- ============================================================================
-- STEP 5: VERIFICATION QUERY (run after migration)
-- ============================================================================
-- Execute this to verify the lockdown is in place:
--
-- SELECT
--     schemaname,
--     tablename,
--     rowsecurity AS rls_enabled,
--     (SELECT string_agg(grantee || ':' || privilege_type, ', ')
--      FROM information_schema.table_privileges tp
--      WHERE tp.table_schema = t.schemaname AND tp.table_name = t.tablename
--      AND tp.grantee NOT IN ('postgres', 'service_role', 'dragonfly_worker')
--     ) AS dangerous_grants
-- FROM pg_tables t
-- WHERE schemaname = 'ops' AND tablename IN ('job_queue', 'worker_heartbeats');
--
-- Expected: rls_enabled = true, dangerous_grants = NULL
COMMIT;
-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE ops.job_queue IS 'Internal worker job queue. Access: service_role, postgres, dragonfly_worker only. RLS enforced.';
COMMENT ON TABLE ops.worker_heartbeats IS 'Worker health tracking. Access: service_role, postgres, dragonfly_worker only. RLS enforced.';
