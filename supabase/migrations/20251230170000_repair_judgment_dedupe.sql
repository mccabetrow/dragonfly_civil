-- 20251230170000_repair_judgment_dedupe.sql
-- REPAIR: Judgment Deduplication Drift
-- ============================================================================
--
-- Problem:
--   Migration history claims dedupe was applied, but production is missing:
--     1. dedupe_key column on public.judgments
--     2. Unique constraint on dedupe_key
--
-- Solution:
--   Idempotent repair with safe backfill and constraint creation.
--
-- Author: Dragonfly Reliability Engineering
-- Created: 2025-12-30
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. Ensure helper functions exist (idempotent with CREATE OR REPLACE)
-- ============================================================================
-- Note: Using same parameter names as existing functions to allow CREATE OR REPLACE
CREATE OR REPLACE FUNCTION public.normalize_party_name(p_name text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
SELECT regexp_replace(lower(trim(p_name)), '\s+', ' ', 'g');
$$;
COMMENT ON FUNCTION public.normalize_party_name(text) IS 'Normalize party name: lowercase, trim, collapse whitespace. Repair migration.';
CREATE OR REPLACE FUNCTION public.compute_judgment_dedupe_key(p_case_number text, p_defendant_name text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
SELECT md5(
        normalize_party_name(p_case_number) || '|' || normalize_party_name(p_defendant_name)
    );
$$;
COMMENT ON FUNCTION public.compute_judgment_dedupe_key(text, text) IS 'Compute judgment dedupe key as MD5 hash of normalized plaintiff|defendant. Repair migration.';
-- ============================================================================
-- 2. Add column safely (IF NOT EXISTS) - skip if already generated
-- ============================================================================
DO $$ BEGIN -- Only add if column doesn't exist at all
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'dedupe_key'
) THEN
ALTER TABLE public.judgments
ADD COLUMN dedupe_key text;
RAISE NOTICE 'Added dedupe_key column to public.judgments';
ELSE RAISE NOTICE 'dedupe_key column already exists on public.judgments';
END IF;
END $$;
-- ============================================================================
-- 3. Backfill data (only for non-generated columns)
-- ============================================================================
DO $$
DECLARE col_is_generated TEXT;
BEGIN
SELECT c.is_generated INTO col_is_generated
FROM information_schema.columns c
WHERE c.table_schema = 'public'
    AND c.table_name = 'judgments'
    AND c.column_name = 'dedupe_key';
IF col_is_generated = 'NEVER' THEN -- Only backfill if NOT a generated column
UPDATE public.judgments
SET dedupe_key = compute_judgment_dedupe_key(case_number, defendant_name)
WHERE dedupe_key IS NULL;
RAISE NOTICE 'Backfilled dedupe_key values';
ELSE RAISE NOTICE 'dedupe_key is GENERATED - no backfill needed';
END IF;
END $$;
-- ============================================================================
-- 4. Apply Unique Constraint (Safe Check)
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_indexes
    WHERE indexname = 'uq_judgments_dedupe_key'
) THEN CREATE UNIQUE INDEX uq_judgments_dedupe_key ON public.judgments (dedupe_key);
RAISE NOTICE 'Created unique index uq_judgments_dedupe_key';
ELSE RAISE NOTICE 'Index uq_judgments_dedupe_key already exists';
END IF;
END $$;
-- ============================================================================
-- 5. Grant permissions
-- ============================================================================
GRANT EXECUTE ON FUNCTION public.normalize_party_name(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.compute_judgment_dedupe_key(text, text) TO service_role;
-- ============================================================================
-- 6. Verification
-- ============================================================================
DO $$
DECLARE col_exists BOOLEAN;
idx_exists BOOLEAN;
null_count BIGINT;
BEGIN -- Check column exists
SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
            AND table_name = 'judgments'
            AND column_name = 'dedupe_key'
    ) INTO col_exists;
-- Check index exists
SELECT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'public'
            AND indexname = 'uq_judgments_dedupe_key'
    ) INTO idx_exists;
-- Count NULL dedupe_keys
SELECT COUNT(*) INTO null_count
FROM public.judgments
WHERE dedupe_key IS NULL;
RAISE NOTICE '════════════════════════════════════════════════════════════════';
RAISE NOTICE 'JUDGMENT DEDUPE REPAIR COMPLETE';
RAISE NOTICE '  Column exists: %',
col_exists;
RAISE NOTICE '  Index exists:  %',
idx_exists;
RAISE NOTICE '  NULL count:    %',
null_count;
RAISE NOTICE '════════════════════════════════════════════════════════════════';
IF NOT col_exists
OR NOT idx_exists
OR null_count > 0 THEN RAISE WARNING 'Repair incomplete - manual intervention may be required';
END IF;
END $$;
COMMIT;