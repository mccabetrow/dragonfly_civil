-- =============================================================================
-- Permission Reset Migration
-- Fixes 406/500 errors caused by RLS blocking and missing grants
-- =============================================================================
-- Created: 2025-12-19
-- Purpose: Ensure service_role has full access, fix RLS policies, expose views
-- =============================================================================
-- -----------------------------------------------------------------------------
-- 1. GRANT FULL ACCESS TO SERVICE ROLE ON ALL SCHEMAS
-- -----------------------------------------------------------------------------
-- Schema usage grants
GRANT USAGE ON SCHEMA public TO service_role;
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT USAGE ON SCHEMA enforcement TO service_role;
GRANT USAGE ON SCHEMA finance TO service_role;
-- Create intelligence schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS intelligence;
GRANT USAGE ON SCHEMA intelligence TO service_role;
-- Grant ALL PRIVILEGES on all tables in each schema to service_role
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA enforcement TO service_role;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA finance TO service_role;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA intelligence TO service_role;
-- Grant ALL PRIVILEGES on all sequences in each schema to service_role
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA ops TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA enforcement TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA finance TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA intelligence TO service_role;
-- Set default privileges for future objects
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT ALL PRIVILEGES ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL PRIVILEGES ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA enforcement
GRANT ALL PRIVILEGES ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA finance
GRANT ALL PRIVILEGES ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA intelligence
GRANT ALL PRIVILEGES ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT ALL PRIVILEGES ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL PRIVILEGES ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA enforcement
GRANT ALL PRIVILEGES ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA finance
GRANT ALL PRIVILEGES ON SEQUENCES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA intelligence
GRANT ALL PRIVILEGES ON SEQUENCES TO service_role;
-- -----------------------------------------------------------------------------
-- 2. FIX RLS POLICIES FOR INTAKE TABLES
-- -----------------------------------------------------------------------------
-- NOTE: ops.intake_batches doesn't exist - the actual table is ops.ingest_batches
-- Skip RLS for intake_batches since it doesn't exist
-- ops.ingest_batches: Enable RLS and grant service_role access
DO $$ BEGIN -- Enable RLS if not already enabled
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'ops'
        AND table_name = 'ingest_batches'
        AND table_type = 'BASE TABLE'
) THEN
ALTER TABLE ops.ingest_batches ENABLE ROW LEVEL SECURITY;
-- Create policy if it doesn't exist
BEGIN CREATE POLICY "Service Role Full Access" ON ops.ingest_batches FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION
WHEN duplicate_object THEN NULL;
-- Policy already exists
END;
END IF;
END $$;
-- ops.intake_logs: Drop existing policies and create service_role full access
DO $$ BEGIN DROP POLICY IF EXISTS "Service Role Full Access" ON ops.intake_logs;
DROP POLICY IF EXISTS "service_role_full_access" ON ops.intake_logs;
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'Table ops.intake_logs does not exist, skipping policy drop';
END $$;
DO $$ BEGIN
ALTER TABLE ops.intake_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role Full Access" ON ops.intake_logs FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'Table ops.intake_logs does not exist, skipping RLS setup';
WHEN duplicate_object THEN RAISE NOTICE 'Policy already exists on ops.intake_logs';
END $$;
-- public.judgments: Ensure service_role has full access
DO $$ BEGIN DROP POLICY IF EXISTS "Service Role Full Access" ON public.judgments;
DROP POLICY IF EXISTS "service_role_full_access" ON public.judgments;
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'Table public.judgments does not exist';
END $$;
DO $$ BEGIN -- Ensure RLS is enabled
ALTER TABLE public.judgments ENABLE ROW LEVEL SECURITY;
-- Service role full access
CREATE POLICY "Service Role Full Access" ON public.judgments FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'Table public.judgments does not exist';
WHEN duplicate_object THEN RAISE NOTICE 'Policy already exists on public.judgments';
END $$;
-- public.plaintiffs: Ensure service_role has full access
DO $$ BEGIN DROP POLICY IF EXISTS "Service Role Full Access" ON public.plaintiffs;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
DO $$ BEGIN
ALTER TABLE public.plaintiffs ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Service Role Full Access" ON public.plaintiffs FOR ALL TO service_role USING (true) WITH CHECK (true);
EXCEPTION
WHEN undefined_table THEN NULL;
WHEN duplicate_object THEN NULL;
END $$;
-- -----------------------------------------------------------------------------
-- 3. EXPOSE VIEWS TO AUTHENTICATED AND ANON ROLES
-- -----------------------------------------------------------------------------
-- Grant SELECT on ops views
GRANT SELECT ON ops.v_enrichment_health TO authenticated;
GRANT SELECT ON ops.v_enrichment_health TO anon;
GRANT SELECT ON ops.v_enrichment_health TO service_role;
GRANT SELECT ON ops.v_metrics_intake_daily TO authenticated;
GRANT SELECT ON ops.v_metrics_intake_daily TO anon;
GRANT SELECT ON ops.v_metrics_intake_daily TO service_role;
-- Grant SELECT on ops.v_plaintiff_call_queue if it exists
DO $$ BEGIN EXECUTE 'GRANT SELECT ON ops.v_plaintiff_call_queue TO authenticated';
EXECUTE 'GRANT SELECT ON ops.v_plaintiff_call_queue TO anon';
EXECUTE 'GRANT SELECT ON ops.v_plaintiff_call_queue TO service_role';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'View ops.v_plaintiff_call_queue does not exist';
END $$;
-- Grant SELECT on enforcement views
DO $$ BEGIN EXECUTE 'GRANT SELECT ON enforcement.v_radar TO authenticated';
EXECUTE 'GRANT SELECT ON enforcement.v_radar TO anon';
EXECUTE 'GRANT SELECT ON enforcement.v_radar TO service_role';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'View enforcement.v_radar does not exist';
END $$;
DO $$ BEGIN EXECUTE 'GRANT SELECT ON enforcement.v_enforcement_pipeline_status TO authenticated';
EXECUTE 'GRANT SELECT ON enforcement.v_enforcement_pipeline_status TO anon';
EXECUTE 'GRANT SELECT ON enforcement.v_enforcement_pipeline_status TO service_role';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'View enforcement.v_enforcement_pipeline_status does not exist';
END $$;
DO $$ BEGIN EXECUTE 'GRANT SELECT ON enforcement.v_plaintiff_call_queue TO authenticated';
EXECUTE 'GRANT SELECT ON enforcement.v_plaintiff_call_queue TO anon';
EXECUTE 'GRANT SELECT ON enforcement.v_plaintiff_call_queue TO service_role';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'View enforcement.v_plaintiff_call_queue does not exist';
END $$;
-- Grant SELECT on finance views
DO $$ BEGIN EXECUTE 'GRANT SELECT ON finance.v_portfolio_stats TO authenticated';
EXECUTE 'GRANT SELECT ON finance.v_portfolio_stats TO anon';
EXECUTE 'GRANT SELECT ON finance.v_portfolio_stats TO service_role';
EXCEPTION
WHEN undefined_table THEN RAISE NOTICE 'View finance.v_portfolio_stats does not exist';
END $$;
-- -----------------------------------------------------------------------------
-- 4. GRANT AUTHENTICATED ROLE ACCESS FOR DASHBOARD READS
-- -----------------------------------------------------------------------------
-- Schema usage for authenticated
GRANT USAGE ON SCHEMA ops TO authenticated;
GRANT USAGE ON SCHEMA enforcement TO authenticated;
GRANT USAGE ON SCHEMA finance TO authenticated;
GRANT USAGE ON SCHEMA intelligence TO authenticated;
-- Read access on key public tables for authenticated
GRANT SELECT ON public.judgments TO authenticated;
GRANT SELECT ON public.plaintiffs TO authenticated;
-- Read access on ops tables for authenticated
DO $$ BEGIN EXECUTE 'GRANT SELECT ON ops.ingest_batches TO authenticated';
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- -----------------------------------------------------------------------------
-- 5. NOTIFY POSTGREST TO RELOAD SCHEMA CACHE
-- -----------------------------------------------------------------------------
NOTIFY pgrst,
'reload schema';
-- =============================================================================
-- END OF MIGRATION
-- =============================================================================
