-- ============================================================================
-- Migration: Zero Trust Schema Hardening
-- Created: 2025-12-22
-- Purpose: Enable RLS on ALL tables across public, ops, intake, enforcement
-- ============================================================================
--
-- ZERO TRUST SECURITY MODEL:
-- ============================================================================
-- This migration establishes the "Zero Trust" baseline for Dragonfly Civil:
--
--   1. Every table has ROW LEVEL SECURITY enabled
--   2. Every table has ROW LEVEL SECURITY forced (even table owners must obey)
--   3. All privileges REVOKED from anon, authenticated, and public roles
--   4. Access is granted ONLY through explicit RLS policies
--
-- This eliminates the entire class of "RLS not enabled" Supabase Advisor
-- warnings and ensures that no data is accessible without explicit policy.
--
-- SECURITY INVARIANT:
-- After this migration, any query from anon or authenticated will return
-- zero rows unless an RLS policy explicitly grants access.
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- UNIFIED SCHEMA HARDENING LOOP
-- ============================================================================
-- Iterates through ALL tables in public, ops, intake, enforcement schemas
-- and applies the Zero Trust baseline to each.
DO $$
DECLARE target_schemas TEXT [] := ARRAY ['public', 'ops', 'intake', 'enforcement'];
schema_name TEXT;
tbl RECORD;
total_enabled INT := 0;
total_revoked INT := 0;
schema_count INT := 0;
BEGIN RAISE NOTICE '============================================================';
RAISE NOTICE 'ZERO TRUST SCHEMA HARDENING';
RAISE NOTICE '============================================================';
RAISE NOTICE 'Target schemas: %',
target_schemas;
RAISE NOTICE '';
-- Loop through each target schema
FOREACH schema_name IN ARRAY target_schemas LOOP schema_count := 0;
RAISE NOTICE '--- Schema: % ---',
schema_name;
-- Check if schema exists
IF NOT EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = schema_name
) THEN RAISE NOTICE '  [SKIP] Schema % does not exist',
schema_name;
CONTINUE;
END IF;
-- Loop through all tables in this schema
FOR tbl IN
SELECT c.relname AS table_name
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = schema_name
    AND c.relkind = 'r' -- Regular tables only
    AND c.relname NOT LIKE 'pg_%'
    AND c.relname NOT LIKE '_pg_%'
    AND c.relname NOT LIKE '_realtime_%'
    AND c.relname NOT IN ('schema_migrations', 'supabase_migrations')
ORDER BY c.relname LOOP BEGIN -- ============================================================
    -- STEP 1: Enable Row Level Security
    -- ============================================================
    -- This activates RLS for the table. Without policies, all
    -- queries from non-owner roles will return zero rows.
    EXECUTE format(
        'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
        schema_name,
        tbl.table_name
    );
-- ============================================================
-- STEP 2: Force Row Level Security
-- ============================================================
-- This ensures that even the table owner (and SECURITY DEFINER
-- functions running as owner) must obey RLS policies.
-- Critical for preventing privilege escalation.
EXECUTE format(
    'ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',
    schema_name,
    tbl.table_name
);
total_enabled := total_enabled + 1;
schema_count := schema_count + 1;
-- ============================================================
-- STEP 3: Revoke All Privileges from Untrusted Roles
-- ============================================================
-- Zero Trust: no access unless explicitly granted via policy.
-- We revoke from:
--   - anon: unauthenticated users
--   - authenticated: logged-in users (still untrusted)
--   - public: the implicit "everyone" role
BEGIN EXECUTE format(
    'REVOKE ALL ON TABLE %I.%I FROM anon, authenticated, public',
    schema_name,
    tbl.table_name
);
total_revoked := total_revoked + 1;
EXCEPTION
WHEN undefined_object THEN -- Role doesn't exist (e.g., in test environment)
NULL;
WHEN OTHERS THEN RAISE NOTICE '  [WARN] Could not revoke on %.%: %',
schema_name,
tbl.table_name,
SQLERRM;
END;
RAISE NOTICE '  [OK] %.%',
schema_name,
tbl.table_name;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  [SKIP] %.% - %',
schema_name,
tbl.table_name,
SQLERRM;
END;
END LOOP;
RAISE NOTICE '  Schema %: % tables hardened',
schema_name,
schema_count;
RAISE NOTICE '';
END LOOP;
RAISE NOTICE '============================================================';
RAISE NOTICE 'SUMMARY';
RAISE NOTICE '============================================================';
RAISE NOTICE '  Tables with RLS enabled+forced: %',
total_enabled;
RAISE NOTICE '  Tables with privileges revoked: %',
total_revoked;
RAISE NOTICE '============================================================';
END $$;
-- ============================================================================
-- COMMENT: Document the Zero Trust Baseline
-- ============================================================================
COMMENT ON SCHEMA public IS 'Zero Trust: RLS enabled on all tables. Access via policies only.';
COMMENT ON SCHEMA ops IS 'Zero Trust: Internal operations. No direct access for anon/authenticated.';
COMMENT ON SCHEMA intake IS 'Zero Trust: Data ingestion. Service-role access only.';
COMMENT ON SCHEMA enforcement IS 'Zero Trust: Enforcement operations. Service-role access only.';
-- ============================================================================
-- RLS COVERAGE MONITORING VIEW
-- ============================================================================
-- This view provides real-time visibility into RLS coverage across all schemas.
-- Use it to detect any tables that might have been added without RLS.
CREATE OR REPLACE VIEW ops.v_rls_coverage AS
SELECT n.nspname AS schema_name,
    c.relname AS table_name,
    c.relrowsecurity AS rls_enabled,
    c.relforcerowsecurity AS rls_forced,
    CASE
        WHEN c.relrowsecurity
        AND c.relforcerowsecurity THEN 'compliant'
        WHEN c.relrowsecurity THEN 'partial'
        ELSE 'non_compliant'
    END AS compliance_status,
    (
        SELECT COUNT(*)
        FROM pg_policy p
        WHERE p.polrelid = c.oid
    ) AS policy_count
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname IN ('public', 'ops', 'intake', 'enforcement')
    AND c.relkind = 'r'
    AND c.relname NOT LIKE 'pg_%'
    AND c.relname NOT LIKE '_pg_%'
    AND c.relname NOT LIKE '_realtime_%'
ORDER BY CASE
        WHEN c.relrowsecurity
        AND c.relforcerowsecurity THEN 3 -- compliant (sort last)
        WHEN c.relrowsecurity THEN 2 -- partial
        ELSE 1 -- non_compliant (sort first)
    END,
    n.nspname,
    c.relname;
COMMENT ON VIEW ops.v_rls_coverage IS 'Real-time RLS compliance status for all tables in audited schemas';
-- Grant access to monitoring roles (wrapped in exception handler for missing roles)
DO $$ BEGIN
GRANT SELECT ON ops.v_rls_coverage TO service_role;
EXCEPTION
WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
GRANT SELECT ON ops.v_rls_coverage TO dragonfly_app;
EXCEPTION
WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
GRANT SELECT ON ops.v_rls_coverage TO dragonfly_readonly;
EXCEPTION
WHEN undefined_object THEN NULL;
END $$;
-- ============================================================================
-- SECURITY DEFINER AUDIT VIEW
-- ============================================================================
-- This view lists all SECURITY DEFINER functions for audit purposes.
CREATE OR REPLACE VIEW ops.v_security_definers AS
SELECT n.nspname AS schema_name,
    p.proname AS function_name,
    n.nspname || '.' || p.proname AS full_name,
    pg_get_function_identity_arguments(p.oid) AS arguments,
    r.rolname AS owner,
    CASE
        WHEN p.provolatile = 'i' THEN 'immutable'
        WHEN p.provolatile = 's' THEN 'stable'
        ELSE 'volatile'
    END AS volatility
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    JOIN pg_roles r ON r.oid = p.proowner
WHERE n.nspname IN ('public', 'ops', 'intake', 'enforcement')
    AND p.prosecdef = true
ORDER BY n.nspname,
    p.proname;
COMMENT ON VIEW ops.v_security_definers IS 'Audit view of all SECURITY DEFINER functions';
-- Grant access to monitoring roles (wrapped in exception handler for missing roles)
DO $$ BEGIN
GRANT SELECT ON ops.v_security_definers TO service_role;
EXCEPTION
WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
GRANT SELECT ON ops.v_security_definers TO dragonfly_app;
EXCEPTION
WHEN undefined_object THEN NULL;
END $$;
DO $$ BEGIN
GRANT SELECT ON ops.v_security_definers TO dragonfly_readonly;
EXCEPTION
WHEN undefined_object THEN NULL;
END $$;
-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Run these after applying the migration to verify success:
--
-- 1. Check RLS coverage:
--    SELECT * FROM ops.v_rls_coverage WHERE compliance_status != 'compliant';
--
-- 2. List all SECURITY DEFINER functions:
--    SELECT * FROM ops.v_security_definers;
--
-- 3. Count non-compliant tables (should be 0):
--    SELECT COUNT(*) FROM ops.v_rls_coverage WHERE compliance_status = 'non_compliant';
--
-- ============================================================================
COMMIT;