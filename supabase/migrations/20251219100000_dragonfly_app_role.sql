-- ============================================================================
-- Migration: Least-Privilege Application Role
-- Created: 2025-12-29
-- Purpose: Create dragonfly_app role with minimum grants for production app
-- ============================================================================
--
-- This migration creates a dedicated `dragonfly_app` role for the backend API
-- and worker processes. It follows the principle of least privilege:
--
--   1. Schema USAGE only on required schemas
--   2. SELECT/INSERT/UPDATE on operational tables (no DELETE)
--   3. EXECUTE on required RPC functions
--   4. No access to audit/evidence tables directly
--
-- After applying this migration:
--   - Create the role password in Supabase dashboard (SQL Editor)
--   - Update SUPABASE_DB_URL in Railway to use dragonfly_app credentials
--
-- ============================================================================
-- ROLLBACK SECTION AT BOTTOM OF FILE
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. CREATE THE APPLICATION ROLE
-- ============================================================================
-- NOTE: Password must be set separately via Supabase SQL Editor for security:
--   ALTER ROLE dragonfly_app WITH PASSWORD 'secure-password-here';
--
-- The role is created with LOGIN capability but no superuser or createdb rights.
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN CREATE ROLE dragonfly_app WITH LOGIN NOINHERIT NOCREATEDB NOCREATEROLE;
RAISE NOTICE 'Created role dragonfly_app';
ELSE RAISE NOTICE 'Role dragonfly_app already exists';
END IF;
END $$;
-- ============================================================================
-- 2. SCHEMA USAGE GRANTS
-- ============================================================================
-- The app needs access to these schemas:
--   public      - Core judgment/plaintiff data + dashboard views
--   ops         - Job queue, batches, worker heartbeats, monitoring
--   enforcement - Enforcement plans, offers, serve jobs
--   intelligence- Entity graph, events, relationships
--   analytics   - CEO metrics views (read-only)
--   finance     - Portfolio stats (read-only)
GRANT USAGE ON SCHEMA public TO dragonfly_app;
GRANT USAGE ON SCHEMA ops TO dragonfly_app;
GRANT USAGE ON SCHEMA enforcement TO dragonfly_app;
-- Create schemas if they don't exist before granting
DO $$ BEGIN CREATE SCHEMA IF NOT EXISTS intelligence;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS finance;
END $$;
GRANT USAGE ON SCHEMA intelligence TO dragonfly_app;
GRANT USAGE ON SCHEMA analytics TO dragonfly_app;
GRANT USAGE ON SCHEMA finance TO dragonfly_app;
-- ============================================================================
-- 3. PUBLIC SCHEMA TABLE GRANTS
-- ============================================================================
-- Core tables: SELECT + INSERT + UPDATE (no DELETE)
GRANT SELECT,
    INSERT,
    UPDATE ON public.judgments TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE ON public.plaintiffs TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE ON public.plaintiff_contacts TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE ON public.plaintiff_status_history TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE ON public.plaintiff_tasks TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE ON public.plaintiff_call_attempts TO dragonfly_app;
-- Enforcement tables in public schema (read + insert for timeline)
GRANT SELECT ON public.enforcement_cases TO dragonfly_app;
GRANT SELECT ON public.enforcement_events TO dragonfly_app;
GRANT SELECT ON public.enforcement_history TO dragonfly_app;
GRANT SELECT ON public.enforcement_timeline TO dragonfly_app;
-- Import tracking (read-only)
GRANT SELECT ON public.import_runs TO dragonfly_app;
-- ETL run logs (insert for workers)
DO $$ BEGIN
GRANT SELECT,
    INSERT ON public.etl_run_logs TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Cases and entities (legacy)
DO $$ BEGIN
GRANT SELECT,
    INSERT,
    UPDATE ON public.cases TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE ON public.entities TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- FOIL tracking
DO $$ BEGIN
GRANT SELECT,
    INSERT ON public.foil_followup_log TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- ============================================================================
-- 4. PUBLIC SCHEMA VIEW GRANTS (Read-Only)
-- ============================================================================
-- Dashboard-critical views
DO $$
DECLARE v_name TEXT;
dashboard_views TEXT [] := ARRAY [
        'v_plaintiffs_overview',
        'v_judgment_pipeline',
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_plaintiff_call_queue',
        'v_priority_pipeline',
        'v_collectability_scores',
        'v_ops_alerts'
    ];
BEGIN FOREACH v_name IN ARRAY dashboard_views LOOP IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relname = v_name
) THEN EXECUTE format(
    'GRANT SELECT ON public.%I TO dragonfly_app',
    v_name
);
END IF;
END LOOP;
END $$;
-- ============================================================================
-- 5. OPS SCHEMA TABLE GRANTS
-- ============================================================================
-- Job queue: full operational access (workers dequeue, update status)
GRANT SELECT,
    INSERT,
    UPDATE ON ops.job_queue TO dragonfly_app;
-- Ingest batches: workers create and update batch status
GRANT SELECT,
    INSERT,
    UPDATE ON ops.ingest_batches TO dragonfly_app;
-- Intake batches (if exists)
DO $$ BEGIN
GRANT SELECT,
    INSERT,
    UPDATE ON ops.intake_batches TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Intake logs: workers write logs
GRANT SELECT,
    INSERT ON ops.intake_logs TO dragonfly_app;
-- Worker heartbeats: workers write their status
GRANT SELECT,
    INSERT,
    UPDATE ON ops.worker_heartbeats TO dragonfly_app;
-- Ingest audit log: workers log operations
GRANT SELECT,
    INSERT,
    UPDATE ON ops.ingest_audit_log TO dragonfly_app;
-- Import errors: workers log errors
GRANT SELECT,
    INSERT ON ops.import_errors TO dragonfly_app;
-- Data discrepancies: workers log issues
GRANT SELECT,
    INSERT,
    UPDATE ON ops.data_discrepancies TO dragonfly_app;
-- Audit log (append-only)
DO $$ BEGIN
GRANT SELECT,
    INSERT ON ops.audit_log TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- ============================================================================
-- 6. OPS SCHEMA VIEW GRANTS (Read-Only)
-- ============================================================================
DO $$
DECLARE v_name TEXT;
ops_views TEXT [] := ARRAY [
        'v_enrichment_health',
        'v_batch_integrity',
        'v_integrity_dashboard',
        'v_metrics_intake_daily',
        'v_plaintiff_call_queue',
        'v_stale_workers',
        'v_daily_health'
    ];
BEGIN FOREACH v_name IN ARRAY ops_views LOOP IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
        AND c.relname = v_name
) THEN EXECUTE format(
    'GRANT SELECT ON ops.%I TO dragonfly_app',
    v_name
);
END IF;
END LOOP;
END $$;
-- ============================================================================
-- 7. ENFORCEMENT SCHEMA TABLE GRANTS
-- ============================================================================
-- Enforcement plans: workers create and update (if exists)
DO $$ BEGIN
GRANT SELECT,
    INSERT,
    UPDATE ON enforcement.enforcement_plans TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Draft packets: workers create and update (if exists)
DO $$ BEGIN
GRANT SELECT,
    INSERT,
    UPDATE ON enforcement.draft_packets TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Offers: workers create and update (if exists)
DO $$ BEGIN
GRANT SELECT,
    INSERT,
    UPDATE ON enforcement.offers TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Serve jobs: workers create and update (if exists)
DO $$ BEGIN
GRANT SELECT,
    INSERT,
    UPDATE ON enforcement.serve_jobs TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- ============================================================================
-- 8. ENFORCEMENT SCHEMA VIEW GRANTS (Read-Only)
-- ============================================================================
DO $$
DECLARE v_name TEXT;
enforcement_views TEXT [] := ARRAY [
        'v_radar',
        'v_offer_stats',
        'v_enforcement_pipeline_status',
        'v_plaintiff_call_queue'
    ];
BEGIN FOREACH v_name IN ARRAY enforcement_views LOOP IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'enforcement'
        AND c.relname = v_name
) THEN EXECUTE format(
    'GRANT SELECT ON enforcement.%I TO dragonfly_app',
    v_name
);
END IF;
END LOOP;
END $$;
-- ============================================================================
-- 9. INTELLIGENCE SCHEMA TABLE GRANTS
-- ============================================================================
-- Events: workers write telemetry
DO $$ BEGIN
GRANT SELECT,
    INSERT ON intelligence.events TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Entities: workers create/update
DO $$ BEGIN
GRANT SELECT,
    INSERT,
    UPDATE ON intelligence.entities TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Relationships: workers create
DO $$ BEGIN
GRANT SELECT,
    INSERT ON intelligence.relationships TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Gig detections: workers create
DO $$ BEGIN
GRANT SELECT,
    INSERT ON intelligence.gig_detections TO dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- ============================================================================
-- 10. ANALYTICS SCHEMA GRANTS (Read-Only)
-- ============================================================================
-- Grant SELECT on all views in analytics schema
DO $$
DECLARE v_rec RECORD;
BEGIN FOR v_rec IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'analytics'
    AND c.relkind = 'v' LOOP EXECUTE format(
        'GRANT SELECT ON analytics.%I TO dragonfly_app',
        v_rec.relname
    );
END LOOP;
END $$;
-- ============================================================================
-- 11. FINANCE SCHEMA GRANTS (Read-Only)
-- ============================================================================
DO $$
DECLARE v_rec RECORD;
BEGIN FOR v_rec IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'finance'
    AND c.relkind = 'v' LOOP EXECUTE format(
        'GRANT SELECT ON finance.%I TO dragonfly_app',
        v_rec.relname
    );
END LOOP;
END $$;
-- ============================================================================
-- 12. SEQUENCE GRANTS (for INSERT operations)
-- ============================================================================
-- Grant USAGE on all sequences the app needs for inserts
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO dragonfly_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO dragonfly_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA enforcement TO dragonfly_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA intelligence TO dragonfly_app;
-- Default privileges for future sequences
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE ON SEQUENCES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT USAGE ON SEQUENCES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA enforcement
GRANT USAGE ON SEQUENCES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA intelligence
GRANT USAGE ON SEQUENCES TO dragonfly_app;
-- ============================================================================
-- 13. RPC FUNCTION GRANTS
-- ============================================================================
-- Grant EXECUTE on functions the app calls via Supabase client.rpc()
-- Worker heartbeat
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.worker_heartbeat(TEXT, TEXT, TEXT, TEXT) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function ops.worker_heartbeat not found, skipping grant';
END $$;
-- Batch integrity check
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.check_batch_integrity(UUID) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function ops.check_batch_integrity not found, skipping grant';
END $$;
-- Duplicate file hash check
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.check_duplicate_file_hash(TEXT, TEXT) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function ops.check_duplicate_file_hash not found, skipping grant';
END $$;
-- CEO metrics RPCs (exposed via PostgREST)
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.ceo_12_metrics() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function public.ceo_12_metrics not found, skipping grant';
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics_v2() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function public.intake_radar_metrics_v2 not found, skipping grant';
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.ceo_command_center_metrics() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function public.ceo_command_center_metrics not found, skipping grant';
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.enforcement_activity_metrics() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function public.enforcement_activity_metrics not found, skipping grant';
END $$;
-- Intake batch management
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.create_intake_batch(TEXT, TEXT, TEXT, JSONB) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function ops.create_intake_batch not found, skipping grant';
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.finalize_intake_batch(UUID, TEXT, INTEGER, INTEGER) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function ops.finalize_intake_batch not found, skipping grant';
END $$;
-- Entity graph functions
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION intelligence.get_defendant_entity_for_judgment(BIGINT) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function intelligence.get_defendant_entity_for_judgment not found, skipping grant';
END $$;
-- Ops alerts
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION analytics.get_ops_alerts() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'Function analytics.get_ops_alerts not found, skipping grant';
END $$;
-- ============================================================================
-- 14. NOTIFY POSTGREST TO RELOAD SCHEMA
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- ROLLBACK STATEMENTS
-- ============================================================================
-- Run these manually if you need to revert the role and all grants:
--
-- BEGIN;
--
-- -- Revoke all grants from dragonfly_app
-- REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA ops FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA enforcement FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA intelligence FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA analytics FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA finance FROM dragonfly_app;
--
-- REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA ops FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA enforcement FROM dragonfly_app;
-- REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA intelligence FROM dragonfly_app;
--
-- REVOKE USAGE ON SCHEMA public FROM dragonfly_app;
-- REVOKE USAGE ON SCHEMA ops FROM dragonfly_app;
-- REVOKE USAGE ON SCHEMA enforcement FROM dragonfly_app;
-- REVOKE USAGE ON SCHEMA intelligence FROM dragonfly_app;
-- REVOKE USAGE ON SCHEMA analytics FROM dragonfly_app;
-- REVOKE USAGE ON SCHEMA finance FROM dragonfly_app;
--
-- -- Drop the role
-- DROP ROLE IF EXISTS dragonfly_app;
--
-- NOTIFY pgrst, 'reload schema';
--
-- COMMIT;
-- ============================================================================
-- ============================================================================
-- POST-MIGRATION STEPS
-- ============================================================================
-- 1. Set the role password in Supabase SQL Editor:
--
--    ALTER ROLE dragonfly_app WITH PASSWORD 'your-secure-password';
--
-- 2. Build the connection string:
--
--    postgresql://dragonfly_app:your-password@db.your-project.supabase.co:5432/postgres?sslmode=require
--
-- 3. Update Railway environment variable:
--
--    SUPABASE_DB_URL=postgresql://dragonfly_app:your-password@db.your-project.supabase.co:5432/postgres?sslmode=require
--
-- 4. Verify connectivity:
--
--    python -m tools.doctor --env prod
--
-- ============================================================================