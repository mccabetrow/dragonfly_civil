-- =============================================================================
-- 20260116120000_ops_fort_knox.sql
-- Fort Knox Security for ops Schema
-- =============================================================================
--
-- SECURITY REQUIREMENTS:
-- 1. ops schema MUST NOT be readable by anon/authenticated
-- 2. All SECURITY DEFINER functions MUST have locked search_path
-- 3. PostgREST schema cache MUST be reloaded after migration
-- 4. All access MUST be auditable
--
-- DESIGN PRINCIPLES:
-- 1. Fully idempotent - safe to run multiple times
-- 2. Comprehensive revocation - covers tables, views, functions, sequences
-- 3. Explicit grants only to service_role (and postgres for maintenance)
-- 4. SECURITY DEFINER functions locked to safe search_path
-- 5. No silent failures - all errors are logged
--
-- =============================================================================
BEGIN;
-- ===========================================================================
-- STEP 0: Metadata
-- ===========================================================================
DO $$ BEGIN RAISE NOTICE '═══════════════════════════════════════════════════════════';
RAISE NOTICE '  OPS SCHEMA FORT KNOX LOCKDOWN';
RAISE NOTICE '  Migration: 20260116120000_ops_fort_knox.sql';
RAISE NOTICE '  Date: 2026-01-16';
RAISE NOTICE '═══════════════════════════════════════════════════════════';
END $$;
-- ===========================================================================
-- STEP 1: Revoke ALL access from PUBLIC, anon, authenticated
-- ===========================================================================
-- 1a. Revoke schema USAGE (prevents all access)
REVOKE ALL ON SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON SCHEMA ops
FROM anon;
REVOKE ALL ON SCHEMA ops
FROM authenticated;
DO $$ BEGIN RAISE NOTICE '✓ Step 1a: Revoked USAGE on ops schema from PUBLIC/anon/authenticated';
END $$;
-- 1b. Revoke on ALL tables (idempotent loop)
DO $$
DECLARE v_table RECORD;
v_count INTEGER := 0;
BEGIN FOR v_table IN
SELECT schemaname,
    tablename
FROM pg_catalog.pg_tables
WHERE schemaname = 'ops' LOOP EXECUTE format(
        'REVOKE ALL ON TABLE ops.%I FROM PUBLIC',
        v_table.tablename
    );
EXECUTE format(
    'REVOKE ALL ON TABLE ops.%I FROM anon',
    v_table.tablename
);
EXECUTE format(
    'REVOKE ALL ON TABLE ops.%I FROM authenticated',
    v_table.tablename
);
v_count := v_count + 1;
END LOOP;
RAISE NOTICE '✓ Step 1b: Revoked table access on % ops tables',
v_count;
END $$;
-- 1c. Revoke on ALL views
DO $$
DECLARE v_view RECORD;
v_count INTEGER := 0;
BEGIN FOR v_view IN
SELECT schemaname,
    viewname
FROM pg_catalog.pg_views
WHERE schemaname = 'ops' LOOP BEGIN EXECUTE format(
        'REVOKE ALL ON ops.%I FROM PUBLIC',
        v_view.viewname
    );
EXECUTE format(
    'REVOKE ALL ON ops.%I FROM anon',
    v_view.viewname
);
EXECUTE format(
    'REVOKE ALL ON ops.%I FROM authenticated',
    v_view.viewname
);
v_count := v_count + 1;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not revoke on view ops.%: %',
v_view.viewname,
SQLERRM;
END;
END LOOP;
RAISE NOTICE '✓ Step 1c: Revoked view access on % ops views',
v_count;
END $$;
-- 1d. Revoke on ALL materialized views
DO $$
DECLARE v_matview RECORD;
v_count INTEGER := 0;
BEGIN FOR v_matview IN
SELECT schemaname,
    matviewname
FROM pg_catalog.pg_matviews
WHERE schemaname = 'ops' LOOP BEGIN EXECUTE format(
        'REVOKE ALL ON ops.%I FROM PUBLIC',
        v_matview.matviewname
    );
EXECUTE format(
    'REVOKE ALL ON ops.%I FROM anon',
    v_matview.matviewname
);
EXECUTE format(
    'REVOKE ALL ON ops.%I FROM authenticated',
    v_matview.matviewname
);
v_count := v_count + 1;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not revoke on matview ops.%: %',
v_matview.matviewname,
SQLERRM;
END;
END LOOP;
RAISE NOTICE '✓ Step 1d: Revoked materialized view access on % ops matviews',
v_count;
END $$;
-- 1e. Revoke on ALL functions
DO $$
DECLARE v_func RECORD;
v_full_sig TEXT;
v_count INTEGER := 0;
BEGIN FOR v_func IN
SELECT p.proname,
    pg_get_function_identity_arguments(p.oid) AS args,
    p.oid
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
v_count := v_count + 1;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not revoke on function %: %',
v_full_sig,
SQLERRM;
END;
END LOOP;
RAISE NOTICE '✓ Step 1e: Revoked function access on % ops functions',
v_count;
END $$;
-- 1f. Revoke on ALL sequences
DO $$
DECLARE v_seq RECORD;
v_count INTEGER := 0;
BEGIN FOR v_seq IN
SELECT schemaname,
    sequencename
FROM pg_catalog.pg_sequences
WHERE schemaname = 'ops' LOOP BEGIN EXECUTE format(
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
v_count := v_count + 1;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not revoke on sequence ops.%: %',
v_seq.sequencename,
SQLERRM;
END;
END LOOP;
RAISE NOTICE '✓ Step 1f: Revoked sequence access on % ops sequences',
v_count;
END $$;
-- ===========================================================================
-- STEP 2: Grant service_role full access (explicit, not via default privileges)
-- ===========================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
-- Grant on all current tables
DO $$
DECLARE v_table RECORD;
BEGIN FOR v_table IN
SELECT tablename
FROM pg_catalog.pg_tables
WHERE schemaname = 'ops' LOOP EXECUTE format(
        'GRANT ALL ON TABLE ops.%I TO service_role',
        v_table.tablename
    );
END LOOP;
END $$;
-- Grant on all current views
DO $$
DECLARE v_view RECORD;
BEGIN FOR v_view IN
SELECT viewname
FROM pg_catalog.pg_views
WHERE schemaname = 'ops' LOOP BEGIN EXECUTE format(
        'GRANT SELECT ON ops.%I TO service_role',
        v_view.viewname
    );
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not grant on view ops.%: %',
v_view.viewname,
SQLERRM;
END;
END LOOP;
END $$;
-- Grant on all current functions
DO $$
DECLARE v_func RECORD;
v_full_sig TEXT;
BEGIN FOR v_func IN
SELECT p.proname,
    pg_get_function_identity_arguments(p.oid) AS args
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops' LOOP v_full_sig := format('ops.%I(%s)', v_func.proname, v_func.args);
BEGIN EXECUTE format(
    'GRANT EXECUTE ON FUNCTION %s TO service_role',
    v_full_sig
);
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not grant on function %: %',
v_full_sig,
SQLERRM;
END;
END LOOP;
END $$;
-- Grant on all current sequences
DO $$
DECLARE v_seq RECORD;
BEGIN FOR v_seq IN
SELECT sequencename
FROM pg_catalog.pg_sequences
WHERE schemaname = 'ops' LOOP BEGIN EXECUTE format(
        'GRANT USAGE, SELECT ON SEQUENCE ops.%I TO service_role',
        v_seq.sequencename
    );
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not grant on sequence ops.%: %',
v_seq.sequencename,
SQLERRM;
END;
END LOOP;
END $$;
DO $$ BEGIN RAISE NOTICE '✓ Step 2: Granted service_role full access to ops schema';
END $$;
-- ===========================================================================
-- STEP 3: Set default privileges for future objects
-- ===========================================================================
-- Revoke default privileges from public roles
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON TABLES
FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON FUNCTIONS
FROM PUBLIC;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON SEQUENCES
FROM PUBLIC;
-- Grant default privileges to service_role
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON FUNCTIONS TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON SEQUENCES TO service_role;
DO $$ BEGIN RAISE NOTICE '✓ Step 3: Set default privileges for future ops objects';
END $$;
-- ===========================================================================
-- STEP 4: Lock search_path on ALL SECURITY DEFINER functions in ops schema
-- ===========================================================================
DO $$
DECLARE v_func RECORD;
v_full_sig TEXT;
v_count INTEGER := 0;
v_locked INTEGER := 0;
BEGIN FOR v_func IN
SELECT p.proname,
    pg_get_function_identity_arguments(p.oid) AS args,
    p.prosecdef AS is_security_definer,
    p.proconfig AS config
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops'
    AND p.prosecdef = TRUE -- SECURITY DEFINER functions only
    LOOP v_count := v_count + 1;
v_full_sig := format('ops.%I(%s)', v_func.proname, v_func.args);
-- Check if search_path is already set
IF v_func.config IS NULL
OR NOT EXISTS (
    SELECT 1
    FROM unnest(v_func.config) AS cfg
    WHERE cfg LIKE 'search_path=%'
) THEN BEGIN -- Lock search_path to ops, pg_catalog (safe defaults)
EXECUTE format(
    'ALTER FUNCTION %s SET search_path = ops, pg_catalog, pg_temp',
    v_full_sig
);
v_locked := v_locked + 1;
RAISE NOTICE '  Locked search_path on: %',
v_full_sig;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not lock search_path on %: %',
v_full_sig,
SQLERRM;
END;
END IF;
END LOOP;
RAISE NOTICE '✓ Step 4: Checked % SECURITY DEFINER functions, locked % search_paths',
v_count,
v_locked;
END $$;
-- ===========================================================================
-- STEP 5: Lock search_path on SECURITY DEFINER functions in OTHER schemas
--         that reference ops schema
-- ===========================================================================
DO $$
DECLARE v_func RECORD;
v_full_sig TEXT;
v_count INTEGER := 0;
v_locked INTEGER := 0;
BEGIN FOR v_func IN
SELECT n.nspname AS schema_name,
    p.proname,
    pg_get_function_identity_arguments(p.oid) AS args,
    p.prosecdef AS is_security_definer,
    p.proconfig AS config,
    pg_get_functiondef(p.oid) AS func_def
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname IN ('public', 'ingest', 'intake', 'enforcement')
    AND p.prosecdef = TRUE -- SECURITY DEFINER functions only
    AND pg_get_functiondef(p.oid) ILIKE '%ops.%' -- References ops schema
    LOOP v_count := v_count + 1;
v_full_sig := format(
    '%I.%I(%s)',
    v_func.schema_name,
    v_func.proname,
    v_func.args
);
-- Check if search_path is already set
IF v_func.config IS NULL
OR NOT EXISTS (
    SELECT 1
    FROM unnest(v_func.config) AS cfg
    WHERE cfg LIKE 'search_path=%'
) THEN BEGIN -- Lock search_path including ops for cross-schema access
EXECUTE format(
    'ALTER FUNCTION %s SET search_path = %I, ops, pg_catalog, pg_temp',
    v_full_sig,
    v_func.schema_name
);
v_locked := v_locked + 1;
RAISE NOTICE '  Locked search_path on: %',
v_full_sig;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  Warning: Could not lock search_path on %: %',
v_full_sig,
SQLERRM;
END;
END IF;
END LOOP;
RAISE NOTICE '✓ Step 5: Checked % cross-schema SECURITY DEFINER functions, locked % search_paths',
v_count,
v_locked;
END $$;
-- ===========================================================================
-- STEP 6: Grant postgres role access for maintenance
-- ===========================================================================
GRANT USAGE ON SCHEMA ops TO postgres;
GRANT ALL ON ALL TABLES IN SCHEMA ops TO postgres;
GRANT ALL ON ALL SEQUENCES IN SCHEMA ops TO postgres;
GRANT ALL ON ALL FUNCTIONS IN SCHEMA ops TO postgres;
DO $$ BEGIN RAISE NOTICE '✓ Step 6: Granted postgres maintenance access';
END $$;
-- ===========================================================================
-- STEP 7: Grant dragonfly_app and dragonfly_worker if they exist
-- ===========================================================================
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT USAGE ON SCHEMA ops TO dragonfly_app;
RAISE NOTICE '✓ Step 7a: Granted dragonfly_app USAGE on ops schema';
ELSE RAISE NOTICE '○ Step 7a: dragonfly_app role does not exist (skipped)';
END IF;
IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN
GRANT USAGE ON SCHEMA ops TO dragonfly_worker;
RAISE NOTICE '✓ Step 7b: Granted dragonfly_worker USAGE on ops schema';
ELSE RAISE NOTICE '○ Step 7b: dragonfly_worker role does not exist (skipped)';
END IF;
END $$;
-- ===========================================================================
-- STEP 8: Create audit trail for ops schema access attempts
-- ===========================================================================
CREATE TABLE IF NOT EXISTS ops.access_audit_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    attempted_at timestamptz NOT NULL DEFAULT now(),
    role_name text NOT NULL,
    object_name text NOT NULL,
    object_type text NOT NULL,
    access_type text NOT NULL,
    was_blocked boolean NOT NULL DEFAULT TRUE,
    client_ip inet,
    metadata jsonb DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_access_audit_log_time ON ops.access_audit_log (attempted_at DESC);
CREATE INDEX IF NOT EXISTS idx_access_audit_log_role ON ops.access_audit_log (role_name, attempted_at DESC);
COMMENT ON TABLE ops.access_audit_log IS 'Audit trail for ops schema access attempts. Used for security monitoring and incident response.';
DO $$ BEGIN RAISE NOTICE '✓ Step 8: Created ops.access_audit_log for security monitoring';
END $$;
-- ===========================================================================
-- STEP 9: PostgREST schema cache reload
-- ===========================================================================
DO $$ BEGIN PERFORM pg_notify('pgrst', 'reload schema');
RAISE NOTICE '✓ Step 9: Sent NOTIFY pgrst to reload schema cache';
END $$;
-- ===========================================================================
-- STEP 10: Verification summary
-- ===========================================================================
DO $$
DECLARE v_anon_usage BOOLEAN;
v_auth_usage BOOLEAN;
v_service_usage BOOLEAN;
v_unsafe_definer_count INTEGER;
BEGIN -- Check schema privileges
SELECT has_schema_privilege('anon', 'ops', 'USAGE'),
    has_schema_privilege('authenticated', 'ops', 'USAGE'),
    has_schema_privilege('service_role', 'ops', 'USAGE') INTO v_anon_usage,
    v_auth_usage,
    v_service_usage;
-- Count SECURITY DEFINER functions without search_path
SELECT COUNT(*) INTO v_unsafe_definer_count
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops'
    AND p.prosecdef = TRUE
    AND (
        p.proconfig IS NULL
        OR NOT EXISTS (
            SELECT 1
            FROM unnest(p.proconfig) AS cfg
            WHERE cfg LIKE 'search_path=%'
        )
    );
RAISE NOTICE '';
RAISE NOTICE '═══════════════════════════════════════════════════════════';
RAISE NOTICE '  FORT KNOX VERIFICATION SUMMARY';
RAISE NOTICE '═══════════════════════════════════════════════════════════';
RAISE NOTICE '  Schema Privileges:';
RAISE NOTICE '    anon has USAGE:          % (expected: FALSE)',
v_anon_usage;
RAISE NOTICE '    authenticated has USAGE: % (expected: FALSE)',
v_auth_usage;
RAISE NOTICE '    service_role has USAGE:  % (expected: TRUE)',
v_service_usage;
RAISE NOTICE '';
RAISE NOTICE '  SECURITY DEFINER Functions:';
RAISE NOTICE '    Missing search_path:     % (expected: 0)',
v_unsafe_definer_count;
RAISE NOTICE '';
IF v_anon_usage
OR v_auth_usage THEN RAISE EXCEPTION 'SECURITY VIOLATION: anon or authenticated still has ops schema access!';
END IF;
IF NOT v_service_usage THEN RAISE EXCEPTION 'CONFIGURATION ERROR: service_role lost ops schema access!';
END IF;
IF v_unsafe_definer_count > 0 THEN RAISE WARNING 'SECURITY WARNING: % SECURITY DEFINER functions still missing search_path',
v_unsafe_definer_count;
END IF;
RAISE NOTICE '  ✅ FORT KNOX LOCKDOWN COMPLETE';
RAISE NOTICE '═══════════════════════════════════════════════════════════';
END $$;
COMMIT;
-- =============================================================================
-- POST-MIGRATION VERIFICATION (run manually)
-- =============================================================================
/*
 -- Run after migration to verify lockdown:
 
 -- 1. Schema privilege check
 SELECT 
 nspname AS schema,
 has_schema_privilege('anon', nspname, 'USAGE') AS anon_usage,
 has_schema_privilege('authenticated', nspname, 'USAGE') AS auth_usage,
 has_schema_privilege('service_role', nspname, 'USAGE') AS service_usage
 FROM pg_namespace
 WHERE nspname = 'ops';
 
 -- Expected: anon_usage=FALSE, auth_usage=FALSE, service_usage=TRUE
 
 -- 2. Table grants check
 SELECT 
 schemaname, tablename, privilege_type, grantee
 FROM information_schema.table_privileges
 WHERE table_schema = 'ops'
 AND grantee IN ('anon', 'authenticated')
 ORDER BY tablename, grantee;
 
 -- Expected: No rows
 
 -- 3. SECURITY DEFINER search_path check
 SELECT 
 n.nspname || '.' || p.proname AS function_name,
 CASE WHEN p.proconfig IS NULL THEN 'MISSING' 
 ELSE array_to_string(p.proconfig, ', ') 
 END AS config
 FROM pg_proc p
 JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname = 'ops'
 AND p.prosecdef = TRUE
 ORDER BY function_name;
 
 -- Expected: All functions have search_path config
 
 -- 4. curl test (from public internet)
 -- curl -X GET "https://<project>.supabase.co/rest/v1/job_queue?select=id&limit=1" \
 --   -H "apikey: <anon_key>" \
 --   -H "Accept-Profile: ops"
 -- Expected: 400 Bad Request or empty [] (schema not exposed)
 */