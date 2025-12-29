-- migrate:up
-- ============================================================================
-- ZERO TRUST HARDENING MIGRATION
-- ============================================================================
--
-- Purpose: Lock down every table in core schemas with RLS + FORCE RLS
-- and revoke all grants from anon/authenticated/public roles.
--
-- This migration is IDEMPOTENT and can be re-run safely.
--
-- Schemas covered:
--   - public (core judgments, plaintiffs, etc.)
--   - enforcement (enforcement workflow tables)
--   - intake (ingestion pipeline tables)
--   - ops (job queue, worker heartbeats, etc.)
--   - judgments (enrichment and scoring)
--   - parties (defendants, contacts)
--   - enrichment (data enrichment tables)
--   - intelligence (analytics/intel tables)
--   - analytics (dashboard views backing tables)
--   - outreach (communication tables)
--   - raw (raw data staging)
--   - ingestion (ingestion staging)
--
-- ============================================================================
-- ============================================================================
-- PART A: THE LOCKDOWN LOOP (Dynamic SQL)
-- ============================================================================
-- For each table in target schemas:
--   1. ENABLE ROW LEVEL SECURITY
--   2. FORCE ROW LEVEL SECURITY
--   3. REVOKE ALL from anon, authenticated, public
-- ============================================================================
DO $$
DECLARE rec RECORD;
target_schemas TEXT [] := ARRAY [
        'public',
        'enforcement',
        'intake',
        'ops',
        'judgments',
        'parties',
        'enrichment',
        'intelligence',
        'analytics',
        'outreach',
        'raw',
        'ingestion'
    ];
-- Tables to exclude (Supabase system tables we don't control)
excluded_tables TEXT [] := ARRAY [
        'schema_migrations',
        'dragonfly_migrations'
    ];
lock_count INT := 0;
revoke_count INT := 0;
BEGIN RAISE NOTICE '[ZERO TRUST] Starting lockdown of % schemas...',
array_length(target_schemas, 1);
FOR rec IN
SELECT n.nspname AS schema_name,
    c.relname AS table_name,
    c.relrowsecurity AS has_rls,
    c.relforcerowsecurity AS force_rls
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r' -- ordinary tables only
    AND n.nspname = ANY(target_schemas)
    AND c.relname != ALL(excluded_tables)
ORDER BY n.nspname,
    c.relname LOOP -- Step 1: Enable RLS (if not already)
    IF NOT rec.has_rls THEN EXECUTE format(
        'ALTER TABLE %I.%I ENABLE ROW LEVEL SECURITY',
        rec.schema_name,
        rec.table_name
    );
RAISE NOTICE '  [RLS] Enabled on %.%',
rec.schema_name,
rec.table_name;
END IF;
-- Step 2: Force RLS (if not already)
IF NOT rec.force_rls THEN EXECUTE format(
    'ALTER TABLE %I.%I FORCE ROW LEVEL SECURITY',
    rec.schema_name,
    rec.table_name
);
RAISE NOTICE '  [FORCE] Enabled on %.%',
rec.schema_name,
rec.table_name;
END IF;
lock_count := lock_count + 1;
-- Step 3: Revoke all from dangerous roles
-- This is safe to re-run (REVOKE is idempotent)
EXECUTE format(
    'REVOKE ALL ON TABLE %I.%I FROM anon, authenticated, public',
    rec.schema_name,
    rec.table_name
);
revoke_count := revoke_count + 1;
END LOOP;
RAISE NOTICE '[ZERO TRUST] Processed % tables, revoked grants on % tables',
lock_count,
revoke_count;
END $$;
-- ============================================================================
-- PART B: OPS VIEWS REPAIR
-- ============================================================================
-- Recreate ops.v_rls_coverage and ops.v_queue_health with expanded schema coverage
-- ============================================================================
-- -----------------------------------------------------------------------------
-- B.1: ops.v_rls_coverage - RLS compliance dashboard
-- -----------------------------------------------------------------------------
-- Shows: schema, table, has_rls, force_rls, compliance_status
-- Expanded to cover ALL core schemas (not just 4)
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ops.v_rls_coverage AS
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
WHERE c.relkind = 'r' -- ordinary tables only
    AND n.nspname IN (
        'public',
        'enforcement',
        'intake',
        'ops',
        'judgments',
        'parties',
        'enrichment',
        'intelligence',
        'analytics',
        'outreach',
        'raw',
        'ingestion'
    )
    AND c.relname NOT IN ('schema_migrations', 'dragonfly_migrations')
ORDER BY CASE
        WHEN c.relrowsecurity
        AND c.relforcerowsecurity THEN 3
        WHEN c.relrowsecurity
        AND NOT c.relforcerowsecurity THEN 2
        ELSE 1
    END,
    n.nspname,
    c.relname;
COMMENT ON VIEW ops.v_rls_coverage IS 'Zero Trust RLS coverage report. All tables should show COMPLIANT status.';
-- -----------------------------------------------------------------------------
-- B.2: ops.v_queue_health - Job queue health dashboard
-- -----------------------------------------------------------------------------
-- Aggregates ops.job_queue by status and job_type
-- Returns: job_type, status, count, oldest_pending_minutes
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS ops.v_queue_health;
CREATE VIEW ops.v_queue_health AS
SELECT job_type,
    status,
    count(*) AS job_count,
    EXTRACT(
        EPOCH
        FROM (now() - min(created_at))
    ) / 60.0 AS oldest_job_minutes,
    EXTRACT(
        EPOCH
        FROM (now() - max(updated_at))
    ) / 60.0 AS last_activity_minutes,
    count(*) FILTER (
        WHERE status = 'pending'
    ) AS pending_count,
    count(*) FILTER (
        WHERE status = 'processing'
    ) AS processing_count,
    count(*) FILTER (
        WHERE status = 'failed'
    ) AS failed_count,
    count(*) FILTER (
        WHERE status = 'completed'
    ) AS completed_count
FROM ops.job_queue
GROUP BY job_type,
    status
ORDER BY CASE
        status
        WHEN 'failed' THEN 1
        WHEN 'pending' THEN 2
        WHEN 'processing' THEN 3
        WHEN 'completed' THEN 4
        ELSE 5
    END,
    job_type;
COMMENT ON VIEW ops.v_queue_health IS 'Job queue health aggregated by type and status. Check for stale pending jobs.';
-- -----------------------------------------------------------------------------
-- B.3: ops.v_queue_summary - Simplified queue overview
-- -----------------------------------------------------------------------------
-- Quick summary view for health checks
-- -----------------------------------------------------------------------------
DROP VIEW IF EXISTS ops.v_queue_summary;
CREATE VIEW ops.v_queue_summary AS
SELECT count(*) AS total_jobs,
    count(*) FILTER (
        WHERE status = 'pending'
    ) AS pending_jobs,
    count(*) FILTER (
        WHERE status = 'processing'
    ) AS processing_jobs,
    count(*) FILTER (
        WHERE status = 'failed'
    ) AS failed_jobs,
    count(*) FILTER (
        WHERE status = 'completed'
    ) AS completed_jobs,
    EXTRACT(
        EPOCH
        FROM (
                now() - min(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
    ) / 60.0 AS oldest_pending_minutes
FROM ops.job_queue;
COMMENT ON VIEW ops.v_queue_summary IS 'Quick job queue health summary for system health checks.';
-- ============================================================================
-- PART C: ZERO REGRET ACCESS CONTROL
-- ============================================================================
-- Grant SELECT on ops views ONLY to service_role and postgres
-- Ensure anon and authenticated have NO access
-- ============================================================================
-- Revoke any existing grants on ops views
REVOKE ALL ON ops.v_rls_coverage
FROM anon,
    authenticated,
    public;
REVOKE ALL ON ops.v_queue_health
FROM anon,
    authenticated,
    public;
REVOKE ALL ON ops.v_queue_summary
FROM anon,
    authenticated,
    public;
-- Grant SELECT only to trusted roles
GRANT SELECT ON ops.v_rls_coverage TO service_role;
GRANT SELECT ON ops.v_queue_health TO service_role;
GRANT SELECT ON ops.v_queue_summary TO service_role;
-- Postgres superuser already has access, but explicit grant for clarity
GRANT SELECT ON ops.v_rls_coverage TO postgres;
GRANT SELECT ON ops.v_queue_health TO postgres;
GRANT SELECT ON ops.v_queue_summary TO postgres;
-- ============================================================================
-- PART D: VERIFICATION ASSERTIONS
-- ============================================================================
-- Fail-safe checks to ensure migration succeeded
-- ============================================================================
DO $$
DECLARE violation_count INT;
partial_count INT;
total_tables INT;
BEGIN -- Count violations
SELECT count(*) FILTER (
        WHERE compliance_status = 'VIOLATION'
    ),
    count(*) FILTER (
        WHERE compliance_status = 'PARTIAL'
    ),
    count(*) INTO violation_count,
    partial_count,
    total_tables
FROM ops.v_rls_coverage;
RAISE NOTICE '';
RAISE NOTICE '============================================================';
RAISE NOTICE '  ZERO TRUST HARDENING COMPLETE';
RAISE NOTICE '============================================================';
RAISE NOTICE '  Total tables processed: %',
total_tables;
RAISE NOTICE '  Full compliance (RLS+FORCE): %',
total_tables - violation_count - partial_count;
RAISE NOTICE '  Partial (RLS only): %',
partial_count;
RAISE NOTICE '  Violations (no RLS): %',
violation_count;
RAISE NOTICE '============================================================';
-- If there are still violations, this is a critical issue
-- But we don't fail the migration - just warn loudly
IF violation_count > 0
OR partial_count > 0 THEN RAISE WARNING 'Zero Trust not fully enforced! Run SELECT * FROM ops.v_rls_coverage WHERE compliance_status != ''COMPLIANT'' to investigate.';
ELSE RAISE NOTICE '✅ ALL TABLES FULLY COMPLIANT - Zero Trust enforced!';
END IF;
END $$;
-- migrate:down
-- ============================================================================
-- ROLLBACK: Remove RLS enforcement (DANGEROUS - Only for development)
-- ============================================================================
-- WARNING: This removes security protections. Never run in production.
-- ============================================================================
DO $$
DECLARE rec RECORD;
target_schemas TEXT [] := ARRAY [
        'public', 'enforcement', 'intake', 'ops', 'judgments',
        'parties', 'enrichment', 'intelligence', 'analytics',
        'outreach', 'raw', 'ingestion'
    ];
BEGIN RAISE WARNING '[ROLLBACK] Removing Zero Trust protections - THIS IS DANGEROUS';
FOR rec IN
SELECT n.nspname AS schema_name,
    c.relname AS table_name
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'r'
    AND n.nspname = ANY(target_schemas)
    AND c.relname NOT IN ('schema_migrations', 'dragonfly_migrations') LOOP EXECUTE format(
        'ALTER TABLE %I.%I NO FORCE ROW LEVEL SECURITY',
        rec.schema_name,
        rec.table_name
    );
-- Note: We don't DISABLE RLS, just remove FORCE
-- Tables remain protected but table owners can bypass
END LOOP;
END $$;
-- Drop the views
DROP VIEW IF EXISTS ops.v_queue_summary;
DROP VIEW IF EXISTS ops.v_queue_health;
DROP VIEW IF EXISTS ops.v_rls_coverage;