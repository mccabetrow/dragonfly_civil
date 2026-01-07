-- =============================================================================
-- Migration: 20251231221000_permissions_audit_fix.sql
-- Purpose:   Apply remaining permissions from 20251231220000 (syntax fix)
-- =============================================================================
-- The original migration had RAISE NOTICE outside DO blocks.
-- This migration applies the remaining grants that failed to apply.
-- =============================================================================
BEGIN;
-- =============================================================================
-- PART 1: VIEW ACCESS GRANTS (Dashboard-Critical)
-- =============================================================================
-- public schema views
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
BEGIN FOREACH v_view IN ARRAY v_views LOOP IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = v_view
) THEN EXECUTE format(
    'GRANT SELECT ON public.%I TO anon, authenticated, service_role',
    v_view
);
END IF;
END LOOP;
END $$;
-- ops schema views
DO $$
DECLARE v_views TEXT [] := ARRAY [
        'v_batch_performance',
        'v_error_distribution',
        'v_pipeline_health',
        'v_event_log_recent',
        'v_event_metrics_24h',
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
) THEN EXECUTE format(
    'GRANT SELECT ON ops.%I TO anon, authenticated, service_role',
    v_view
);
END IF;
END LOOP;
END $$;
-- =============================================================================
-- PART 2: TABLE GRANTS (service_role only)
-- =============================================================================
-- Core tables
DO $$ BEGIN -- public schema
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
) THEN
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.judgments TO service_role;
END IF;
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
) THEN
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiffs TO service_role;
END IF;
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
) THEN
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiff_contacts TO service_role;
END IF;
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_status_history'
) THEN
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiff_status_history TO service_role;
END IF;
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_tasks'
) THEN
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiff_tasks TO service_role;
END IF;
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'job_queue'
) THEN
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.job_queue TO service_role;
END IF;
END $$;
-- =============================================================================
-- PART 3: FUNCTION HARDENING (search_path)
-- =============================================================================
-- Harden public schema SECURITY DEFINER functions
DO $$
DECLARE v_func RECORD;
BEGIN FOR v_func IN
SELECT p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.prosecdef = true LOOP BEGIN EXECUTE format(
        'ALTER FUNCTION public.%I(%s) SET search_path = public, pg_temp',
        v_func.func_name,
        v_func.func_args
    );
EXCEPTION
WHEN OTHERS THEN -- Skip if function cannot be altered
NULL;
END;
END LOOP;
END $$;
-- Harden ops schema SECURITY DEFINER functions
DO $$
DECLARE v_func RECORD;
BEGIN FOR v_func IN
SELECT p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'ops'
    AND p.prosecdef = true LOOP BEGIN EXECUTE format(
        'ALTER FUNCTION ops.%I(%s) SET search_path = public, pg_temp',
        v_func.func_name,
        v_func.func_args
    );
EXCEPTION
WHEN OTHERS THEN NULL;
END;
END LOOP;
END $$;
-- Harden api schema SECURITY DEFINER functions
DO $$
DECLARE v_func RECORD;
BEGIN FOR v_func IN
SELECT p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'api'
    AND p.prosecdef = true LOOP BEGIN EXECUTE format(
        'ALTER FUNCTION api.%I(%s) SET search_path = public, pg_temp',
        v_func.func_name,
        v_func.func_args
    );
EXCEPTION
WHEN OTHERS THEN NULL;
END;
END LOOP;
END $$;
-- =============================================================================
-- PART 4: RPC EXECUTE GRANTS
-- =============================================================================
DO $$
DECLARE v_func RECORD;
BEGIN FOR v_func IN
SELECT p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS func_args
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'api' LOOP BEGIN EXECUTE format(
        'GRANT EXECUTE ON FUNCTION api.%I(%s) TO anon, authenticated, service_role',
        v_func.func_name,
        v_func.func_args
    );
EXCEPTION
WHEN OTHERS THEN NULL;
END;
END LOOP;
END $$;
-- =============================================================================
-- PART 5: SEQUENCE GRANTS
-- =============================================================================
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA ops TO service_role;
COMMIT;
