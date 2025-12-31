-- 20250108_stabilization_fix.sql
-- ============================================================================
-- STABILIZATION FIX: Comprehensive Go-Live Hardening
-- ============================================================================
--
-- This migration provides comprehensive hardening for production go-live:
--
--   1. FUNCTION SEARCH_PATH: Harden normalize_party_name + compute_judgment_dedupe_key
--      Fix: SET search_path = public, pg_temp to prevent injection
--
--   2. SCHEMA GRANTS: Ensure ops, enforcement, intake have proper access
--      Fix: GRANT USAGE on schemas + SELECT on views to anon/authenticated
--
--   3. VIEW PERMISSIONS: Fix 503 errors on dashboard views
--      Fix: GRANT SELECT on v_enrichment_health, v_live_feed_events, etc.
--
--   4. RLS HARDENING: Additional policies for ops.ingest_batches + ops.intake_logs
--      Fix: service_role + authenticated get proper access
--
-- Author: Dragonfly Reliability Engineering
-- Created: 2025-01-08
-- ============================================================================
-- ============================================================================
-- SECTION 1: HARDEN FUNCTION SEARCH_PATH
-- ============================================================================
-- Security hardening: SET search_path prevents untrusted schema injection
-- 1A: Harden normalize_party_name
CREATE OR REPLACE FUNCTION public.normalize_party_name(p_name TEXT) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE
SET search_path = public,
    pg_temp AS $$
DECLARE v_name TEXT;
BEGIN IF p_name IS NULL THEN RETURN NULL;
END IF;
v_name := upper(trim(p_name));
IF v_name = '' THEN RETURN NULL;
END IF;
-- Strip corporate suffixes
v_name := regexp_replace(v_name, '\s+(LLC|INC|CORP|CO|LTD)\.?$', '', 'gi');
v_name := regexp_replace(v_name, '\s+', ' ', 'g');
RETURN v_name;
END;
$$;
-- 1B: Harden compute_judgment_dedupe_key
CREATE OR REPLACE FUNCTION public.compute_judgment_dedupe_key(
        p_case_number TEXT,
        p_defendant_name TEXT
    ) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE
SET search_path = public,
    pg_temp AS $$
DECLARE v_case TEXT;
v_def TEXT;
BEGIN IF p_case_number IS NULL THEN RETURN NULL;
END IF;
v_case := upper(trim(p_case_number));
IF v_case = '' THEN RETURN NULL;
END IF;
v_def := public.normalize_party_name(p_defendant_name);
IF v_def IS NULL THEN RETURN v_case;
END IF;
RETURN v_case || '|' || v_def;
END;
$$;
COMMENT ON FUNCTION public.normalize_party_name(TEXT) IS 'Normalize party name for deduplication. SET search_path hardened. 2025-01-08';
COMMENT ON FUNCTION public.compute_judgment_dedupe_key(TEXT, TEXT) IS 'Compute deterministic dedupe key. SET search_path hardened. 2025-01-08';
DO $$ BEGIN RAISE NOTICE '✅ Section 1: Function search_path hardening complete';
END $$;
-- ============================================================================
-- SECTION 2: SCHEMA GRANTS (ops, enforcement, intake)
-- ============================================================================
-- Ensure anon, authenticated, and service_role have proper schema access
-- 2A: ops schema grants
GRANT USAGE ON SCHEMA ops TO anon;
GRANT USAGE ON SCHEMA ops TO authenticated;
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT ALL ON SCHEMA ops TO postgres;
GRANT ALL ON SCHEMA ops TO service_role;
-- 2B: enforcement schema grants (if exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'enforcement'
) THEN
GRANT USAGE ON SCHEMA enforcement TO anon;
GRANT USAGE ON SCHEMA enforcement TO authenticated;
GRANT USAGE ON SCHEMA enforcement TO service_role;
GRANT ALL ON SCHEMA enforcement TO postgres;
GRANT ALL ON SCHEMA enforcement TO service_role;
RAISE NOTICE 'Granted usage on enforcement schema';
ELSE RAISE NOTICE 'enforcement schema does not exist, skipping';
END IF;
END $$;
-- 2C: Ensure intake schema grants (supplement emergency fix)
GRANT USAGE ON SCHEMA intake TO anon;
GRANT USAGE ON SCHEMA intake TO authenticated;
GRANT USAGE ON SCHEMA intake TO service_role;
DO $$ BEGIN RAISE NOTICE '✅ Section 2: Schema usage grants complete';
END $$;
-- ============================================================================
-- SECTION 3: VIEW PERMISSIONS (Dashboard Critical)
-- ============================================================================
-- Fix 503 errors: GRANT SELECT on views to anon and authenticated
-- 3A: Grant on ops views (if they exist)
DO $$ BEGIN -- v_intake_monitor
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'ops'
        AND viewname = 'v_intake_monitor'
) THEN
GRANT SELECT ON ops.v_intake_monitor TO anon;
GRANT SELECT ON ops.v_intake_monitor TO authenticated;
GRANT SELECT ON ops.v_intake_monitor TO service_role;
RAISE NOTICE 'Granted SELECT on ops.v_intake_monitor';
END IF;
-- v_enrichment_health
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'ops'
        AND viewname = 'v_enrichment_health'
) THEN
GRANT SELECT ON ops.v_enrichment_health TO anon;
GRANT SELECT ON ops.v_enrichment_health TO authenticated;
GRANT SELECT ON ops.v_enrichment_health TO service_role;
RAISE NOTICE 'Granted SELECT on ops.v_enrichment_health';
END IF;
-- v_batch_metrics
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'ops'
        AND viewname = 'v_batch_metrics'
) THEN
GRANT SELECT ON ops.v_batch_metrics TO anon;
GRANT SELECT ON ops.v_batch_metrics TO authenticated;
GRANT SELECT ON ops.v_batch_metrics TO service_role;
RAISE NOTICE 'Granted SELECT on ops.v_batch_metrics';
END IF;
END $$;
-- 3B: Grant on public views (if they exist)
DO $$ BEGIN -- v_live_feed_events
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'public'
        AND viewname = 'v_live_feed_events'
) THEN
GRANT SELECT ON public.v_live_feed_events TO anon;
GRANT SELECT ON public.v_live_feed_events TO authenticated;
GRANT SELECT ON public.v_live_feed_events TO service_role;
RAISE NOTICE 'Granted SELECT on public.v_live_feed_events';
END IF;
-- v_plaintiffs_overview
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'public'
        AND viewname = 'v_plaintiffs_overview'
) THEN
GRANT SELECT ON public.v_plaintiffs_overview TO anon;
GRANT SELECT ON public.v_plaintiffs_overview TO authenticated;
GRANT SELECT ON public.v_plaintiffs_overview TO service_role;
RAISE NOTICE 'Granted SELECT on public.v_plaintiffs_overview';
END IF;
-- v_judgment_pipeline
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'public'
        AND viewname = 'v_judgment_pipeline'
) THEN
GRANT SELECT ON public.v_judgment_pipeline TO anon;
GRANT SELECT ON public.v_judgment_pipeline TO authenticated;
GRANT SELECT ON public.v_judgment_pipeline TO service_role;
RAISE NOTICE 'Granted SELECT on public.v_judgment_pipeline';
END IF;
-- v_enforcement_overview
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'public'
        AND viewname = 'v_enforcement_overview'
) THEN
GRANT SELECT ON public.v_enforcement_overview TO anon;
GRANT SELECT ON public.v_enforcement_overview TO authenticated;
GRANT SELECT ON public.v_enforcement_overview TO service_role;
RAISE NOTICE 'Granted SELECT on public.v_enforcement_overview';
END IF;
-- v_enforcement_recent
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'public'
        AND viewname = 'v_enforcement_recent'
) THEN
GRANT SELECT ON public.v_enforcement_recent TO anon;
GRANT SELECT ON public.v_enforcement_recent TO authenticated;
GRANT SELECT ON public.v_enforcement_recent TO service_role;
RAISE NOTICE 'Granted SELECT on public.v_enforcement_recent';
END IF;
-- v_plaintiff_call_queue
IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'public'
        AND viewname = 'v_plaintiff_call_queue'
) THEN
GRANT SELECT ON public.v_plaintiff_call_queue TO anon;
GRANT SELECT ON public.v_plaintiff_call_queue TO authenticated;
GRANT SELECT ON public.v_plaintiff_call_queue TO service_role;
RAISE NOTICE 'Granted SELECT on public.v_plaintiff_call_queue';
END IF;
END $$;
DO $$ BEGIN RAISE NOTICE '✅ Section 3: View permissions complete';
END $$;
-- ============================================================================
-- SECTION 4: RLS HARDENING FOR OPS TABLES
-- ============================================================================
-- Ensure ops.ingest_batches and ops.intake_logs have proper policies
-- 4A: ops.ingest_batches policies
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'ops'
        AND tablename = 'ingest_batches'
) THEN -- Drop existing if any
DROP POLICY IF EXISTS service_ingest_batches_all ON ops.ingest_batches;
DROP POLICY IF EXISTS authenticated_ingest_batches_select ON ops.ingest_batches;
DROP POLICY IF EXISTS anon_ingest_batches_select ON ops.ingest_batches;
-- Enable RLS if not already
ALTER TABLE ops.ingest_batches ENABLE ROW LEVEL SECURITY;
-- Full access for service_role
CREATE POLICY service_ingest_batches_all ON ops.ingest_batches FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Read access for authenticated
CREATE POLICY authenticated_ingest_batches_select ON ops.ingest_batches FOR
SELECT TO authenticated USING (true);
-- Read access for anon (dashboard)
CREATE POLICY anon_ingest_batches_select ON ops.ingest_batches FOR
SELECT TO anon USING (true);
RAISE NOTICE 'RLS policies created for ops.ingest_batches';
END IF;
END $$;
-- 4B: ops.intake_logs policies
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'ops'
        AND tablename = 'intake_logs'
) THEN -- Drop existing if any
DROP POLICY IF EXISTS service_intake_logs_all ON ops.intake_logs;
DROP POLICY IF EXISTS authenticated_intake_logs_select ON ops.intake_logs;
DROP POLICY IF EXISTS anon_intake_logs_select ON ops.intake_logs;
-- Enable RLS if not already
ALTER TABLE ops.intake_logs ENABLE ROW LEVEL SECURITY;
-- Full access for service_role
CREATE POLICY service_intake_logs_all ON ops.intake_logs FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Read access for authenticated
CREATE POLICY authenticated_intake_logs_select ON ops.intake_logs FOR
SELECT TO authenticated USING (true);
-- Read access for anon (dashboard)
CREATE POLICY anon_intake_logs_select ON ops.intake_logs FOR
SELECT TO anon USING (true);
RAISE NOTICE 'RLS policies created for ops.intake_logs';
END IF;
END $$;
-- 4C: ops.worker_jobs policies (if exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'ops'
        AND tablename = 'worker_jobs'
) THEN -- Drop existing if any
DROP POLICY IF EXISTS service_worker_jobs_all ON ops.worker_jobs;
-- Enable RLS if not already
ALTER TABLE ops.worker_jobs ENABLE ROW LEVEL SECURITY;
-- Full access for service_role
CREATE POLICY service_worker_jobs_all ON ops.worker_jobs FOR ALL TO service_role USING (true) WITH CHECK (true);
RAISE NOTICE 'RLS policy created for ops.worker_jobs';
END IF;
END $$;
DO $$ BEGIN RAISE NOTICE '✅ Section 4: RLS hardening complete';
END $$;
-- ============================================================================
-- SECTION 5: TABLE GRANTS (ops schema)
-- ============================================================================
-- Explicit table grants for ops schema tables
-- 5A: Grant all to service_role on ops tables
GRANT ALL ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA ops TO postgres;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO authenticated;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO anon;
-- 5B: Sequence grants
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA ops TO service_role;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA ops TO authenticated;
-- 5C: Future table grants
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT SELECT ON TABLES TO authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT SELECT ON TABLES TO anon;
DO $$ BEGIN RAISE NOTICE '✅ Section 5: ops table grants complete';
END $$;
-- ============================================================================
-- SECTION 6: VERIFICATION
-- ============================================================================
DO $$
DECLARE fn_search_path TEXT;
ops_usage_count INT;
view_grant_count INT;
BEGIN -- Check function has SET search_path
SELECT prosrc INTO fn_search_path
FROM pg_proc
WHERE proname = 'normalize_party_name'
    AND pronamespace = 'public'::regnamespace;
-- Count schema grants
SELECT COUNT(*) INTO ops_usage_count
FROM information_schema.role_usage_grants
WHERE object_schema = 'ops';
-- Count view grants on ops.v_intake_monitor (if exists)
SELECT COUNT(*) INTO view_grant_count
FROM information_schema.role_table_grants
WHERE table_schema = 'ops'
    AND privilege_type = 'SELECT';
RAISE NOTICE '================================================';
RAISE NOTICE 'STABILIZATION FIX VERIFICATION:';
RAISE NOTICE '  ops schema grants: %',
ops_usage_count;
RAISE NOTICE '  ops SELECT grants: %',
view_grant_count;
RAISE NOTICE '================================================';
IF ops_usage_count > 0
AND view_grant_count > 0 THEN RAISE NOTICE '✅ STABILIZATION FIX APPLIED SUCCESSFULLY';
ELSE RAISE WARNING '⚠️ PARTIAL FIX - Review verification counts';
END IF;
END $$;
-- ============================================================================
-- END OF STABILIZATION FIX MIGRATION
-- ============================================================================