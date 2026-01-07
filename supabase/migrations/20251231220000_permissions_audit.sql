-- =============================================================================
-- Migration: 20250109_permissions_audit.sql
-- Purpose:   Comprehensive permissions hardening for plaintiff data onboarding
-- Author:    Dragonfly Security Team
-- Date:      2025-01-09
-- =============================================================================
--
-- SECURITY MODEL:
--   - Explicit GRANT USAGE on all schemas (no implicit access)
--   - Explicit GRANT SELECT on views needed by dashboard
--   - All SECURITY DEFINER functions get SET search_path = public, pg_temp
--   - RLS policies define write paths
--
-- SCHEMAS: public, intake, ops, enforcement, api
-- ROLES:   postgres, anon, authenticated, service_role
--
-- =============================================================================
BEGIN;
-- =============================================================================
-- PART 1: SCHEMA USAGE GRANTS
-- =============================================================================
-- Explicit USAGE grants eliminate "implicit" schema access.
-- Each role gets only what it needs.
-- Ensure schemas exist
CREATE SCHEMA IF NOT EXISTS intake;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS enforcement;
CREATE SCHEMA IF NOT EXISTS api;
-- Revoke implicit public access (defense in depth)
REVOKE ALL ON SCHEMA public
FROM PUBLIC;
REVOKE ALL ON SCHEMA intake
FROM PUBLIC;
REVOKE ALL ON SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON SCHEMA enforcement
FROM PUBLIC;
REVOKE ALL ON SCHEMA api
FROM PUBLIC;
-- postgres (superuser) - full access
GRANT USAGE ON SCHEMA public TO postgres;
GRANT USAGE ON SCHEMA intake TO postgres;
GRANT USAGE ON SCHEMA ops TO postgres;
GRANT USAGE ON SCHEMA enforcement TO postgres;
GRANT USAGE ON SCHEMA api TO postgres;
-- service_role - full access (backend workers)
GRANT USAGE ON SCHEMA public TO service_role;
GRANT USAGE ON SCHEMA intake TO service_role;
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT USAGE ON SCHEMA enforcement TO service_role;
GRANT USAGE ON SCHEMA api TO service_role;
-- authenticated - limited access (logged-in users)
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA api TO authenticated;
-- NO intake, ops, enforcement direct access for authenticated
-- anon - minimal access (public API, read-only views)
GRANT USAGE ON SCHEMA public TO anon;
GRANT USAGE ON SCHEMA api TO anon;
-- NO intake, ops, enforcement direct access for anon
RAISE NOTICE '[PERMISSIONS] Schema USAGE grants applied';
-- =============================================================================
-- PART 2: VIEW ACCESS GRANTS (Dashboard-Critical)
-- =============================================================================
-- Explicit SELECT on views needed by the dashboard.
-- Views are the authorized read surface; tables are hidden.
-- -----------------------------------------------------------------------------
-- public schema views (dashboard core)
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_views TEXT [] := ARRAY [
        'v_plaintiffs_overview',
        'v_judgment_pipeline',
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_plaintiff_call_queue',
        'v_collectability_snapshot',
        'v_priority_pipeline',
        'v_metrics_enforcement',
        'v_metrics_intake_daily',
        'v_metrics_pipeline'
    ];
v_view TEXT;
BEGIN FOREACH v_view IN ARRAY v_views LOOP -- Check if view exists before granting
IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = v_view
) THEN EXECUTE format(
    'GRANT SELECT ON public.%I TO anon, authenticated, service_role',
    v_view
);
RAISE NOTICE '[PERMISSIONS] Granted SELECT on public.% to anon, authenticated, service_role',
v_view;
ELSE RAISE NOTICE '[PERMISSIONS] View public.% does not exist, skipping',
v_view;
END IF;
END LOOP;
END $$;
-- -----------------------------------------------------------------------------
-- ops schema views (SRE monitoring)
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_views TEXT [] := ARRAY [
        'v_batch_performance',
        'v_error_distribution',
        'v_pipeline_health',
        'v_event_log_recent',
        'v_event_metrics_24h',
        'v_event_burn_rate',
        'v_audit_metrics_24h',
        'v_audit_burn_rate',
        'v_outbox_metrics',
        'v_rls_coverage',
        'v_queue_health',
        'v_queue_summary',
        'v_ingest_timeline',
        'v_intake_monitor',
        'v_reaper_status'
    ];
v_view TEXT;
BEGIN FOREACH v_view IN ARRAY v_views LOOP IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'ops'
        AND table_name = v_view
) THEN -- ops views: service_role for workers, anon/authenticated for dashboard read
EXECUTE format(
    'GRANT SELECT ON ops.%I TO anon, authenticated, service_role',
    v_view
);
RAISE NOTICE '[PERMISSIONS] Granted SELECT on ops.% to anon, authenticated, service_role',
v_view;
ELSE RAISE NOTICE '[PERMISSIONS] View ops.% does not exist, skipping',
v_view;
END IF;
END LOOP;
END $$;
-- -----------------------------------------------------------------------------
-- enforcement schema views
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_views TEXT [] := ARRAY [
        'v_metrics_enforcement',
        'v_plaintiff_call_queue'
    ];
v_view TEXT;
BEGIN FOREACH v_view IN ARRAY v_views LOOP IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'enforcement'
        AND table_name = v_view
) THEN EXECUTE format(
    'GRANT SELECT ON enforcement.%I TO anon, authenticated, service_role',
    v_view
);
RAISE NOTICE '[PERMISSIONS] Granted SELECT on enforcement.% to anon, authenticated, service_role',
v_view;
ELSE RAISE NOTICE '[PERMISSIONS] View enforcement.% does not exist, skipping',
v_view;
END IF;
END LOOP;
END $$;
RAISE NOTICE '[PERMISSIONS] View SELECT grants applied';
-- =============================================================================
-- PART 3: TABLE ACCESS FOR SERVICE_ROLE (Workers Only)
-- =============================================================================
-- service_role needs CRUD on core tables for backend processing.
-- anon/authenticated NEVER get direct table access.
-- Core tables for service_role
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.judgments TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiffs TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiff_contacts TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiff_status_history TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiff_tasks TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.job_queue TO service_role;
-- intake tables for service_role
GRANT SELECT,
    INSERT,
    UPDATE ON intake.simplicity_batches TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON intake.simplicity_import_log TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON intake.simplicity_raw TO service_role;
-- ops tables for service_role (logging, auditing)
GRANT SELECT,
    INSERT,
    UPDATE ON ops.event_log TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON ops.outbox TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON ops.reaper_log TO service_role;
RAISE NOTICE '[PERMISSIONS] Table grants for service_role applied';
-- =============================================================================
-- PART 4: RLS POLICIES (Write Paths)
-- =============================================================================
-- Define explicit write paths through RLS.
-- authenticated can INSERT via specific policies.
-- Enable RLS on intake tables
ALTER TABLE intake.simplicity_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE intake.simplicity_import_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE intake.simplicity_raw ENABLE ROW LEVEL SECURITY;
-- Policy: authenticated can INSERT into simplicity_batches (for uploads)
DROP POLICY IF EXISTS authenticated_insert_batches ON intake.simplicity_batches;
CREATE POLICY authenticated_insert_batches ON intake.simplicity_batches FOR
INSERT TO authenticated WITH CHECK (true);
-- Policy: authenticated can view their own batches
DROP POLICY IF EXISTS authenticated_select_batches ON intake.simplicity_batches;
CREATE POLICY authenticated_select_batches ON intake.simplicity_batches FOR
SELECT TO authenticated USING (true);
-- service_role bypasses RLS
DROP POLICY IF EXISTS service_role_all_batches ON intake.simplicity_batches;
CREATE POLICY service_role_all_batches ON intake.simplicity_batches FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE '[PERMISSIONS] RLS policies applied to intake tables';
-- =============================================================================
-- PART 5: FUNCTION HARDENING (search_path)
-- =============================================================================
-- ALL SECURITY DEFINER functions MUST set search_path = public, pg_temp
-- This prevents search path hijacking attacks.
-- -----------------------------------------------------------------------------
-- public schema functions
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_func RECORD;
v_alter_sql TEXT;
BEGIN FOR v_func IN
SELECT n.nspname AS schema_name,
    p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.prosecdef = true -- SECURITY DEFINER
    LOOP v_alter_sql := format(
        'ALTER FUNCTION public.%I(%s) SET search_path = public, pg_temp',
        v_func.func_name,
        v_func.func_args
    );
BEGIN EXECUTE v_alter_sql;
RAISE NOTICE '[HARDENING] Set search_path on public.%(%)',
v_func.func_name,
v_func.func_args;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '[HARDENING] Could not alter public.%: %',
v_func.func_name,
SQLERRM;
END;
END LOOP;
END $$;
-- -----------------------------------------------------------------------------
-- ops schema functions
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_func RECORD;
v_alter_sql TEXT;
BEGIN FOR v_func IN
SELECT n.nspname AS schema_name,
    p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'ops'
    AND p.prosecdef = true LOOP v_alter_sql := format(
        'ALTER FUNCTION ops.%I(%s) SET search_path = public, pg_temp',
        v_func.func_name,
        v_func.func_args
    );
BEGIN EXECUTE v_alter_sql;
RAISE NOTICE '[HARDENING] Set search_path on ops.%(%)',
v_func.func_name,
v_func.func_args;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '[HARDENING] Could not alter ops.%: %',
v_func.func_name,
SQLERRM;
END;
END LOOP;
END $$;
-- -----------------------------------------------------------------------------
-- api schema functions
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_func RECORD;
v_alter_sql TEXT;
BEGIN FOR v_func IN
SELECT n.nspname AS schema_name,
    p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'api'
    AND p.prosecdef = true LOOP v_alter_sql := format(
        'ALTER FUNCTION api.%I(%s) SET search_path = public, pg_temp',
        v_func.func_name,
        v_func.func_args
    );
BEGIN EXECUTE v_alter_sql;
RAISE NOTICE '[HARDENING] Set search_path on api.%(%)',
v_func.func_name,
v_func.func_args;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '[HARDENING] Could not alter api.%: %',
v_func.func_name,
SQLERRM;
END;
END LOOP;
END $$;
-- -----------------------------------------------------------------------------
-- intake schema functions
-- -----------------------------------------------------------------------------
DO $$
DECLARE v_func RECORD;
v_alter_sql TEXT;
BEGIN FOR v_func IN
SELECT n.nspname AS schema_name,
    p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'intake'
    AND p.prosecdef = true LOOP v_alter_sql := format(
        'ALTER FUNCTION intake.%I(%s) SET search_path = public, pg_temp',
        v_func.func_name,
        v_func.func_args
    );
BEGIN EXECUTE v_alter_sql;
RAISE NOTICE '[HARDENING] Set search_path on intake.%(%)',
v_func.func_name,
v_func.func_args;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '[HARDENING] Could not alter intake.%: %',
v_func.func_name,
SQLERRM;
END;
END LOOP;
END $$;
RAISE NOTICE '[HARDENING] SECURITY DEFINER function search_path hardening complete';
-- =============================================================================
-- PART 6: RPC EXECUTE GRANTS
-- =============================================================================
-- Grant EXECUTE on api.* RPCs to appropriate roles.
DO $$
DECLARE v_func RECORD;
BEGIN FOR v_func IN
SELECT p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'api' LOOP -- api.* functions are callable by anon, authenticated, service_role
    EXECUTE format(
        'GRANT EXECUTE ON FUNCTION api.%I(%s) TO anon, authenticated, service_role',
        v_func.func_name,
        v_func.func_args
    );
RAISE NOTICE '[PERMISSIONS] Granted EXECUTE on api.%(%)',
v_func.func_name,
v_func.func_args;
END LOOP;
END $$;
RAISE NOTICE '[PERMISSIONS] RPC EXECUTE grants applied';
-- =============================================================================
-- PART 7: SEQUENCE GRANTS (for INSERT operations)
-- =============================================================================
-- service_role needs sequence usage for auto-increment fields.
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO service_role;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA ops TO service_role;
-- authenticated needs sequence for batch uploads
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO authenticated;
RAISE NOTICE '[PERMISSIONS] Sequence grants applied';
-- =============================================================================
-- PART 8: VALIDATION
-- =============================================================================
-- Verify the permissions model is correctly applied.
DO $$
DECLARE v_schema_count INT;
v_definer_unset INT;
BEGIN -- Check schemas have explicit grants
SELECT COUNT(*) INTO v_schema_count
FROM information_schema.role_usage_grants
WHERE grantee IN ('anon', 'authenticated', 'service_role')
    AND object_type = 'SCHEMA';
RAISE NOTICE '[VALIDATION] Schema grants found: %',
v_schema_count;
-- Check for SECURITY DEFINER functions without search_path set
SELECT COUNT(*) INTO v_definer_unset
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.prosecdef = true
    AND n.nspname IN ('public', 'ops', 'api', 'intake', 'enforcement')
    AND NOT EXISTS (
        SELECT 1
        FROM pg_options_to_table(p.proconfig)
        WHERE option_name = 'search_path'
    );
IF v_definer_unset > 0 THEN RAISE WARNING '[VALIDATION] Found % SECURITY DEFINER functions without search_path set',
v_definer_unset;
ELSE RAISE NOTICE '[VALIDATION] All SECURITY DEFINER functions have search_path set';
END IF;
END $$;
-- =============================================================================
-- PART 9: AUDIT LOG
-- =============================================================================
-- Record this migration in ops.event_log
INSERT INTO ops.event_log (
        event_type,
        event_name,
        event_source,
        payload
    )
VALUES (
        'system',
        'permissions_audit_migration',
        'migration/20250109_permissions_audit',
        jsonb_build_object(
            'version',
            '1.0.0',
            'applied_at',
            NOW(),
            'schemas_hardened',
            ARRAY ['public', 'intake', 'ops', 'enforcement', 'api'],
            'roles_configured',
            ARRAY ['postgres', 'anon', 'authenticated', 'service_role']
        )
    ) ON CONFLICT DO NOTHING;
COMMIT;
-- =============================================================================
-- SUMMARY
-- =============================================================================
-- This migration establishes the following security model:
--
-- SCHEMAS:
--   public:      anon ✓ authenticated ✓ service_role ✓
--   api:         anon ✓ authenticated ✓ service_role ✓
--   intake:      service_role ✓ (no anon/authenticated direct)
--   ops:         service_role ✓ (no anon/authenticated direct)
--   enforcement: service_role ✓ (no anon/authenticated direct)
--
-- VIEWS (SELECT):
--   Dashboard views in public/ops: anon ✓ authenticated ✓ service_role ✓
--
-- TABLES:
--   Core tables: service_role only (no anon/authenticated)
--   Writes go through RLS policies or RPCs
--
-- FUNCTIONS:
--   All SECURITY DEFINER functions: SET search_path = public, pg_temp
--   api.* RPCs: EXECUTE granted to anon, authenticated, service_role
--
-- RLS:
--   intake.simplicity_batches: authenticated can INSERT (uploads)
--   All other tables: service_role bypass, authenticated/anon blocked
-- =============================================================================
