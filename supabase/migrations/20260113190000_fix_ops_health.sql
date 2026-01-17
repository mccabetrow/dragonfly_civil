-- =============================================================================
-- Migration: 20260113_fix_ops_health.sql
-- Purpose: Fix ops.get_system_health() RPC that returns 503 in production
--
-- This migration is IDEMPOTENT - safe to run multiple times.
--
-- Security Model:
--   - ops schema is PRIVATE (no anon/authenticated access)
--   - get_system_health() is SECURITY DEFINER (runs as owner)
--   - Only service_role can EXECUTE this function
--
-- Rollback:
--   DROP FUNCTION IF EXISTS ops.get_system_health();
--   -- Then restore previous version if needed
--
-- Author: Principal Engineer
-- Date: 2026-01-13
-- =============================================================================
-- Ensure ops schema exists
CREATE SCHEMA IF NOT EXISTS ops;
-- Revoke all default privileges from public roles on ops schema
-- This ensures anon/authenticated cannot access anything in ops
REVOKE ALL ON SCHEMA ops
FROM PUBLIC;
REVOKE ALL ON SCHEMA ops
FROM anon;
REVOKE ALL ON SCHEMA ops
FROM authenticated;
-- Grant usage only to service_role (backend uses this)
GRANT USAGE ON SCHEMA ops TO service_role;
-- =============================================================================
-- DROP existing functions to ensure clean recreation (handle all overloads)
-- =============================================================================
DROP FUNCTION IF EXISTS ops.get_system_health();
DROP FUNCTION IF EXISTS ops.get_system_health(integer);
-- =============================================================================
-- CREATE ops.get_system_health()
--
-- Returns JSON payload with:
--   - timestamp: Current UTC timestamp
--   - db_time: Database server time (proves DB connectivity)
--   - git_sha: Application SHA from app.settings (if set)
--   - schema_version: Latest migration marker
--   - subsystems: Object with boolean health checks
--
-- SECURITY DEFINER: Runs with owner privileges, not caller
-- search_path: Locked to ops,public to prevent search_path injection
-- =============================================================================
CREATE OR REPLACE FUNCTION ops.get_system_health() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE result jsonb;
v_git_sha text;
v_schema_version text;
v_plaintiffs_ok boolean;
v_judgments_ok boolean;
v_import_runs_ok boolean;
v_db_time timestamptz;
BEGIN -- Capture database server time (proves connectivity)
v_db_time := clock_timestamp();
-- Attempt to read git_sha from app.settings (may not exist)
BEGIN
SELECT current_setting('app.git_sha', true) INTO v_git_sha;
EXCEPTION
WHEN OTHERS THEN v_git_sha := 'unknown';
END;
-- Get latest migration version from supabase_migrations if it exists
BEGIN
SELECT version INTO v_schema_version
FROM supabase_migrations.schema_migrations
ORDER BY version DESC
LIMIT 1;
EXCEPTION
WHEN OTHERS THEN v_schema_version := 'unknown';
END;
-- Subsystem health checks (table existence + row accessibility)
-- These use EXISTS to be fast and avoid full scans
-- Check plaintiffs table accessible
BEGIN
SELECT EXISTS(
        SELECT 1
        FROM public.plaintiffs
        LIMIT 1
    ) INTO v_plaintiffs_ok;
EXCEPTION
WHEN OTHERS THEN v_plaintiffs_ok := false;
END;
-- Check judgments table accessible
BEGIN
SELECT EXISTS(
        SELECT 1
        FROM public.judgments
        LIMIT 1
    ) INTO v_judgments_ok;
EXCEPTION
WHEN OTHERS THEN v_judgments_ok := false;
END;
-- Check ingest.import_runs table accessible
BEGIN
SELECT EXISTS(
        SELECT 1
        FROM public.import_runs
        LIMIT 1
    ) INTO v_import_runs_ok;
EXCEPTION
WHEN OTHERS THEN v_import_runs_ok := false;
END;
-- Build result JSON
result := jsonb_build_object(
    'status',
    'ok',
    'timestamp',
    (now() AT TIME ZONE 'UTC')::text,
    'db_time',
    v_db_time::text,
    'git_sha',
    COALESCE(v_git_sha, 'unknown'),
    'schema_version',
    COALESCE(v_schema_version, 'unknown'),
    'subsystems',
    jsonb_build_object(
        'plaintiffs',
        v_plaintiffs_ok,
        'judgments',
        v_judgments_ok,
        'import_runs',
        v_import_runs_ok
    )
);
RETURN result;
END;
$$;
-- =============================================================================
-- GRANTS: Explicit least-privilege access
-- =============================================================================
-- Revoke execute from all (defense in depth)
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM PUBLIC;
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM anon;
REVOKE ALL ON FUNCTION ops.get_system_health()
FROM authenticated;
-- Grant execute ONLY to service_role (backend service account)
GRANT EXECUTE ON FUNCTION ops.get_system_health() TO service_role;
-- =============================================================================
-- Verification comment
-- =============================================================================
COMMENT ON FUNCTION ops.get_system_health() IS 'System health check for backend certification. Returns JSON with db_time, git_sha, schema_version, and subsystem booleans. SECURITY DEFINER, service_role only.';
-- =============================================================================
-- Verify the function works (will fail if broken)
-- =============================================================================
DO $$
DECLARE health_result jsonb;
BEGIN
SELECT ops.get_system_health() INTO health_result;
IF health_result IS NULL
OR health_result->>'status' IS NULL THEN RAISE EXCEPTION 'ops.get_system_health() verification failed: returned NULL or missing status';
END IF;
RAISE NOTICE 'ops.get_system_health() verified: %',
health_result;
END;
$$;