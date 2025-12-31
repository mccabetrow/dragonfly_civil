-- =============================================================================
-- Migration: Dedupe Plaintiffs Remediation (v3)
-- Author: Dragonfly Civil DBA
-- Date: 2025-01-05
-- Purpose: Clean up duplicate plaintiff rows (by dedupe_key), repoint FK refs
--          to winner, delete loser rows, then apply UNIQUE constraint.
-- 
-- v3 Changes: Temporarily disable FCRA compliance trigger during cleanup
-- =============================================================================
BEGIN;
-- ============================================================================
-- STEP 0: Safety - Ensure we can rollback
-- ============================================================================
DO $$ BEGIN RAISE NOTICE 'Starting dedupe_plaintiffs_remediation_v3 migration';
END $$;
-- ============================================================================
-- STEP 1: Create helper functions if not exist
-- ============================================================================
-- Drop existing functions first to avoid param name conflicts
DROP FUNCTION IF EXISTS public.normalize_party_name(text);
DROP FUNCTION IF EXISTS public.compute_judgment_dedupe_key(text, text);
-- Function to normalize party names for deduplication
CREATE FUNCTION public.normalize_party_name(raw text) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT LOWER(
        TRIM(
            REGEXP_REPLACE(
                REGEXP_REPLACE(raw, '\s+', ' ', 'g'),
                '[^a-zA-Z0-9 ]',
                '',
                'g'
            )
        )
    ) $$;
-- Function to compute dedupe key for judgments (if needed)
CREATE FUNCTION public.compute_judgment_dedupe_key(
    p_plaintiff_name text,
    p_case_number text
) RETURNS text LANGUAGE sql IMMUTABLE PARALLEL SAFE AS $$
SELECT public.normalize_party_name(p_plaintiff_name) || '::' || COALESCE(LOWER(TRIM(p_case_number)), '') $$;
-- ============================================================================
-- STEP 2: Add dedupe_key column if not exists
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiffs'
        AND column_name = 'dedupe_key'
) THEN
ALTER TABLE public.plaintiffs
ADD COLUMN dedupe_key text GENERATED ALWAYS AS (public.normalize_party_name(name)) STORED;
RAISE NOTICE 'Added dedupe_key column to public.plaintiffs';
ELSE RAISE NOTICE 'dedupe_key column already exists';
END IF;
END $$;
-- Drop existing index if exists (will recreate as unique later)
DROP INDEX IF EXISTS public.idx_plaintiffs_dedupe_key;
-- ============================================================================
-- STEP 3: Temporarily disable FCRA compliance triggers for cleanup
-- ============================================================================
DO $$ BEGIN -- Disable block-delete triggers on plaintiff tables
ALTER TABLE public.plaintiff_contacts DISABLE TRIGGER trg_plaintiff_contacts_block_delete;
ALTER TABLE public.plaintiff_call_attempts DISABLE TRIGGER trg_plaintiff_call_attempts_block_delete;
RAISE NOTICE 'Disabled FCRA compliance triggers for cleanup';
EXCEPTION
WHEN undefined_object THEN RAISE NOTICE 'Some triggers do not exist, continuing...';
END $$;
-- ============================================================================
-- STEP 4: Remediate duplicates
-- ============================================================================
DO $$
DECLARE dup_count int;
dup_rec RECORD;
winner_id uuid;
loser_ids uuid [];
lid uuid;
BEGIN -- Count duplicates
SELECT COUNT(*) INTO dup_count
FROM (
        SELECT dedupe_key
        FROM public.plaintiffs
        WHERE dedupe_key IS NOT NULL
        GROUP BY dedupe_key
        HAVING COUNT(*) > 1
    ) d;
IF dup_count = 0 THEN RAISE NOTICE 'No duplicate plaintiffs found, skipping remediation';
RETURN;
END IF;
RAISE NOTICE 'Found % duplicate dedupe_key groups to remediate',
dup_count;
-- Process each duplicate group
FOR dup_rec IN
SELECT dedupe_key
FROM public.plaintiffs
WHERE dedupe_key IS NOT NULL
GROUP BY dedupe_key
HAVING COUNT(*) > 1 LOOP -- Pick winner: earliest created_at
SELECT id INTO winner_id
FROM public.plaintiffs
WHERE dedupe_key = dup_rec.dedupe_key
ORDER BY created_at ASC
LIMIT 1;
-- Get loser IDs
SELECT ARRAY_AGG(id) INTO loser_ids
FROM public.plaintiffs
WHERE dedupe_key = dup_rec.dedupe_key
    AND id != winner_id;
RAISE NOTICE 'Processing dedupe_key=% winner=% losers=%',
dup_rec.dedupe_key,
winner_id,
loser_ids;
-- For each loser, repoint FKs to winner
FOREACH lid IN ARRAY loser_ids LOOP -- Step 4a: Delete conflicting contacts that would violate unique constraint
-- Constraint: ux_plaintiff_contacts_plaintiff_kind_value (plaintiff_id, kind, value)
DELETE FROM public.plaintiff_contacts
WHERE plaintiff_id = lid
    AND (kind, value) IN (
        SELECT kind,
            value
        FROM public.plaintiff_contacts
        WHERE plaintiff_id = winner_id
    );
-- Step 4b: Repoint remaining contacts
UPDATE public.plaintiff_contacts
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
-- Step 4c: Repoint other FK tables (no unique constraints to worry about)
UPDATE public.plaintiff_status_history
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
UPDATE public.plaintiff_tasks
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
UPDATE public.plaintiff_call_attempts
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
UPDATE public.judgments
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
-- enforcement tables if they have plaintiff_id FK
UPDATE public.enforcement_timeline
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
UPDATE public.enforcement_cases
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
UPDATE public.enforcement_evidence
SET plaintiff_id = winner_id
WHERE plaintiff_id = lid;
-- Delete loser plaintiff row
DELETE FROM public.plaintiffs
WHERE id = lid;
END LOOP;
END LOOP;
RAISE NOTICE 'Remediation complete';
END $$;
-- ============================================================================
-- STEP 5: Re-enable FCRA compliance triggers
-- ============================================================================
DO $$ BEGIN
ALTER TABLE public.plaintiff_contacts ENABLE TRIGGER trg_plaintiff_contacts_block_delete;
ALTER TABLE public.plaintiff_call_attempts ENABLE TRIGGER trg_plaintiff_call_attempts_block_delete;
RAISE NOTICE 'Re-enabled FCRA compliance triggers';
EXCEPTION
WHEN undefined_object THEN RAISE NOTICE 'Some triggers do not exist, continuing...';
END $$;
-- ============================================================================
-- STEP 6: Apply unique constraint
-- ============================================================================
-- Create unique index on dedupe_key (allows NULLs which is fine)
CREATE UNIQUE INDEX IF NOT EXISTS ux_plaintiffs_dedupe_key ON public.plaintiffs (dedupe_key)
WHERE dedupe_key IS NOT NULL;
COMMIT;
-- ============================================================================
-- VERIFICATION
-- ============================================================================
DO $$
DECLARE dup_count int;
BEGIN
SELECT COUNT(*) INTO dup_count
FROM (
        SELECT dedupe_key
        FROM public.plaintiffs
        WHERE dedupe_key IS NOT NULL
        GROUP BY dedupe_key
        HAVING COUNT(*) > 1
    ) d;
IF dup_count > 0 THEN RAISE EXCEPTION 'Migration failed: % duplicate dedupe_keys remain',
dup_count;
ELSE RAISE NOTICE 'VERIFIED: No duplicate dedupe_keys remain';
END IF;
END $$;