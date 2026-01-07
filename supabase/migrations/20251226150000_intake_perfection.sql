-- ===========================================================================
-- Migration: Intake Perfection - Service-Role Only Architecture
-- ===========================================================================
-- Finalize the "UI is Read-Only, Backend has exclusive Write access" model.
--
-- This migration:
--   1. REVOKES all permissions from anon/authenticated on intake tables
--   2. Adds service_role ALL policies on simplicity_* tables (foil_* already have them)
--   3. Grants SELECT on views to authenticated/dragonfly_app for dashboard reads
--   4. Documents the security model
--
-- Philosophy: Default Deny + Explicit Allow for service_role only
-- ===========================================================================
-- ===========================================================================
-- 1. REVOKE all permissions from anon/authenticated on intake tables
-- (Defense in depth - RLS already blocks, but grants should not exist)
-- ===========================================================================
-- Revoke from anon (should already be denied)
REVOKE ALL ON intake.simplicity_batches
FROM anon;
REVOKE ALL ON intake.simplicity_raw_rows
FROM anon;
REVOKE ALL ON intake.simplicity_validated_rows
FROM anon;
REVOKE ALL ON intake.simplicity_failed_rows
FROM anon;
-- Revoke from authenticated (UI should only read via views)
REVOKE ALL ON intake.simplicity_batches
FROM authenticated;
REVOKE ALL ON intake.simplicity_raw_rows
FROM authenticated;
REVOKE ALL ON intake.simplicity_validated_rows
FROM authenticated;
REVOKE ALL ON intake.simplicity_failed_rows
FROM authenticated;
-- ===========================================================================
-- 2. Ensure FORCE ROW LEVEL SECURITY on all intake tables
-- (Already enabled via prior migrations, but re-assert for safety)
-- ===========================================================================
ALTER TABLE intake.simplicity_batches FORCE ROW LEVEL SECURITY;
ALTER TABLE intake.simplicity_raw_rows FORCE ROW LEVEL SECURITY;
ALTER TABLE intake.simplicity_validated_rows FORCE ROW LEVEL SECURITY;
ALTER TABLE intake.simplicity_failed_rows FORCE ROW LEVEL SECURITY;
-- ===========================================================================
-- 3. Add service_role ALL policies on simplicity_* tables
-- (foil_* already have them, simplicity_* were missing)
-- ===========================================================================
-- simplicity_batches
DROP POLICY IF EXISTS service_simplicity_batches_all ON intake.simplicity_batches;
CREATE POLICY service_simplicity_batches_all ON intake.simplicity_batches FOR ALL TO service_role USING (true) WITH CHECK (true);
-- simplicity_raw_rows
DROP POLICY IF EXISTS service_simplicity_raw_rows_all ON intake.simplicity_raw_rows;
CREATE POLICY service_simplicity_raw_rows_all ON intake.simplicity_raw_rows FOR ALL TO service_role USING (true) WITH CHECK (true);
-- simplicity_validated_rows
DROP POLICY IF EXISTS service_simplicity_validated_rows_all ON intake.simplicity_validated_rows;
CREATE POLICY service_simplicity_validated_rows_all ON intake.simplicity_validated_rows FOR ALL TO service_role USING (true) WITH CHECK (true);
-- simplicity_failed_rows
DROP POLICY IF EXISTS service_simplicity_failed_rows_all ON intake.simplicity_failed_rows;
CREATE POLICY service_simplicity_failed_rows_all ON intake.simplicity_failed_rows FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ===========================================================================
-- 4. Grant service_role full access on tables (for backend workers)
-- ===========================================================================
GRANT ALL ON intake.simplicity_batches TO service_role;
GRANT ALL ON intake.simplicity_raw_rows TO service_role;
GRANT ALL ON intake.simplicity_validated_rows TO service_role;
GRANT ALL ON intake.simplicity_failed_rows TO service_role;
-- ===========================================================================
-- 5. Grant SELECT on views to authenticated/dragonfly_app (dashboard reads)
-- ===========================================================================
-- Batch progress view (main dashboard view)
GRANT SELECT ON intake.view_batch_progress TO authenticated;
GRANT SELECT ON intake.view_batch_progress TO dragonfly_app;
GRANT SELECT ON intake.view_batch_progress TO service_role;
-- Batch status view (if exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_views
    WHERE schemaname = 'intake'
        AND viewname = 'v_simplicity_batch_status'
) THEN EXECUTE 'GRANT SELECT ON intake.v_simplicity_batch_status TO authenticated';
EXECUTE 'GRANT SELECT ON intake.v_simplicity_batch_status TO dragonfly_app';
EXECUTE 'GRANT SELECT ON intake.v_simplicity_batch_status TO service_role';
END IF;
END $$;
-- ===========================================================================
-- 6. UNIQUE constraint on simplicity_validated_rows (batch_id, case_number)
-- Prevents validating the same case number twice within a batch
-- ===========================================================================
-- Add unique index if not exists
CREATE UNIQUE INDEX IF NOT EXISTS uq_simplicity_validated_batch_case ON intake.simplicity_validated_rows(batch_id, case_number)
WHERE case_number IS NOT NULL;
COMMENT ON INDEX intake.uq_simplicity_validated_batch_case IS 'Ensures each case number appears at most once per batch';
-- ===========================================================================
-- 7. Document the security model
-- ===========================================================================
COMMENT ON TABLE intake.simplicity_batches IS 'Intake batch tracking. RLS: service_role ONLY (Default Deny to anon/authenticated)';
COMMENT ON TABLE intake.simplicity_raw_rows IS 'Raw CSV rows staged for validation. RLS: service_role ONLY';
COMMENT ON TABLE intake.simplicity_validated_rows IS 'Validated rows ready for processing. RLS: service_role ONLY';
COMMENT ON TABLE intake.simplicity_failed_rows IS 'Failed rows with error details. RLS: service_role ONLY';
-- ===========================================================================
-- Done: Service-Role Only Architecture Complete
-- ===========================================================================
-- UI (anon/authenticated) reads ONLY through views: view_batch_progress
-- Backend (service_role) has exclusive write access to tables
-- RLS Default Deny protects even if grants are misconfigured
-- ===========================================================================
