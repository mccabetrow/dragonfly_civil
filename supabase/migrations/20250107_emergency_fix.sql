-- 20250107_emergency_fix.sql
-- ============================================================================
-- EMERGENCY FIX: Go-Live Critical Blockers
-- ============================================================================
--
-- This migration fixes three critical blockers for production go-live:
--
--   1. RLS VIOLATION: API user cannot write to intake.simplicity_batches
--      Fix: Add policies for authenticated + service_role INSERT/SELECT/UPDATE
--
--   2. SCHEMA DRIFT: public.judgments missing dedupe_key column
--      Fix: Idempotently add dedupe_key, backfill, add UNIQUE index
--
--   3. PERMISSION GAPS: Explicit grants on intake schema
--      Fix: GRANT ALL ON SCHEMA + ALL TABLES to postgres, authenticated, service_role
--
-- Author: Dragonfly Reliability Engineering
-- Created: 2025-01-07
-- ============================================================================
-- ============================================================================
-- SECTION 1: FIX RLS POLICIES ON INTAKE TABLES
-- ============================================================================
-- The API uses the service key (service_role) for writes, but RLS was blocking.
-- We also enable authenticated for future dashboard writes if needed.
-- 1A: DROP existing restrictive policies (if any conflict)
DROP POLICY IF EXISTS service_simplicity_batches_all ON intake.simplicity_batches;
DROP POLICY IF EXISTS authenticated_simplicity_batches_read ON intake.simplicity_batches;
DROP POLICY IF EXISTS authenticated_simplicity_batches_write ON intake.simplicity_batches;
DROP POLICY IF EXISTS service_simplicity_batches_insert ON intake.simplicity_batches;
DROP POLICY IF EXISTS service_simplicity_batches_select ON intake.simplicity_batches;
DROP POLICY IF EXISTS service_simplicity_batches_update ON intake.simplicity_batches;
-- 1B: Create permissive policies for service_role (full CRUD)
CREATE POLICY service_simplicity_batches_all ON intake.simplicity_batches FOR ALL TO service_role USING (true) WITH CHECK (true);
-- 1C: Create permissive policies for authenticated (INSERT/SELECT/UPDATE for API calls)
CREATE POLICY authenticated_simplicity_batches_insert ON intake.simplicity_batches FOR
INSERT TO authenticated WITH CHECK (true);
CREATE POLICY authenticated_simplicity_batches_select ON intake.simplicity_batches FOR
SELECT TO authenticated USING (true);
CREATE POLICY authenticated_simplicity_batches_update ON intake.simplicity_batches FOR
UPDATE TO authenticated USING (true) WITH CHECK (true);
-- 1D: Same for related intake tables (if they exist)
DO $$ BEGIN -- simplicity_raw_rows
IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'intake'
        AND tablename = 'simplicity_raw_rows'
) THEN DROP POLICY IF EXISTS service_simplicity_raw_rows_all ON intake.simplicity_raw_rows;
CREATE POLICY service_simplicity_raw_rows_all ON intake.simplicity_raw_rows FOR ALL TO service_role USING (true) WITH CHECK (true);
END IF;
-- simplicity_validated_rows
IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'intake'
        AND tablename = 'simplicity_validated_rows'
) THEN DROP POLICY IF EXISTS service_simplicity_validated_rows_all ON intake.simplicity_validated_rows;
CREATE POLICY service_simplicity_validated_rows_all ON intake.simplicity_validated_rows FOR ALL TO service_role USING (true) WITH CHECK (true);
END IF;
-- simplicity_failed_rows
IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'intake'
        AND tablename = 'simplicity_failed_rows'
) THEN DROP POLICY IF EXISTS service_simplicity_failed_rows_all ON intake.simplicity_failed_rows;
CREATE POLICY service_simplicity_failed_rows_all ON intake.simplicity_failed_rows FOR ALL TO service_role USING (true) WITH CHECK (true);
END IF;
-- row_errors (if exists)
IF EXISTS (
    SELECT 1
    FROM pg_tables
    WHERE schemaname = 'intake'
        AND tablename = 'row_errors'
) THEN DROP POLICY IF EXISTS service_row_errors_all ON intake.row_errors;
CREATE POLICY service_row_errors_all ON intake.row_errors FOR ALL TO service_role USING (true) WITH CHECK (true);
END IF;
RAISE NOTICE 'RLS policies fixed for intake tables';
END $$;
-- ============================================================================
-- SECTION 2: REPAIR SCHEMA DRIFT - public.judgments.dedupe_key
-- ============================================================================
-- This is idempotent - safe to run multiple times.
-- 2A: Ensure normalize_party_name function exists
CREATE OR REPLACE FUNCTION public.normalize_party_name(p_name TEXT) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
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
-- 2B: Ensure compute_judgment_dedupe_key function exists
CREATE OR REPLACE FUNCTION public.compute_judgment_dedupe_key(
        p_case_number TEXT,
        p_defendant_name TEXT
    ) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
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
-- 2C: Add dedupe_key column to public.judgments if missing
DO $$
DECLARE is_generated BOOLEAN := FALSE;
BEGIN -- Check if column exists
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'dedupe_key'
) THEN -- Add as GENERATED ALWAYS column
ALTER TABLE public.judgments
ADD COLUMN dedupe_key TEXT GENERATED ALWAYS AS (
        public.compute_judgment_dedupe_key(case_number, defendant_name)
    ) STORED;
RAISE NOTICE 'Added dedupe_key GENERATED column to public.judgments';
ELSE -- Column exists - check if it's GENERATED
SELECT (
        attgenerated IS NOT NULL
        AND attgenerated != ''
    ) INTO is_generated
FROM pg_attribute
WHERE attrelid = 'public.judgments'::regclass
    AND attname = 'dedupe_key';
IF is_generated THEN RAISE NOTICE 'dedupe_key is GENERATED ALWAYS - skipping backfill';
ELSE -- Regular column - backfill NULL values
UPDATE public.judgments
SET dedupe_key = public.compute_judgment_dedupe_key(case_number, defendant_name)
WHERE dedupe_key IS NULL;
RAISE NOTICE 'Backfilled NULL dedupe_key values';
END IF;
END IF;
END $$;
-- 2D: Create UNIQUE index on dedupe_key (non-concurrent since we're in transaction)
-- Use IF NOT EXISTS pattern
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'public'
        AND tablename = 'judgments'
        AND indexname = 'idx_judgments_dedupe_key'
) THEN CREATE UNIQUE INDEX idx_judgments_dedupe_key ON public.judgments (dedupe_key)
WHERE dedupe_key IS NOT NULL;
RAISE NOTICE 'Created unique index idx_judgments_dedupe_key';
ELSE RAISE NOTICE 'Index idx_judgments_dedupe_key already exists';
END IF;
-- Also create secondary unique constraint index if not exists
IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE schemaname = 'public'
        AND tablename = 'judgments'
        AND indexname = 'uq_judgments_dedupe_key'
) THEN CREATE UNIQUE INDEX uq_judgments_dedupe_key ON public.judgments (dedupe_key)
WHERE dedupe_key IS NOT NULL;
RAISE NOTICE 'Created unique index uq_judgments_dedupe_key';
ELSE RAISE NOTICE 'Index uq_judgments_dedupe_key already exists';
END IF;
END $$;
COMMENT ON COLUMN public.judgments.dedupe_key IS 'Deterministic dedupe key: UPPER(case_number)|NORMALIZED(defendant). Emergency fix 2025-01-07.';
-- ============================================================================
-- SECTION 3: EXPLICIT GRANTS ON INTAKE SCHEMA
-- ============================================================================
-- Ensure postgres, authenticated, and service_role have full access.
-- 3A: Schema-level grants
GRANT USAGE ON SCHEMA intake TO postgres;
GRANT USAGE ON SCHEMA intake TO authenticated;
GRANT USAGE ON SCHEMA intake TO service_role;
GRANT ALL ON SCHEMA intake TO postgres;
GRANT ALL ON SCHEMA intake TO service_role;
-- 3B: Table-level grants (all tables in intake schema)
GRANT ALL ON ALL TABLES IN SCHEMA intake TO postgres;
GRANT ALL ON ALL TABLES IN SCHEMA intake TO service_role;
-- Authenticated gets SELECT + INSERT + UPDATE (no DELETE for safety)
GRANT SELECT,
    INSERT,
    UPDATE ON ALL TABLES IN SCHEMA intake TO authenticated;
-- 3C: Sequence grants (for serial columns)
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO postgres;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO authenticated;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO service_role;
-- 3D: Future table grants (for tables created later)
ALTER DEFAULT PRIVILEGES IN SCHEMA intake
GRANT ALL ON TABLES TO postgres;
ALTER DEFAULT PRIVILEGES IN SCHEMA intake
GRANT ALL ON TABLES TO service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA intake
GRANT SELECT,
    INSERT,
    UPDATE ON TABLES TO authenticated;
-- 3E: Function execution grants
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA intake TO postgres;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA intake TO authenticated;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA intake TO service_role;
GRANT EXECUTE ON FUNCTION public.normalize_party_name(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.normalize_party_name(TEXT) TO authenticated;
GRANT EXECUTE ON FUNCTION public.compute_judgment_dedupe_key(TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.compute_judgment_dedupe_key(TEXT, TEXT) TO authenticated;
DO $$ BEGIN RAISE NOTICE 'Grants applied to intake schema and functions';
END $$;
-- ============================================================================
-- SECTION 4: VERIFICATION
-- ============================================================================
DO $$
DECLARE policy_count INT;
col_exists BOOLEAN;
idx_count INT;
BEGIN -- Count RLS policies on simplicity_batches
SELECT COUNT(*) INTO policy_count
FROM pg_policies
WHERE schemaname = 'intake'
    AND tablename = 'simplicity_batches';
-- Check dedupe_key column
SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
            AND table_name = 'judgments'
            AND column_name = 'dedupe_key'
    ) INTO col_exists;
-- Count dedupe indexes
SELECT COUNT(*) INTO idx_count
FROM pg_indexes
WHERE schemaname = 'public'
    AND tablename = 'judgments'
    AND indexname LIKE '%dedupe_key%';
RAISE NOTICE '================================================';
RAISE NOTICE 'EMERGENCY FIX VERIFICATION:';
RAISE NOTICE '  RLS policies on simplicity_batches: %',
policy_count;
RAISE NOTICE '  dedupe_key column exists: %',
col_exists;
RAISE NOTICE '  dedupe_key indexes: %',
idx_count;
RAISE NOTICE '================================================';
IF policy_count >= 2
AND col_exists
AND idx_count >= 1 THEN RAISE NOTICE '✅ EMERGENCY FIX APPLIED SUCCESSFULLY';
ELSE RAISE WARNING '⚠️ PARTIAL FIX - Review verification counts';
END IF;
END $$;
-- ============================================================================
-- END OF EMERGENCY FIX MIGRATION
-- ============================================================================