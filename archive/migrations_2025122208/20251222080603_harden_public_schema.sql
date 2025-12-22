-- ============================================================================
-- Migration: Harden Public Schema (Zero Trust RLS)
-- Created: 2025-12-22
-- Purpose: Enable RLS on ALL tables in public/ops/intake schemas
-- ============================================================================
--
-- SECURITY INVARIANT:
-- Every table in public, ops, and intake schemas MUST have:
--   1. Row Level Security ENABLED
--   2. Row Level Security FORCED (for security definer bypass prevention)
--   3. REVOKE ALL from anon and authenticated (unless explicitly granted)
--
-- This migration crushes the ~70 Supabase Advisor security warnings by
-- applying a Zero Trust model: deny all, then whitelist specific access.
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. ENABLE RLS ON ALL TABLES IN PUBLIC SCHEMA
-- ============================================================================
DO $$
DECLARE tbl RECORD;
enabled_count INT := 0;
BEGIN RAISE NOTICE 'Enabling RLS on public schema tables...';
FOR tbl IN
SELECT c.relname AS table_name
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
    AND c.relkind = 'r' -- Only regular tables
    AND c.relname NOT LIKE 'pg_%'
    AND c.relname NOT LIKE '_pg_%'
    AND c.relname NOT IN ('schema_migrations', 'supabase_migrations') LOOP BEGIN EXECUTE format(
        'ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY',
        tbl.table_name
    );
EXECUTE format(
    'ALTER TABLE public.%I FORCE ROW LEVEL SECURITY',
    tbl.table_name
);
enabled_count := enabled_count + 1;
RAISE NOTICE '  [OK] public.%',
tbl.table_name;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  [SKIP] public.% - %',
tbl.table_name,
SQLERRM;
END;
END LOOP;
RAISE NOTICE 'Public schema: Enabled RLS on % tables',
enabled_count;
END $$;
-- ============================================================================
-- 2. ENABLE RLS ON ALL TABLES IN OPS SCHEMA
-- ============================================================================
DO $$
DECLARE tbl RECORD;
enabled_count INT := 0;
BEGIN RAISE NOTICE 'Enabling RLS on ops schema tables...';
FOR tbl IN
SELECT c.relname AS table_name
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
    AND c.relkind = 'r' LOOP BEGIN EXECUTE format(
        'ALTER TABLE ops.%I ENABLE ROW LEVEL SECURITY',
        tbl.table_name
    );
EXECUTE format(
    'ALTER TABLE ops.%I FORCE ROW LEVEL SECURITY',
    tbl.table_name
);
enabled_count := enabled_count + 1;
RAISE NOTICE '  [OK] ops.%',
tbl.table_name;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  [SKIP] ops.% - %',
tbl.table_name,
SQLERRM;
END;
END LOOP;
RAISE NOTICE 'Ops schema: Enabled RLS on % tables',
enabled_count;
END $$;
-- ============================================================================
-- 3. ENABLE RLS ON ALL TABLES IN INTAKE SCHEMA
-- ============================================================================
DO $$
DECLARE tbl RECORD;
enabled_count INT := 0;
BEGIN RAISE NOTICE 'Enabling RLS on intake schema tables...';
FOR tbl IN
SELECT c.relname AS table_name
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'intake'
    AND c.relkind = 'r' LOOP BEGIN EXECUTE format(
        'ALTER TABLE intake.%I ENABLE ROW LEVEL SECURITY',
        tbl.table_name
    );
EXECUTE format(
    'ALTER TABLE intake.%I FORCE ROW LEVEL SECURITY',
    tbl.table_name
);
enabled_count := enabled_count + 1;
RAISE NOTICE '  [OK] intake.%',
tbl.table_name;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  [SKIP] intake.% - %',
tbl.table_name,
SQLERRM;
END;
END LOOP;
RAISE NOTICE 'Intake schema: Enabled RLS on % tables',
enabled_count;
END $$;
-- ============================================================================
-- 4. REVOKE ALL FROM ANON AND AUTHENTICATED ON OPS/INTAKE
-- ============================================================================
-- Note: This may already be done by zero_trust_hardening migration
-- Running again for idempotency
DO $$
DECLARE tbl RECORD;
BEGIN RAISE NOTICE 'Revoking privileges from anon/authenticated on ops schema...';
FOR tbl IN
SELECT c.relname AS table_name
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
    AND c.relkind IN ('r', 'v', 'm') LOOP BEGIN EXECUTE format(
        'REVOKE ALL ON ops.%I FROM anon, authenticated, public',
        tbl.table_name
    );
EXCEPTION
WHEN OTHERS THEN NULL;
-- Ignore errors
END;
END LOOP;
RAISE NOTICE 'Revoking privileges from anon/authenticated on intake schema...';
FOR tbl IN
SELECT c.relname AS table_name
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'intake'
    AND c.relkind IN ('r', 'v', 'm') LOOP BEGIN EXECUTE format(
        'REVOKE ALL ON intake.%I FROM anon, authenticated, public',
        tbl.table_name
    );
EXCEPTION
WHEN OTHERS THEN NULL;
-- Ignore errors
END;
END LOOP;
RAISE NOTICE 'Revoked all privileges from anon/authenticated on ops/intake';
END $$;
-- ============================================================================
-- 5. CREATE DEFAULT DENY POLICIES (if not exist)
-- ============================================================================
-- These policies ensure that even if RLS is enabled, there's a deny-all default
DO $$
DECLARE tbl RECORD;
BEGIN RAISE NOTICE 'Creating deny-all policies for ops schema...';
FOR tbl IN
SELECT c.relname AS table_name,
    c.oid AS table_oid
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
    AND c.relkind = 'r' LOOP -- Check if policy already exists
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policy
        WHERE polrelid = tbl.table_oid
            AND polname = 'deny_all_authenticated'
    ) THEN BEGIN EXECUTE format(
        'CREATE POLICY deny_all_authenticated ON ops.%I FOR ALL TO authenticated USING (false) WITH CHECK (false)',
        tbl.table_name
    );
RAISE NOTICE '  [OK] Created deny policy on ops.%',
tbl.table_name;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  [SKIP] ops.% - %',
tbl.table_name,
SQLERRM;
END;
END IF;
END LOOP;
END $$;
DO $$
DECLARE tbl RECORD;
BEGIN RAISE NOTICE 'Creating deny-all policies for intake schema...';
FOR tbl IN
SELECT c.relname AS table_name,
    c.oid AS table_oid
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'intake'
    AND c.relkind = 'r' LOOP -- Check if policy already exists
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policy
        WHERE polrelid = tbl.table_oid
            AND polname = 'deny_all_authenticated'
    ) THEN BEGIN EXECUTE format(
        'CREATE POLICY deny_all_authenticated ON intake.%I FOR ALL TO authenticated USING (false) WITH CHECK (false)',
        tbl.table_name
    );
RAISE NOTICE '  [OK] Created deny policy on intake.%',
tbl.table_name;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  [SKIP] intake.% - %',
tbl.table_name,
SQLERRM;
END;
END IF;
END LOOP;
END $$;
-- ============================================================================
-- 6. UPDATE SECURITY AUDIT VIEW
-- ============================================================================
-- Extend the existing v_security_audit to include public schema
CREATE OR REPLACE VIEW ops.v_rls_coverage AS
SELECT n.nspname AS schema_name,
    c.relname AS table_name,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced,
    CASE
        WHEN c.relrowsecurity
        AND c.relforcerowsecurity THEN 'COMPLIANT'
        WHEN c.relrowsecurity THEN 'PARTIAL'
        ELSE 'VIOLATION'
    END AS compliance_status,
    (
        SELECT COUNT(*)
        FROM pg_policy p
        WHERE p.polrelid = c.oid
    ) AS policy_count
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'ops', 'intake')
    AND c.relkind = 'r'
    AND c.relname NOT LIKE 'pg_%'
    AND c.relname NOT LIKE '_pg_%'
    AND c.relname NOT IN ('schema_migrations', 'supabase_migrations')
ORDER BY CASE
        WHEN c.relrowsecurity THEN 0
        ELSE 1
    END,
    -- Violations first
    n.nspname,
    c.relname;
COMMENT ON VIEW ops.v_rls_coverage IS 'RLS coverage report for security compliance';
GRANT SELECT ON ops.v_rls_coverage TO service_role;
GRANT SELECT ON ops.v_rls_coverage TO dragonfly_app;
GRANT SELECT ON ops.v_rls_coverage TO dragonfly_readonly;
-- ============================================================================
-- 7. NOTIFY POSTGREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
--
-- Check RLS coverage:
--   SELECT * FROM ops.v_rls_coverage WHERE compliance_status != 'COMPLIANT';
--
-- Count violations:
--   SELECT compliance_status, COUNT(*) FROM ops.v_rls_coverage GROUP BY 1;
--
-- Check Supabase Advisor:
--   Go to Dashboard -> Advisor -> Security tab
--   Should show near-zero warnings for RLS
--
-- ============================================================================