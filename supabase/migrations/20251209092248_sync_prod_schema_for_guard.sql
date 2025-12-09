-- =============================================================================
-- Migration: Sync prod schema with dev for Schema Guard compatibility
-- =============================================================================
-- Purpose: Add columns and views required by recovery SQL files
-- 
-- This migration adds:
--   1. public.plaintiffs.tier (text, nullable, default='unknown')
--   2. public.judgments.priority_level (text, NOT NULL, default='normal')
--   3. public.v_migration_status view (for tools/migration_status.py)
--
-- Safe to run in both dev and prod:
--   - Uses ADD COLUMN IF NOT EXISTS
--   - Uses DROP VIEW IF EXISTS before CREATE VIEW
--   - Backfills existing rows with safe defaults
--
-- After this migration, the prod-skip guard in run_schema_repair.py can be removed.
-- =============================================================================
BEGIN;
-- ============================================================================
-- SECTION 1: public.plaintiffs.tier
-- ============================================================================
-- Add tier column to plaintiffs (nullable text with default)
-- Used by: enforcement.v_plaintiff_call_queue, v_candidate_wage_garnishments
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS tier text DEFAULT 'unknown';
-- Backfill any NULL values to 'unknown' for consistency
UPDATE public.plaintiffs
SET tier = 'unknown'
WHERE tier IS NULL;
COMMENT ON COLUMN public.plaintiffs.tier IS 'Plaintiff tier level (platinum, gold, silver, bronze, unknown). Used for call prioritization.';
-- ============================================================================
-- SECTION 2: public.judgments.priority_level
-- ============================================================================
-- Add priority_level column to judgments (NOT NULL text with default)
-- Used by: public.v_judgment_pipeline, analytics.v_collectability_scores
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS priority_level text DEFAULT 'normal';
-- Backfill any NULL or empty values to 'normal'
UPDATE public.judgments
SET priority_level = 'normal'
WHERE priority_level IS NULL
    OR trim(priority_level) = '';
-- Now make it NOT NULL (after backfill)
ALTER TABLE public.judgments
ALTER COLUMN priority_level
SET NOT NULL;
-- Also add priority_level_updated_at for tracking changes
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS priority_level_updated_at timestamptz DEFAULT now();
COMMENT ON COLUMN public.judgments.priority_level IS 'Priority level for enforcement (urgent, high, normal, low, on_hold). Default is normal.';
-- ============================================================================
-- SECTION 3: public.v_migration_status VIEW
-- ============================================================================
-- Required by: tools/migration_status.py
-- Unifies legacy (dragonfly_migrations) and Supabase CLI (schema_migrations) trackers
-- First ensure the base tables exist (defensive)
CREATE TABLE IF NOT EXISTS public.dragonfly_migrations (
    id serial PRIMARY KEY,
    migration_filename text NOT NULL UNIQUE,
    applied_at timestamptz NOT NULL DEFAULT now()
);
-- Drop and recreate the view (idempotent)
DROP VIEW IF EXISTS public.v_migration_status;
CREATE VIEW public.v_migration_status AS
SELECT 'legacy'::text AS source,
    COALESCE(
        LEFT(dm.migration_filename, 4),
        dm.migration_filename
    ) AS version,
    dm.migration_filename AS name,
    dm.applied_at AS executed_at,
    TRUE AS success
FROM public.dragonfly_migrations dm
UNION ALL
SELECT 'supabase'::text AS source,
    sm.version::text AS version,
    sm.name AS name,
    -- supabase_migrations.schema_migrations has timestamp as version
    to_timestamp(sm.version::text, 'YYYYMMDDHH24MISS') AS executed_at,
    TRUE AS success
FROM supabase_migrations.schema_migrations sm
WHERE sm.version ~ '^\d{14}$';
-- Only timestamp-formatted versions
-- Grant access
GRANT SELECT ON public.v_migration_status TO authenticated;
GRANT SELECT ON public.v_migration_status TO service_role;
GRANT SELECT ON public.v_migration_status TO anon;
COMMENT ON VIEW public.v_migration_status IS 'Unified migration status from legacy and Supabase CLI trackers. Query via REST: GET /rest/v1/v_migration_status';
-- ============================================================================
-- SECTION 4: Verify required columns exist (defensive check)
-- ============================================================================
-- These columns are also used by recovery SQL but may already exist
-- collectability_score on judgments (used by many views)
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS collectability_score numeric DEFAULT 0;
-- enforcement_stage on judgments (used by v_enforcement_overview)
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS enforcement_stage text DEFAULT 'intake';
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS enforcement_stage_updated_at timestamptz DEFAULT now();
COMMIT;
-- ============================================================================
-- POST-MIGRATION NOTES:
-- ============================================================================
-- After applying this migration to prod:
-- 
-- 1. Verify with: SELECT tier FROM public.plaintiffs LIMIT 1;
--                 SELECT priority_level FROM public.judgments LIMIT 1;
--                 SELECT * FROM public.v_migration_status LIMIT 5;
--
-- 2. Remove the prod-skip guard in tools/run_schema_repair.py (lines ~113-130)
--
-- 3. Test schema repair: 
--    SUPABASE_MODE=prod python tools/run_schema_repair.py --dry-run
--    SUPABASE_MODE=prod python tools/run_schema_repair.py
-- ============================================================================