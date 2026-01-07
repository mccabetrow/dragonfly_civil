-- 20250106000000_repair_schema_drift.sql
-- ============================================================================
-- REPAIR: Schema Drift Fix for Missing Dedupe Infrastructure
-- ============================================================================
--
-- Problem:
--   Migration history claims 20250101... applied, but production is missing:
--     1. public.normalize_party_name() function
--     2. public.compute_judgment_dedupe_key() function
--     3. dedupe_key column on public.plaintiffs
--     4. dedupe_key column on public.judgments
--     5. Unique indexes on dedupe_key columns
--
-- Solution:
--   CREATE OR REPLACE + IF NOT EXISTS for idempotent repair.
--   Safe to run multiple times in any environment.
--
-- Author: Dragonfly Reliability Engineering
-- Created: 2025-01-06
-- ============================================================================
-- ============================================================================
-- 1. FUNCTIONS: Create or replace core dedupe functions
-- ============================================================================
-- NOTE: DROP CASCADE is needed because existing function has different parameter name (raw vs p_name)
-- PostgreSQL does not allow CREATE OR REPLACE to change parameter names.
DROP FUNCTION IF EXISTS public.normalize_party_name(TEXT) CASCADE;
-- normalize_party_name: Uppercase + whitespace normalized, corporate suffix trimmed
CREATE OR REPLACE FUNCTION public.normalize_party_name(p_name TEXT) RETURNS TEXT LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_name TEXT;
BEGIN IF p_name IS NULL THEN RETURN NULL;
END IF;
v_name := upper(trim(p_name));
IF v_name = '' THEN RETURN NULL;
END IF;
-- Strip corporate suffixes: LLC, INC, CORP, CO, LTD
v_name := regexp_replace(
    v_name,
    '\s+(LLC|INC|CORP|CO|LTD)\.?$',
    '',
    'gi'
);
v_name := regexp_replace(v_name, '\s+', ' ', 'g');
RETURN v_name;
END;
$$;
COMMENT ON FUNCTION public.normalize_party_name(TEXT) IS 'Uppercase + whitespace normalized name with corporate suffixes trimmed. Idempotent repair.';
-- compute_judgment_dedupe_key: Deterministic key = UPPER(case)|NORMALIZED(defendant)
DROP FUNCTION IF EXISTS public.compute_judgment_dedupe_key(TEXT, TEXT) CASCADE;
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
COMMENT ON FUNCTION public.compute_judgment_dedupe_key(TEXT, TEXT) IS 'Deterministic dedupe key: UPPER(case_number)|NORMALIZED(defendant). Idempotent repair.';
-- ============================================================================
-- 2. PLAINTIFFS: Add dedupe_key column if missing
-- ============================================================================
DO $$ BEGIN -- Check if column already exists
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
        AND column_name = 'dedupe_key'
) THEN -- Add generated column
ALTER TABLE public.plaintiffs
ADD COLUMN dedupe_key TEXT GENERATED ALWAYS AS (
        public.normalize_party_name(name)
    ) STORED;
RAISE NOTICE 'Added dedupe_key column to public.plaintiffs';
ELSE RAISE NOTICE 'dedupe_key column already exists on public.plaintiffs';
END IF;
END;
$$;
-- Create unique index if not exists (for plaintiffs)
CREATE UNIQUE INDEX IF NOT EXISTS idx_plaintiffs_dedupe_key ON public.plaintiffs (dedupe_key)
WHERE dedupe_key IS NOT NULL;
COMMENT ON COLUMN public.plaintiffs.dedupe_key IS 'Deterministic dedupe key derived from normalized plaintiff name. Repair migration.';
-- ============================================================================
-- 3. JUDGMENTS: Add dedupe_key column if missing
-- ============================================================================
DO $$ BEGIN -- Check if column already exists
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'dedupe_key'
) THEN -- Add generated column
ALTER TABLE public.judgments
ADD COLUMN dedupe_key TEXT GENERATED ALWAYS AS (
        public.compute_judgment_dedupe_key(case_number, defendant_name)
    ) STORED;
RAISE NOTICE 'Added dedupe_key column to public.judgments';
ELSE RAISE NOTICE 'dedupe_key column already exists on public.judgments';
END IF;
END;
$$;
-- Create unique index if not exists (for judgments)
CREATE UNIQUE INDEX IF NOT EXISTS idx_judgments_dedupe_key ON public.judgments (dedupe_key)
WHERE dedupe_key IS NOT NULL;
COMMENT ON COLUMN public.judgments.dedupe_key IS 'Deterministic dedupe key: UPPER(case_number)|NORMALIZED(defendant). Repair migration.';
-- ============================================================================
-- 4. GRANTS: Ensure service roles can use the functions
-- ============================================================================
GRANT EXECUTE ON FUNCTION public.normalize_party_name(TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION public.compute_judgment_dedupe_key(TEXT, TEXT) TO service_role;
-- Also grant to anon for RPC calls if needed
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'anon'
) THEN
GRANT EXECUTE ON FUNCTION public.normalize_party_name(TEXT) TO anon;
GRANT EXECUTE ON FUNCTION public.compute_judgment_dedupe_key(TEXT, TEXT) TO anon;
END IF;
END;
$$;
-- ============================================================================
-- 5. VERIFICATION: Log repair status
-- ============================================================================
DO $$
DECLARE fn_count INT;
col_count INT;
idx_count INT;
BEGIN -- Count functions
SELECT COUNT(*) INTO fn_count
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.proname IN (
        'normalize_party_name',
        'compute_judgment_dedupe_key'
    );
-- Count dedupe_key columns
SELECT COUNT(*) INTO col_count
FROM information_schema.columns
WHERE table_schema = 'public'
    AND column_name = 'dedupe_key'
    AND table_name IN ('plaintiffs', 'judgments');
-- Count dedupe indexes
SELECT COUNT(*) INTO idx_count
FROM pg_indexes
WHERE schemaname = 'public'
    AND indexname IN (
        'idx_plaintiffs_dedupe_key',
        'idx_judgments_dedupe_key'
    );
RAISE NOTICE '════════════════════════════════════════════════════════════════';
RAISE NOTICE 'SCHEMA DRIFT REPAIR COMPLETE';
RAISE NOTICE '  Functions: % / 2',
fn_count;
RAISE NOTICE '  Columns:   % / 2',
col_count;
RAISE NOTICE '  Indexes:   % / 2',
idx_count;
RAISE NOTICE '════════════════════════════════════════════════════════════════';
IF fn_count < 2
OR col_count < 2
OR idx_count < 2 THEN RAISE WARNING 'Schema repair incomplete - manual intervention may be required';
END IF;
END;
$$;
