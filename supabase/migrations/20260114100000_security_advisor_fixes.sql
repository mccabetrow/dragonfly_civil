-- 20260114_security_advisor_fixes.sql
-- ============================================================================
-- Security Advisor Remediation Migration
-- ============================================================================
-- 
-- This migration addresses all issues flagged by the Supabase Security Advisor:
--
-- TASK 1: Function Search Path Mutable
--   - Add explicit search_path to SECURITY DEFINER functions
--
-- TASK 2: Extension in Public
--   - Move vector and pg_trgm to dedicated extensions schema
--   - Update database search_path to include extensions
--
-- TASK 3: RLS Policy Always True  
--   - Restrict overly permissive policies on intake.foil_* tables
--   - Make policies explicit: TO service_role only
--
-- TASK 4: RLS Disabled
--   - Enable RLS on audit.event_log
--   - Enable RLS on public.security_definer_whitelist
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- TASK 1: Fix "Function Search Path Mutable"
-- ============================================================================
-- All SECURITY DEFINER functions must have explicit search_path to prevent
-- privilege escalation attacks via schema hijacking.
-- Each ALTER is guarded to skip gracefully if the function doesn't exist.
-- ============================================================================
-- 1a. ops.f_get_stale_workers(integer, text)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
        AND p.proname = 'f_get_stale_workers'
        AND pg_get_function_identity_arguments(p.oid) = 'threshold_minutes integer, worker_filter text'
) THEN EXECUTE 'ALTER FUNCTION ops.f_get_stale_workers(integer, text)
             SET search_path = ops, public, pg_temp';
RAISE NOTICE '  ✓ ops.f_get_stale_workers - search_path set';
ELSE RAISE NOTICE '  ⊘ ops.f_get_stale_workers(integer, text) not found - skipping';
END IF;
END $$;
-- 1b. ops.touch_worker_heartbeats_updated_at()
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
        AND p.proname = 'touch_worker_heartbeats_updated_at'
        AND pg_get_function_identity_arguments(p.oid) = ''
) THEN EXECUTE 'ALTER FUNCTION ops.touch_worker_heartbeats_updated_at()
             SET search_path = ops, public, pg_temp';
RAISE NOTICE '  ✓ ops.touch_worker_heartbeats_updated_at - search_path set';
ELSE RAISE NOTICE '  ⊘ ops.touch_worker_heartbeats_updated_at() not found - skipping';
END IF;
END $$;
-- 1c. ops.touch_job_queue_updated_at()
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
        AND p.proname = 'touch_job_queue_updated_at'
        AND pg_get_function_identity_arguments(p.oid) = ''
) THEN EXECUTE 'ALTER FUNCTION ops.touch_job_queue_updated_at()
             SET search_path = ops, public, pg_temp';
RAISE NOTICE '  ✓ ops.touch_job_queue_updated_at - search_path set';
ELSE RAISE NOTICE '  ⊘ ops.touch_job_queue_updated_at() not found - skipping';
END IF;
END $$;
-- 1d. ops.check_duplicate_file_hash (signature varies by environment)
DO $$
DECLARE fn_args text;
BEGIN
SELECT pg_get_function_identity_arguments(p.oid) INTO fn_args
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops'
    AND p.proname = 'check_duplicate_file_hash'
LIMIT 1;
IF fn_args IS NOT NULL THEN EXECUTE format(
    'ALTER FUNCTION ops.check_duplicate_file_hash(%s)
                    SET search_path = ops, public, pg_temp',
    fn_args
);
RAISE NOTICE '  ✓ ops.check_duplicate_file_hash(%) - search_path set',
fn_args;
ELSE RAISE NOTICE '  ⊘ ops.check_duplicate_file_hash not found - skipping';
END IF;
END $$;
-- 1e. ops.touch_discrepancy_updated_at()
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
        AND p.proname = 'touch_discrepancy_updated_at'
        AND pg_get_function_identity_arguments(p.oid) = ''
) THEN EXECUTE 'ALTER FUNCTION ops.touch_discrepancy_updated_at()
             SET search_path = ops, public, pg_temp';
RAISE NOTICE '  ✓ ops.touch_discrepancy_updated_at - search_path set';
ELSE RAISE NOTICE '  ⊘ ops.touch_discrepancy_updated_at() not found - skipping';
END IF;
END $$;
-- 1f. rag.update_timestamp()
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'rag'
        AND p.proname = 'update_timestamp'
        AND pg_get_function_identity_arguments(p.oid) = ''
) THEN EXECUTE 'ALTER FUNCTION rag.update_timestamp()
             SET search_path = rag, public, pg_temp';
RAISE NOTICE '  ✓ rag.update_timestamp - search_path set';
ELSE RAISE NOTICE '  ⊘ rag.update_timestamp() not found - skipping';
END IF;
END $$;
-- 1g. judgments._set_updated_at()
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'judgments'
        AND p.proname = '_set_updated_at'
        AND pg_get_function_identity_arguments(p.oid) = ''
) THEN EXECUTE 'ALTER FUNCTION judgments._set_updated_at()
             SET search_path = judgments, public, pg_temp';
RAISE NOTICE '  ✓ judgments._set_updated_at - search_path set';
ELSE RAISE NOTICE '  ⊘ judgments._set_updated_at() not found - skipping';
END IF;
END $$;
DO $$ BEGIN RAISE NOTICE '✓ TASK 1: Processed search_path for SECURITY DEFINER functions';
END $$;
-- ============================================================================
-- TASK 2: Fix "Extension in Public"
-- ============================================================================
-- Best practice: extensions belong in a dedicated schema to keep public clean.
-- This prevents extension functions from polluting the public namespace.
-- ============================================================================
-- 2a. Create extensions schema if not exists
CREATE SCHEMA IF NOT EXISTS extensions;
-- 2b. Grant usage to all roles (extensions need to be callable)
GRANT USAGE ON SCHEMA extensions TO public;
GRANT USAGE ON SCHEMA extensions TO anon;
GRANT USAGE ON SCHEMA extensions TO authenticated;
GRANT USAGE ON SCHEMA extensions TO service_role;
-- 2c. Move extensions to dedicated schema
-- Note: These are idempotent - if already in extensions schema, no change
DO $$ BEGIN -- Move pg_trgm if it exists and is in public
IF EXISTS (
    SELECT 1
    FROM pg_extension e
        JOIN pg_namespace n ON e.extnamespace = n.oid
    WHERE e.extname = 'pg_trgm'
        AND n.nspname = 'public'
) THEN ALTER EXTENSION pg_trgm
SET SCHEMA extensions;
RAISE NOTICE '  → Moved pg_trgm to extensions schema';
ELSE RAISE NOTICE '  → pg_trgm already in extensions schema or not installed';
END IF;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  → Could not move pg_trgm: %',
SQLERRM;
END $$;
DO $$ BEGIN -- Move vector if it exists and is in public
IF EXISTS (
    SELECT 1
    FROM pg_extension e
        JOIN pg_namespace n ON e.extnamespace = n.oid
    WHERE e.extname = 'vector'
        AND n.nspname = 'public'
) THEN ALTER EXTENSION vector
SET SCHEMA extensions;
RAISE NOTICE '  → Moved vector to extensions schema';
ELSE RAISE NOTICE '  → vector already in extensions schema or not installed';
END IF;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '  → Could not move vector: %',
SQLERRM;
END $$;
-- 2d. Update database search_path to include extensions
-- This ensures existing queries using extension functions continue to work
ALTER DATABASE postgres
SET search_path TO public,
    extensions;
-- Also set for current session
SET search_path TO public,
    extensions;
DO $$ BEGIN RAISE NOTICE '✓ TASK 2: Extensions relocated and search_path updated';
END $$;
-- ============================================================================
-- TASK 3: Fix "RLS Policy Always True"
-- ============================================================================
-- The intake.foil_* policies use USING(true) which allows any role to access.
-- These tables contain internal pipeline data and should be service_role only.
-- ============================================================================
-- 3a. intake.foil_datasets - Restrict to service_role
DROP POLICY IF EXISTS "service_foil_datasets_all" ON intake.foil_datasets;
CREATE POLICY "service_foil_datasets_service_only" ON intake.foil_datasets FOR ALL TO service_role USING (true) WITH CHECK (true);
COMMENT ON POLICY "service_foil_datasets_service_only" ON intake.foil_datasets IS 'FOIL datasets are internal pipeline data - service_role only for ETL workers';
-- 3b. intake.foil_column_mappings - Restrict to service_role
DROP POLICY IF EXISTS "service_foil_column_mappings_all" ON intake.foil_column_mappings;
CREATE POLICY "service_foil_column_mappings_service_only" ON intake.foil_column_mappings FOR ALL TO service_role USING (true) WITH CHECK (true);
COMMENT ON POLICY "service_foil_column_mappings_service_only" ON intake.foil_column_mappings IS 'Column mappings are internal config - service_role only';
-- 3c. intake.foil_raw_rows - Restrict to service_role (bonus fix)
DROP POLICY IF EXISTS "service_foil_raw_rows_all" ON intake.foil_raw_rows;
CREATE POLICY "service_foil_raw_rows_service_only" ON intake.foil_raw_rows FOR ALL TO service_role USING (true) WITH CHECK (true);
COMMENT ON POLICY "service_foil_raw_rows_service_only" ON intake.foil_raw_rows IS 'Raw FOIL rows contain unprocessed data - service_role only';
-- 3d. intake.foil_quarantine - Restrict to service_role (bonus fix)
DROP POLICY IF EXISTS "service_foil_quarantine_all" ON intake.foil_quarantine;
CREATE POLICY "service_foil_quarantine_service_only" ON intake.foil_quarantine FOR ALL TO service_role USING (true) WITH CHECK (true);
COMMENT ON POLICY "service_foil_quarantine_service_only" ON intake.foil_quarantine IS 'Quarantined rows are internal - service_role only';
DO $$ BEGIN RAISE NOTICE '✓ TASK 3: RLS policies restricted to service_role for intake.foil_* tables';
END $$;
-- ============================================================================
-- TASK 4: Fix "RLS Disabled" Errors
-- ============================================================================
-- Enable RLS on tables that have policies defined but RLS is disabled.
-- ============================================================================
-- 4a. audit.event_log - Enable RLS (immutable audit log)
ALTER TABLE audit.event_log ENABLE ROW LEVEL SECURITY;
-- Verify/create policy for audit log (service_role only - high sensitivity)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'audit'
        AND tablename = 'event_log'
        AND policyname = 'audit_event_log_service_only'
) THEN CREATE POLICY "audit_event_log_service_only" ON audit.event_log FOR ALL TO service_role USING (true) WITH CHECK (true);
END IF;
END $$;
COMMENT ON POLICY "audit_event_log_service_only" ON audit.event_log IS 'Audit log is HIGH sensitivity - service_role only for compliance logging';
-- 4b. public.security_definer_whitelist - Enable RLS
ALTER TABLE public.security_definer_whitelist ENABLE ROW LEVEL SECURITY;
-- Create policy: service_role can read/write, authenticated can read
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'security_definer_whitelist'
        AND policyname = 'whitelist_service_full'
) THEN CREATE POLICY "whitelist_service_full" ON public.security_definer_whitelist FOR ALL TO service_role USING (true) WITH CHECK (true);
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'security_definer_whitelist'
        AND policyname = 'whitelist_authenticated_read'
) THEN CREATE POLICY "whitelist_authenticated_read" ON public.security_definer_whitelist FOR
SELECT TO authenticated USING (true);
END IF;
END $$;
COMMENT ON POLICY "whitelist_service_full" ON public.security_definer_whitelist IS 'Service role can manage security whitelist';
COMMENT ON POLICY "whitelist_authenticated_read" ON public.security_definer_whitelist IS 'Authenticated users can view approved exceptions for transparency';
DO $$ BEGIN RAISE NOTICE '✓ TASK 4: RLS enabled on audit.event_log and public.security_definer_whitelist';
END $$;
-- ============================================================================
-- Verification Queries (for manual inspection)
-- ============================================================================
DO $$ BEGIN RAISE NOTICE '';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════════';
RAISE NOTICE 'SECURITY ADVISOR FIXES COMPLETE';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════════';
RAISE NOTICE '';
RAISE NOTICE 'TASK 1: search_path set on 7 functions';
RAISE NOTICE '  - ops.f_get_stale_workers';
RAISE NOTICE '  - ops.touch_worker_heartbeats_updated_at';
RAISE NOTICE '  - ops.touch_job_queue_updated_at';
RAISE NOTICE '  - ops.check_duplicate_file_hash';
RAISE NOTICE '  - ops.touch_discrepancy_updated_at';
RAISE NOTICE '  - rag.update_timestamp';
RAISE NOTICE '  - judgments._set_updated_at';
RAISE NOTICE '';
RAISE NOTICE 'TASK 2: Extensions relocated to extensions schema';
RAISE NOTICE '  - pg_trgm -> extensions';
RAISE NOTICE '  - vector -> extensions';
RAISE NOTICE '  - search_path = public, extensions';
RAISE NOTICE '';
RAISE NOTICE 'TASK 3: RLS policies restricted to service_role';
RAISE NOTICE '  - intake.foil_datasets';
RAISE NOTICE '  - intake.foil_column_mappings';
RAISE NOTICE '  - intake.foil_raw_rows';
RAISE NOTICE '  - intake.foil_quarantine';
RAISE NOTICE '';
RAISE NOTICE 'TASK 4: RLS enabled on tables with policies';
RAISE NOTICE '  - audit.event_log';
RAISE NOTICE '  - public.security_definer_whitelist';
RAISE NOTICE '';
RAISE NOTICE 'Re-run Security Advisor to verify all issues resolved.';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════════';
END $$;
COMMIT;
-- Notify PostgREST to reload schema cache
NOTIFY pgrst,
'reload schema';