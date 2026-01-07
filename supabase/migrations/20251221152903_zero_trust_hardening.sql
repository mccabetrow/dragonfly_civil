-- ============================================================================
-- Migration: Zero Trust Security Hardening
-- Created: 2025-12-21
-- Incident: INC-2025-12-21-01 (Incident Response Framework)
-- ============================================================================
--
-- PURPOSE:
-- This migration enforces "Zero Trust" / Least-Privilege for Supabase built-in
-- roles (authenticated, anon, public) which are exposed to API/client requests.
--
-- The existing dragonfly_* roles (dragonfly_app, dragonfly_worker, dragonfly_readonly)
-- are for backend service connections. This migration hardens the API-facing roles.
--
-- ROLE MODEL:
-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │  API-FACING ROLES (hardened by this migration):                        │
-- ├─────────────────────────────────────────────────────────────────────────┤
-- │  authenticated - Logged-in app users via Supabase Auth                 │
-- │                  ✓ EXECUTE on queue_job (submit work)                  │
-- │                  ✗ NO direct table access in ops/intake schemas        │
-- │                  ✗ NO claim_pending_job, reap_stuck_jobs (admin-only)  │
-- ├─────────────────────────────────────────────────────────────────────────┤
-- │  anon          - Unauthenticated API requests                          │
-- │                  ✗ NO access to ops/intake schemas                     │
-- ├─────────────────────────────────────────────────────────────────────────┤
-- │  public        - PostgreSQL pseudo-role (default grants)               │
-- │                  ✗ REVOKE ALL (no default inheritance)                 │
-- └─────────────────────────────────────────────────────────────────────────┘
--
-- INVARIANT:
-- Tests in tests/test_security_invariants.py verify these boundaries cannot
-- be bypassed. The gate_preflight.ps1 hard gate enforces this before deploy.
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. REVOKE ALL FROM PUBLIC/ANON/AUTHENTICATED ON OPS SCHEMA
-- ============================================================================
-- Nuclear option: remove all existing grants, then selectively re-grant
-- Revoke schema usage first
REVOKE ALL ON SCHEMA ops
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON SCHEMA intake
FROM PUBLIC,
    anon,
    authenticated;
-- Revoke all table privileges in ops
DO $$
DECLARE tbl RECORD;
BEGIN FOR tbl IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
    AND c.relkind IN ('r', 'v', 'm') LOOP EXECUTE format(
        'REVOKE ALL ON ops.%I FROM PUBLIC, anon, authenticated',
        tbl.relname
    );
END LOOP;
END $$;
-- Revoke all table privileges in intake
DO $$
DECLARE tbl RECORD;
BEGIN FOR tbl IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'intake'
    AND c.relkind IN ('r', 'v', 'm') LOOP EXECUTE format(
        'REVOKE ALL ON intake.%I FROM PUBLIC, anon, authenticated',
        tbl.relname
    );
END LOOP;
END $$;
-- Revoke all function privileges in ops
DO $$
DECLARE func RECORD;
BEGIN FOR func IN
SELECT p.proname,
    pg_get_function_identity_arguments(p.oid) as args
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops' LOOP BEGIN EXECUTE format(
        'REVOKE ALL ON FUNCTION ops.%I(%s) FROM PUBLIC, anon, authenticated',
        func.proname,
        func.args
    );
EXCEPTION
WHEN OTHERS THEN -- Some functions may have complex signatures, skip on error
NULL;
END;
END LOOP;
END $$;
-- ============================================================================
-- 2. GRANT MINIMAL SCHEMA USAGE
-- ============================================================================
-- authenticated can use ops schema (for allowed RPCs only)
GRANT USAGE ON SCHEMA ops TO authenticated;
-- anon gets NO ops access at all
-- (No GRANT statement = no access)
-- ============================================================================
-- 3. GRANT SPECIFIC RPC EXECUTE PERMISSIONS
-- ============================================================================
-- authenticated: Can queue jobs (submit work) but NOT claim or admin
DO $$ BEGIN -- queue_job: Submit new work to the queue
IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
        AND p.proname = 'queue_job'
) THEN
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO authenticated;
RAISE NOTICE 'GRANTED: ops.queue_job to authenticated';
END IF;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'SKIPPED: ops.queue_job (function not found)';
END $$;
-- queue_job_idempotent: Also safe for authenticated users
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
        AND p.proname = 'queue_job_idempotent'
) THEN
GRANT EXECUTE ON FUNCTION ops.queue_job_idempotent(TEXT, JSONB, TEXT, INTEGER, TIMESTAMPTZ) TO authenticated;
RAISE NOTICE 'GRANTED: ops.queue_job_idempotent to authenticated';
END IF;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'SKIPPED: ops.queue_job_idempotent (function not found)';
END $$;
-- Explicitly DO NOT grant to authenticated:
-- - ops.claim_pending_job (worker-only)
-- - ops.reap_stuck_jobs (admin-only)
-- - ops.update_job_status (worker-only)
-- - ops.register_heartbeat (worker-only)
-- These remain accessible only to dragonfly_worker and service_role
-- ============================================================================
-- 4. ENABLE RLS ON ALL OPS AND INTAKE TABLES
-- ============================================================================
-- Even though authenticated has no direct table access, enable RLS as defense-in-depth
DO $$
DECLARE tbl RECORD;
BEGIN -- Enable RLS on ops tables
FOR tbl IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
    AND c.relkind = 'r' LOOP EXECUTE format(
        'ALTER TABLE ops.%I ENABLE ROW LEVEL SECURITY',
        tbl.relname
    );
EXECUTE format(
    'ALTER TABLE ops.%I FORCE ROW LEVEL SECURITY',
    tbl.relname
);
RAISE NOTICE 'RLS FORCED on ops.%',
tbl.relname;
END LOOP;
-- Enable RLS on intake tables
FOR tbl IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'intake'
    AND c.relkind = 'r' LOOP EXECUTE format(
        'ALTER TABLE intake.%I ENABLE ROW LEVEL SECURITY',
        tbl.relname
    );
EXECUTE format(
    'ALTER TABLE intake.%I FORCE ROW LEVEL SECURITY',
    tbl.relname
);
RAISE NOTICE 'RLS FORCED on intake.%',
tbl.relname;
END LOOP;
END $$;
-- ============================================================================
-- 5. CREATE DENY-ALL RLS POLICIES FOR AUTHENTICATED/ANON
-- ============================================================================
-- Even if someone grants table access, RLS will block the query
-- Policy: Deny authenticated on ops.job_queue
DO $$ BEGIN DROP POLICY IF EXISTS deny_authenticated_all ON ops.job_queue;
CREATE POLICY deny_authenticated_all ON ops.job_queue FOR ALL TO authenticated USING (false) WITH CHECK (false);
RAISE NOTICE 'Created deny policy on ops.job_queue for authenticated';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'SKIPPED: ops.job_queue deny policy (table not found)';
END $$;
-- Policy: Deny authenticated on ops.worker_heartbeats
DO $$ BEGIN DROP POLICY IF EXISTS deny_authenticated_all ON ops.worker_heartbeats;
CREATE POLICY deny_authenticated_all ON ops.worker_heartbeats FOR ALL TO authenticated USING (false) WITH CHECK (false);
RAISE NOTICE 'Created deny policy on ops.worker_heartbeats for authenticated';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'SKIPPED: ops.worker_heartbeats deny policy (table not found)';
END $$;
-- Policy: Deny anon on ops.job_queue
DO $$ BEGIN DROP POLICY IF EXISTS deny_anon_all ON ops.job_queue;
CREATE POLICY deny_anon_all ON ops.job_queue FOR ALL TO anon USING (false) WITH CHECK (false);
RAISE NOTICE 'Created deny policy on ops.job_queue for anon';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'SKIPPED: ops.job_queue anon policy (table not found)';
END $$;
-- Policy: Deny anon on ops.worker_heartbeats
DO $$ BEGIN DROP POLICY IF EXISTS deny_anon_all ON ops.worker_heartbeats;
CREATE POLICY deny_anon_all ON ops.worker_heartbeats FOR ALL TO anon USING (false) WITH CHECK (false);
RAISE NOTICE 'Created deny policy on ops.worker_heartbeats for anon';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'SKIPPED: ops.worker_heartbeats anon policy (table not found)';
END $$;
-- ============================================================================
-- 6. ALLOW SERVICE_ROLE AND DRAGONFLY_WORKER TO BYPASS RLS
-- ============================================================================
-- These roles need full access for legitimate operations
-- Service role bypasses RLS by default, but ensure it's explicit
-- (Supabase configures this, but we document intent)
-- dragonfly_worker policies: allow full access
DO $$ BEGIN DROP POLICY IF EXISTS worker_full_access ON ops.job_queue;
CREATE POLICY worker_full_access ON ops.job_queue FOR ALL TO dragonfly_worker USING (true) WITH CHECK (true);
RAISE NOTICE 'Created allow policy on ops.job_queue for dragonfly_worker';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'SKIPPED: ops.job_queue worker policy (table not found)';
WHEN undefined_object THEN RAISE NOTICE 'SKIPPED: dragonfly_worker role not found';
END $$;
DO $$ BEGIN DROP POLICY IF EXISTS worker_full_access ON ops.worker_heartbeats;
CREATE POLICY worker_full_access ON ops.worker_heartbeats FOR ALL TO dragonfly_worker USING (true) WITH CHECK (true);
RAISE NOTICE 'Created allow policy on ops.worker_heartbeats for dragonfly_worker';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'SKIPPED: ops.worker_heartbeats worker policy (table not found)';
WHEN undefined_object THEN RAISE NOTICE 'SKIPPED: dragonfly_worker role not found';
END $$;
-- ============================================================================
-- 7. VERIFICATION VIEW
-- ============================================================================
-- Create a view that tests can query to verify security configuration
CREATE OR REPLACE VIEW ops.v_security_audit AS
SELECT n.nspname AS schema_name,
    c.relname AS relation_name,
    c.relkind AS relation_type,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced,
    (
        SELECT COUNT(*)
        FROM pg_policy p
        WHERE p.polrelid = c.oid
    ) AS policy_count,
    ARRAY(
        SELECT rolname || ':' || CASE
                WHEN has_table_privilege(r.oid, c.oid, 'SELECT') THEN 'S'
                ELSE ''
            END || CASE
                WHEN has_table_privilege(r.oid, c.oid, 'INSERT') THEN 'I'
                ELSE ''
            END || CASE
                WHEN has_table_privilege(r.oid, c.oid, 'UPDATE') THEN 'U'
                ELSE ''
            END || CASE
                WHEN has_table_privilege(r.oid, c.oid, 'DELETE') THEN 'D'
                ELSE ''
            END
        FROM pg_roles r
        WHERE r.rolname IN (
                'authenticated',
                'anon',
                'public',
                'dragonfly_worker',
                'dragonfly_app'
            )
            AND (
                has_table_privilege(r.oid, c.oid, 'SELECT')
                OR has_table_privilege(r.oid, c.oid, 'INSERT')
                OR has_table_privilege(r.oid, c.oid, 'UPDATE')
                OR has_table_privilege(r.oid, c.oid, 'DELETE')
            )
    ) AS role_grants
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('ops', 'intake')
    AND c.relkind = 'r'
ORDER BY n.nspname,
    c.relname;
COMMENT ON VIEW ops.v_security_audit IS 'Security audit view showing RLS status and role grants for ops/intake tables';
-- Grant to dragonfly_app so security tests can query it
GRANT SELECT ON ops.v_security_audit TO dragonfly_app,
    dragonfly_worker,
    dragonfly_readonly;
-- ============================================================================
-- 8. NOTIFY POSTGREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- VERIFICATION QUERIES (run manually to verify):
-- ============================================================================
-- 
-- Check RLS enforcement:
--   SELECT schema_name, relation_name, rls_enabled, rls_forced, role_grants
--   FROM ops.v_security_audit;
--
-- Test as authenticated (should fail):
--   SET ROLE authenticated;
--   SELECT * FROM ops.job_queue;  -- Should return 0 rows or error
--   RESET ROLE;
--
-- Test admin function (should fail for authenticated):
--   SET ROLE authenticated;
--   SELECT ops.reap_stuck_jobs(30);  -- Should error: permission denied
--   RESET ROLE;
--
-- ============================================================================
