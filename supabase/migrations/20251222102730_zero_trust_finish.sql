-- ============================================================================
-- ZERO TRUST FINISH - Final RLS Hardening & Compliance Monitoring
-- ============================================================================
-- Purpose: Close all RLS gaps and deploy compliance monitoring views
-- Incident: Part of World Class Zero Trust posture
-- Date: 2025-12-22
-- ============================================================================
-- ============================================================================
-- PART A: COMPLIANCE MONITORING VIEWS
-- ============================================================================
-- ----------------------------------------------------------------------------
-- View: ops.v_rls_coverage
-- Purpose: Lists all tables and their RLS compliance status
-- Target: 0 rows with compliance_status = 'VIOLATION'
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS ops.v_rls_coverage;
CREATE VIEW ops.v_rls_coverage AS
SELECT n.nspname AS schema_name,
    c.relname AS table_name,
    c.relrowsecurity AS has_rls,
    c.relforcerowsecurity AS force_rls,
    CASE
        WHEN c.relrowsecurity
        AND c.relforcerowsecurity THEN 'COMPLIANT'
        WHEN c.relrowsecurity
        AND NOT c.relforcerowsecurity THEN 'PARTIAL'
        ELSE 'VIOLATION'
    END AS compliance_status,
    pg_get_userbyid(c.relowner) AS owner,
    obj_description(c.oid, 'pg_class') AS description
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' -- Regular tables only
    AND n.nspname IN ('public', 'enforcement', 'intake', 'ops') -- Exclude system/internal tables that don't need RLS
    AND c.relname NOT IN (
        'schema_migrations',
        -- Supabase internal
        'dragonfly_migrations' -- Our migration tracking (will be secured separately)
    )
ORDER BY CASE
        WHEN c.relrowsecurity
        AND c.relforcerowsecurity THEN 3
        WHEN c.relrowsecurity
        AND NOT c.relforcerowsecurity THEN 2
        ELSE 1
    END,
    n.nspname,
    c.relname;
COMMENT ON VIEW ops.v_rls_coverage IS 'Zero Trust compliance monitor - lists all tables and their RLS status. Target: 0 VIOLATION rows.';
-- ----------------------------------------------------------------------------
-- View: ops.v_security_definers
-- Purpose: Lists all functions with SECURITY DEFINER set (attack surface)
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS ops.v_security_definers;
CREATE VIEW ops.v_security_definers AS
SELECT n.nspname AS schema_name,
    p.proname AS function_name,
    pg_get_userbyid(p.proowner) AS owner,
    pg_get_function_arguments(p.oid) AS arguments,
    pg_get_function_result(p.oid) AS return_type,
    p.prosecdef AS is_security_definer,
    CASE
        WHEN n.nspname = 'ops' THEN 'ALLOWED'
        WHEN n.nspname = 'public'
        AND p.proname IN (
            'claim_pending_job',
            'complete_job',
            'fail_job',
            'requeue_job',
            'reap_stuck_jobs',
            'log_call_outcome',
            'update_plaintiff_priority',
            'update_plaintiff_status',
            'get_plaintiff_call_queue',
            'calculate_priority_score',
            'create_intake_batch',
            'process_intake_row',
            'finalize_intake_batch'
        ) THEN 'WHITELISTED'
        ELSE 'REVIEW_REQUIRED'
    END AS security_status
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.prosecdef = true
    AND n.nspname NOT IN (
        'pg_catalog',
        'information_schema',
        'extensions',
        'auth',
        'storage',
        'graphql',
        'graphql_public',
        'realtime',
        'supabase_functions',
        'supabase_migrations',
        'pgsodium',
        'vault',
        'cron'
    )
ORDER BY CASE
        WHEN n.nspname = 'ops' THEN 1
        WHEN n.nspname = 'public' THEN 2
        ELSE 3
    END,
    n.nspname,
    p.proname;
COMMENT ON VIEW ops.v_security_definers IS 'Security audit view - lists all SECURITY DEFINER functions. Review any REVIEW_REQUIRED entries.';
-- ----------------------------------------------------------------------------
-- View: ops.v_public_grants
-- Purpose: Lists dangerous grants to anon/authenticated on sensitive tables
-- ----------------------------------------------------------------------------
DROP VIEW IF EXISTS ops.v_public_grants;
CREATE VIEW ops.v_public_grants AS
SELECT n.nspname AS schema_name,
    c.relname AS table_name,
    r.rolname AS grantee,
    string_agg(
        CASE
            a.privilege_type
            WHEN 'SELECT' THEN 'S'
            WHEN 'INSERT' THEN 'I'
            WHEN 'UPDATE' THEN 'U'
            WHEN 'DELETE' THEN 'D'
            WHEN 'TRUNCATE' THEN 'T'
            WHEN 'REFERENCES' THEN 'R'
            WHEN 'TRIGGER' THEN 'G'
            ELSE a.privilege_type
        END,
        ''
        ORDER BY a.privilege_type
    ) AS privileges,
    CASE
        WHEN r.rolname = 'anon'
        AND n.nspname = 'public' THEN 'DANGEROUS'
        WHEN r.rolname = 'authenticated'
        AND c.relname IN ('job_queue', 'dragonfly_migrations') THEN 'DANGEROUS'
        ELSE 'OK'
    END AS risk_level
FROM information_schema.table_privileges a
    JOIN pg_class c ON c.relname = a.table_name
    JOIN pg_namespace n ON n.oid = c.relnamespace
    AND n.nspname = a.table_schema
    JOIN pg_roles r ON r.rolname = a.grantee
WHERE n.nspname IN ('public', 'enforcement', 'intake', 'ops')
    AND r.rolname IN ('anon', 'authenticated', 'public')
GROUP BY n.nspname,
    c.relname,
    r.rolname
ORDER BY risk_level DESC,
    n.nspname,
    c.relname;
COMMENT ON VIEW ops.v_public_grants IS 'Security audit view - lists grants to anon/authenticated. Review any DANGEROUS entries.';
-- ============================================================================
-- PART B: LEGACY TABLE HARDENING (public schema)
-- ============================================================================
-- ----------------------------------------------------------------------------
-- public.dragonfly_migrations - Migration tracking table
-- Strategy: RLS + FORCE + Revoke public access
-- ----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'public'
        AND tablename = 'dragonfly_migrations'
) THEN -- Enable RLS
ALTER TABLE public.dragonfly_migrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dragonfly_migrations FORCE ROW LEVEL SECURITY;
-- Revoke all public access
REVOKE ALL ON TABLE public.dragonfly_migrations
FROM anon;
REVOKE ALL ON TABLE public.dragonfly_migrations
FROM authenticated;
REVOKE ALL ON TABLE public.dragonfly_migrations
FROM public;
-- Create service-role-only policy (deny by default - no matching role = no access)
DROP POLICY IF EXISTS service_role_only ON public.dragonfly_migrations;
-- No explicit policy = deny all (RLS enabled, no matching policy = empty result)
RAISE NOTICE 'Hardened: public.dragonfly_migrations';
END IF;
END $$;
-- ----------------------------------------------------------------------------
-- public.judgment_history - Judgment audit trail
-- Strategy: RLS + FORCE + Revoke public access
-- ----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'public'
        AND tablename = 'judgment_history'
) THEN
ALTER TABLE public.judgment_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.judgment_history FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.judgment_history
FROM anon;
REVOKE ALL ON TABLE public.judgment_history
FROM authenticated;
REVOKE ALL ON TABLE public.judgment_history
FROM public;
DROP POLICY IF EXISTS service_role_only ON public.judgment_history;
RAISE NOTICE 'Hardened: public.judgment_history';
END IF;
END $$;
-- ----------------------------------------------------------------------------
-- public.raw_simplicity_imports - Raw import staging
-- Strategy: RLS + FORCE + Revoke public access
-- ----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'public'
        AND tablename = 'raw_simplicity_imports'
) THEN
ALTER TABLE public.raw_simplicity_imports ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.raw_simplicity_imports FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.raw_simplicity_imports
FROM anon;
REVOKE ALL ON TABLE public.raw_simplicity_imports
FROM authenticated;
REVOKE ALL ON TABLE public.raw_simplicity_imports
FROM public;
DROP POLICY IF EXISTS service_role_only ON public.raw_simplicity_imports;
RAISE NOTICE 'Hardened: public.raw_simplicity_imports';
END IF;
END $$;
-- ============================================================================
-- PART C: ENFORCEMENT SCHEMA HARDENING
-- ============================================================================
-- ----------------------------------------------------------------------------
-- enforcement.draft_packets
-- ----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'enforcement'
        AND tablename = 'draft_packets'
) THEN
ALTER TABLE enforcement.draft_packets ENABLE ROW LEVEL SECURITY;
ALTER TABLE enforcement.draft_packets FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE enforcement.draft_packets
FROM anon;
REVOKE ALL ON TABLE enforcement.draft_packets
FROM authenticated;
REVOKE ALL ON TABLE enforcement.draft_packets
FROM public;
-- Grant to service_role only
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE enforcement.draft_packets TO service_role;
RAISE NOTICE 'Hardened: enforcement.draft_packets';
END IF;
END $$;
-- ----------------------------------------------------------------------------
-- enforcement.enforcement_plans
-- ----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'enforcement'
        AND tablename = 'enforcement_plans'
) THEN
ALTER TABLE enforcement.enforcement_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE enforcement.enforcement_plans FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE enforcement.enforcement_plans
FROM anon;
REVOKE ALL ON TABLE enforcement.enforcement_plans
FROM authenticated;
REVOKE ALL ON TABLE enforcement.enforcement_plans
FROM public;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE enforcement.enforcement_plans TO service_role;
RAISE NOTICE 'Hardened: enforcement.enforcement_plans';
END IF;
END $$;
-- ----------------------------------------------------------------------------
-- enforcement.offers
-- ----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'enforcement'
        AND tablename = 'offers'
) THEN
ALTER TABLE enforcement.offers ENABLE ROW LEVEL SECURITY;
ALTER TABLE enforcement.offers FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE enforcement.offers
FROM anon;
REVOKE ALL ON TABLE enforcement.offers
FROM authenticated;
REVOKE ALL ON TABLE enforcement.offers
FROM public;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE enforcement.offers TO service_role;
RAISE NOTICE 'Hardened: enforcement.offers';
END IF;
END $$;
-- ----------------------------------------------------------------------------
-- enforcement.serve_jobs
-- ----------------------------------------------------------------------------
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'enforcement'
        AND tablename = 'serve_jobs'
) THEN
ALTER TABLE enforcement.serve_jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE enforcement.serve_jobs FORCE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE enforcement.serve_jobs
FROM anon;
REVOKE ALL ON TABLE enforcement.serve_jobs
FROM authenticated;
REVOKE ALL ON TABLE enforcement.serve_jobs
FROM public;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE enforcement.serve_jobs TO service_role;
RAISE NOTICE 'Hardened: enforcement.serve_jobs';
END IF;
END $$;
-- ============================================================================
-- PART D: INTAKE SCHEMA HARDENING (if exists)
-- ============================================================================
DO $$
DECLARE tbl RECORD;
BEGIN FOR tbl IN
SELECT tablename
FROM pg_tables
WHERE schemaname = 'intake' LOOP EXECUTE format(
        'ALTER TABLE intake.%I ENABLE ROW LEVEL SECURITY',
        tbl.tablename
    );
EXECUTE format(
    'ALTER TABLE intake.%I FORCE ROW LEVEL SECURITY',
    tbl.tablename
);
EXECUTE format(
    'REVOKE ALL ON TABLE intake.%I FROM anon',
    tbl.tablename
);
EXECUTE format(
    'REVOKE ALL ON TABLE intake.%I FROM authenticated',
    tbl.tablename
);
EXECUTE format(
    'REVOKE ALL ON TABLE intake.%I FROM public',
    tbl.tablename
);
EXECUTE format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE intake.%I TO service_role',
    tbl.tablename
);
RAISE NOTICE 'Hardened: intake.%',
tbl.tablename;
END LOOP;
END $$;
-- ============================================================================
-- PART E: OPS SCHEMA HARDENING (job_queue, etc.)
-- ============================================================================
DO $$
DECLARE tbl RECORD;
BEGIN FOR tbl IN
SELECT tablename
FROM pg_tables
WHERE schemaname = 'ops'
    AND tablename NOT LIKE 'v_%' -- Skip views
    LOOP EXECUTE format(
        'ALTER TABLE ops.%I ENABLE ROW LEVEL SECURITY',
        tbl.tablename
    );
EXECUTE format(
    'ALTER TABLE ops.%I FORCE ROW LEVEL SECURITY',
    tbl.tablename
);
EXECUTE format(
    'REVOKE ALL ON TABLE ops.%I FROM anon',
    tbl.tablename
);
EXECUTE format(
    'REVOKE ALL ON TABLE ops.%I FROM authenticated',
    tbl.tablename
);
EXECUTE format(
    'REVOKE ALL ON TABLE ops.%I FROM public',
    tbl.tablename
);
EXECUTE format(
    'GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE ops.%I TO service_role',
    tbl.tablename
);
RAISE NOTICE 'Hardened: ops.%',
tbl.tablename;
END LOOP;
END $$;
-- ============================================================================
-- VERIFICATION
-- ============================================================================
-- Report any remaining violations
DO $$
DECLARE violation_count INTEGER;
BEGIN
SELECT COUNT(*) INTO violation_count
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
    AND n.nspname IN ('public', 'enforcement', 'intake', 'ops')
    AND c.relname NOT IN ('schema_migrations', 'dragonfly_migrations')
    AND (
        NOT c.relrowsecurity
        OR NOT c.relforcerowsecurity
    );
IF violation_count > 0 THEN RAISE WARNING 'Zero Trust: % tables still have RLS gaps',
violation_count;
ELSE RAISE NOTICE 'Zero Trust: ALL tables are RLS compliant';
END IF;
END $$;
-- ============================================================================
-- GRANT VIEW ACCESS
-- ============================================================================
-- Allow service_role to read compliance views
GRANT SELECT ON ops.v_rls_coverage TO service_role;
GRANT SELECT ON ops.v_security_definers TO service_role;
GRANT SELECT ON ops.v_public_grants TO service_role;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
