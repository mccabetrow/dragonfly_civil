-- =============================================================================
-- Migration: 20260114_plaintiff_intake_moat.sql
-- Purpose: Plaintiff Intake Moat - idempotent batch ingestion infrastructure
-- Author: Lead Engineer
-- Date: 2026-01-14
-- =============================================================================
--
-- DESIGN PRINCIPLES:
--   1. Every import is idempotent and auditable
--   2. Same file imported twice = no duplicates, second run is a no-op
--   3. Same plaintiff appearing in multiple files = deduplicated by dedupe_key
--   4. Every INSERT uses ON CONFLICT DO NOTHING semantics
--   5. Full audit trail via ingest.import_runs and plaintiffs_raw
--
-- IDEMPOTENCY MODEL:
--   - Batch level: ingest.import_runs has UNIQUE(source_system, source_batch_id, source_file_hash)
--   - Row level: ingest.plaintiffs_raw has UNIQUE(dedupe_key)
--   - Final table: public.plaintiffs has UNIQUE(dedupe_key) via existing migration
--
-- WORKFLOW:
--   1. Compute SHA-256 hash of the CSV file
--   2. Attempt INSERT into ingest.import_runs with ON CONFLICT DO NOTHING
--   3. If row inserted, parse CSV and insert each row into ingest.plaintiffs_raw
--   4. Each plaintiff_raw row has a deterministic dedupe_key
--   5. Downstream pipeline promotes from plaintiffs_raw to public.plaintiffs
--
-- ROLLBACK:
--   DROP TABLE IF EXISTS ingest.plaintiffs_raw;
--   -- Remove new columns/constraints from ingest.import_runs if needed
--
-- =============================================================================
BEGIN;
-- =============================================================================
-- STEP 1: Ensure ingest schema exists (idempotent)
-- =============================================================================
CREATE SCHEMA IF NOT EXISTS ingest;
COMMENT ON SCHEMA ingest IS 'Ingestion tracking schema for exactly-once batch processing.';
-- =============================================================================
-- STEP 2: Extend ingest.import_runs with batch-level idempotency columns
-- =============================================================================
-- Add source_system if missing
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'source_system'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN source_system text;
RAISE NOTICE '✓ Added column source_system to ingest.import_runs';
END IF;
END $$;
-- Add source_file_hash if missing (distinct from file_hash if legacy)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'source_file_hash'
) THEN -- If file_hash already exists and serves same purpose, we alias via computed column
-- Otherwise, add as distinct column for clarity
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'file_hash'
) THEN -- file_hash exists, add alias
ALTER TABLE ingest.import_runs
ADD COLUMN source_file_hash text GENERATED ALWAYS AS (file_hash) STORED;
RAISE NOTICE '✓ Added computed column source_file_hash as alias to file_hash';
ELSE
ALTER TABLE ingest.import_runs
ADD COLUMN source_file_hash text;
RAISE NOTICE '✓ Added column source_file_hash to ingest.import_runs';
END IF;
END IF;
END $$;
-- Add filename if missing
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'filename'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN filename text;
RAISE NOTICE '✓ Added column filename to ingest.import_runs';
END IF;
END $$;
-- Add import_kind if missing (e.g., 'plaintiff', 'judgment', 'enrichment')
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'import_kind'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN import_kind text DEFAULT 'plaintiff';
RAISE NOTICE '✓ Added column import_kind to ingest.import_runs';
END IF;
END $$;
-- Add stats columns if missing
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'rows_fetched'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN rows_fetched integer DEFAULT 0;
RAISE NOTICE '✓ Added column rows_fetched';
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'rows_inserted'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN rows_inserted integer DEFAULT 0;
RAISE NOTICE '✓ Added column rows_inserted';
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'rows_skipped'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN rows_skipped integer DEFAULT 0;
RAISE NOTICE '✓ Added column rows_skipped';
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'rows_errored'
) THEN
ALTER TABLE ingest.import_runs
ADD COLUMN rows_errored integer DEFAULT 0;
RAISE NOTICE '✓ Added column rows_errored';
END IF;
END $$;
-- =============================================================================
-- STEP 3: Create unique constraint for batch-level idempotency
-- =============================================================================
-- Prevents re-importing the exact same batch (source_system + batch_id + file_hash)
-- Note: source_batch_id already has a unique constraint, but we want the triple
DO $$ BEGIN -- First, ensure source_system has a value for existing rows (default 'unknown')
UPDATE ingest.import_runs
SET source_system = 'unknown'
WHERE source_system IS NULL;
-- Check if file_hash is the base column (not source_file_hash as generated)
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ingest'
        AND table_name = 'import_runs'
        AND column_name = 'source_file_hash'
        AND is_generated = 'ALWAYS'
) THEN -- source_file_hash is generated from file_hash, use file_hash in constraint
IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'import_runs_batch_idempotency_key'
        AND conrelid = 'ingest.import_runs'::regclass
) THEN
ALTER TABLE ingest.import_runs
ADD CONSTRAINT import_runs_batch_idempotency_key UNIQUE (source_system, source_batch_id, file_hash);
RAISE NOTICE '✓ Created unique constraint import_runs_batch_idempotency_key (using file_hash)';
ELSE RAISE NOTICE '○ Constraint import_runs_batch_idempotency_key already exists';
END IF;
ELSE -- source_file_hash is a regular column
IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'import_runs_batch_idempotency_key'
        AND conrelid = 'ingest.import_runs'::regclass
) THEN -- Ensure source_file_hash is not null for existing rows
UPDATE ingest.import_runs
SET source_file_hash = 'legacy-' || id::text
WHERE source_file_hash IS NULL;
ALTER TABLE ingest.import_runs
ADD CONSTRAINT import_runs_batch_idempotency_key UNIQUE (source_system, source_batch_id, source_file_hash);
RAISE NOTICE '✓ Created unique constraint import_runs_batch_idempotency_key';
ELSE RAISE NOTICE '○ Constraint import_runs_batch_idempotency_key already exists';
END IF;
END IF;
END $$;
-- =============================================================================
-- STEP 4: Create plaintiffs_raw landing table
-- =============================================================================
CREATE TABLE IF NOT EXISTS ingest.plaintiffs_raw (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Ingest tracking
    import_run_id uuid NOT NULL REFERENCES ingest.import_runs(id) ON DELETE CASCADE,
    row_index integer NOT NULL,
    -- 0-based position in source CSV
    -- Raw data from source (canonicalized, not transformed)
    plaintiff_name text NOT NULL,
    plaintiff_name_normalized text GENERATED ALWAYS AS (
        regexp_replace(lower(trim(plaintiff_name)), '\s+', ' ', 'g')
    ) STORED,
    firm_name text,
    short_name text,
    -- Contact info (denormalized for raw capture)
    contact_name text,
    contact_email text,
    contact_phone text,
    contact_address text,
    -- Source metadata
    source_system text NOT NULL,
    source_reference text,
    -- External ID from source system
    -- Raw payload for debugging/auditing
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Deduplication
    dedupe_key text NOT NULL,
    -- Deterministic key for row-level dedup
    -- Processing status
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'processing',
            'promoted',
            'failed',
            'skipped'
        )
    ),
    promoted_at timestamptz,
    promoted_plaintiff_id uuid,
    -- FK to public.plaintiffs after promotion
    -- Error tracking
    error_code text,
    error_message text,
    -- Audit
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- Row-level idempotency constraint
    CONSTRAINT plaintiffs_raw_dedupe_key_unique UNIQUE (dedupe_key)
);
COMMENT ON TABLE ingest.plaintiffs_raw IS 'Landing zone for raw plaintiff records. Append-only with ON CONFLICT DO NOTHING semantics.';
COMMENT ON COLUMN ingest.plaintiffs_raw.dedupe_key IS 'Deterministic key: SHA-256(source_system || "|" || normalized_name || "|" || coalesce(contact_email, ""))';
COMMENT ON COLUMN ingest.plaintiffs_raw.status IS 'Processing status: pending (new), processing (in-flight), promoted (moved to public.plaintiffs), failed (error), skipped (duplicate).';
-- =============================================================================
-- STEP 5: Create indexes for plaintiffs_raw
-- =============================================================================
-- Query pattern: Find pending records for promotion pipeline
CREATE INDEX IF NOT EXISTS idx_plaintiffs_raw_status_pending ON ingest.plaintiffs_raw (status, created_at)
WHERE status = 'pending';
-- Query pattern: Lookup by source system + reference
CREATE INDEX IF NOT EXISTS idx_plaintiffs_raw_source_lookup ON ingest.plaintiffs_raw (source_system, source_reference)
WHERE source_reference IS NOT NULL;
-- Query pattern: Track records by import run
CREATE INDEX IF NOT EXISTS idx_plaintiffs_raw_import_run ON ingest.plaintiffs_raw (import_run_id);
-- Query pattern: Join by normalized name for merge detection
CREATE INDEX IF NOT EXISTS idx_plaintiffs_raw_name_normalized ON ingest.plaintiffs_raw (plaintiff_name_normalized);
-- Query pattern: Find promoted records by plaintiff_id
CREATE INDEX IF NOT EXISTS idx_plaintiffs_raw_promoted_plaintiff ON ingest.plaintiffs_raw (promoted_plaintiff_id)
WHERE promoted_plaintiff_id IS NOT NULL;
-- =============================================================================
-- STEP 6: Create indexes on ingest.import_runs for common queries
-- =============================================================================
-- Query pattern: Find pending runs by source
CREATE INDEX IF NOT EXISTS idx_import_runs_source_status ON ingest.import_runs (source_system, status);
-- Query pattern: Recent runs ordered by time
CREATE INDEX IF NOT EXISTS idx_import_runs_created_at_desc ON ingest.import_runs (created_at DESC);
-- Query pattern: Find by import_kind
CREATE INDEX IF NOT EXISTS idx_import_runs_import_kind ON ingest.import_runs (import_kind);
-- =============================================================================
-- STEP 7: Create helper functions for dedupe key computation
-- =============================================================================
-- Compute plaintiff dedupe key (deterministic, reproducible)
CREATE OR REPLACE FUNCTION ingest.compute_plaintiff_dedupe_key(
        p_source_system text,
        p_name text,
        p_contact_email text DEFAULT NULL
    ) RETURNS text LANGUAGE plpgsql IMMUTABLE AS $$
DECLARE v_normalized_name text;
v_normalized_email text;
v_composite text;
BEGIN -- Normalize name: lowercase, collapse whitespace
v_normalized_name := regexp_replace(
    lower(trim(COALESCE(p_name, ''))),
    '\s+',
    ' ',
    'g'
);
-- Normalize email: lowercase, trim
v_normalized_email := lower(trim(COALESCE(p_contact_email, '')));
-- Composite key: source|name|email
v_composite := COALESCE(p_source_system, 'unknown') || '|' || v_normalized_name || '|' || v_normalized_email;
-- Return SHA-256 hash for fixed-length key
RETURN encode(sha256(v_composite::bytea), 'hex');
END;
$$;
COMMENT ON FUNCTION ingest.compute_plaintiff_dedupe_key(text, text, text) IS 'Computes deterministic dedupe key for plaintiff records: SHA-256(source|normalized_name|normalized_email)';
-- =============================================================================
-- STEP 8: Create trigger for updated_at on plaintiffs_raw
-- =============================================================================
CREATE OR REPLACE FUNCTION ingest.set_plaintiffs_raw_updated_at() RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_plaintiffs_raw_updated_at ON ingest.plaintiffs_raw;
CREATE TRIGGER trg_plaintiffs_raw_updated_at BEFORE
UPDATE ON ingest.plaintiffs_raw FOR EACH ROW EXECUTE FUNCTION ingest.set_plaintiffs_raw_updated_at();
-- =============================================================================
-- STEP 9: Enable RLS on plaintiffs_raw
-- =============================================================================
ALTER TABLE ingest.plaintiffs_raw ENABLE ROW LEVEL SECURITY;
ALTER TABLE ingest.plaintiffs_raw FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS plaintiffs_raw_service_role_full ON ingest.plaintiffs_raw;
CREATE POLICY plaintiffs_raw_service_role_full ON ingest.plaintiffs_raw FOR ALL TO service_role USING (true) WITH CHECK (true);
-- =============================================================================
-- STEP 10: Grants
-- =============================================================================
GRANT USAGE ON SCHEMA ingest TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE ingest.plaintiffs_raw TO service_role;
GRANT EXECUTE ON FUNCTION ingest.compute_plaintiff_dedupe_key(text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION ingest.set_plaintiffs_raw_updated_at() TO service_role;
-- Grant to dragonfly_app if it exists
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT USAGE ON SCHEMA ingest TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE ingest.import_runs TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE ingest.plaintiffs_raw TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ingest.compute_plaintiff_dedupe_key(text, text, text) TO dragonfly_app;
RAISE NOTICE '✓ Granted ingest access to dragonfly_app';
END IF;
END $$;
-- Revoke from public/anon/authenticated
REVOKE ALL ON TABLE ingest.plaintiffs_raw
FROM PUBLIC,
    anon,
    authenticated;
-- =============================================================================
-- STEP 11: Create helper view for operator queries
-- =============================================================================
CREATE OR REPLACE VIEW ingest.v_import_runs_summary AS
SELECT ir.id,
    ir.source_system,
    ir.source_batch_id,
    ir.import_kind,
    ir.filename,
    ir.status,
    ir.rows_fetched,
    ir.rows_inserted,
    ir.rows_skipped,
    ir.rows_errored,
    ir.created_at,
    ir.completed_at,
    EXTRACT(
        EPOCH
        FROM (ir.completed_at - ir.created_at)
    ) AS duration_seconds,
    COALESCE(ir.error_details->>'message', NULL) AS error_message
FROM ingest.import_runs ir
ORDER BY ir.created_at DESC;
COMMENT ON VIEW ingest.v_import_runs_summary IS 'Summary view of import runs for operator dashboards.';
GRANT SELECT ON ingest.v_import_runs_summary TO service_role;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT SELECT ON ingest.v_import_runs_summary TO dragonfly_app;
END IF;
END $$;
-- =============================================================================
-- STEP 12: Create view for blocked duplicates
-- =============================================================================
CREATE OR REPLACE VIEW ingest.v_blocked_duplicates AS
SELECT pr.dedupe_key,
    pr.plaintiff_name,
    pr.source_system,
    pr.source_reference,
    pr.import_run_id,
    ir.filename,
    pr.created_at,
    pr.status,
    pr.error_code
FROM ingest.plaintiffs_raw pr
    JOIN ingest.import_runs ir ON ir.id = pr.import_run_id
WHERE pr.status = 'skipped'
    OR pr.error_code = 'DUPLICATE'
ORDER BY pr.created_at DESC;
COMMENT ON VIEW ingest.v_blocked_duplicates IS 'Records that were blocked due to duplicate dedupe_key.';
GRANT SELECT ON ingest.v_blocked_duplicates TO service_role;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT SELECT ON ingest.v_blocked_duplicates TO dragonfly_app;
END IF;
END $$;
-- =============================================================================
-- STEP 13: Create view for errored rows
-- =============================================================================
CREATE OR REPLACE VIEW ingest.v_errored_rows AS
SELECT pr.id,
    pr.import_run_id,
    ir.filename,
    ir.source_system,
    pr.row_index,
    pr.plaintiff_name,
    pr.error_code,
    pr.error_message,
    pr.raw_payload,
    pr.created_at
FROM ingest.plaintiffs_raw pr
    JOIN ingest.import_runs ir ON ir.id = pr.import_run_id
WHERE pr.status = 'failed'
ORDER BY pr.created_at DESC;
COMMENT ON VIEW ingest.v_errored_rows IS 'Records that failed processing with error details.';
GRANT SELECT ON ingest.v_errored_rows TO service_role;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT SELECT ON ingest.v_errored_rows TO dragonfly_app;
END IF;
END $$;
-- =============================================================================
-- VERIFICATION
-- =============================================================================
DO $$ BEGIN RAISE NOTICE '✅ Plaintiff Intake Moat migration complete';
RAISE NOTICE '';
RAISE NOTICE 'Tables created/updated:';
RAISE NOTICE '  • ingest.import_runs (extended with source_system, file_hash idempotency)';
RAISE NOTICE '  • ingest.plaintiffs_raw (new landing zone)';
RAISE NOTICE '';
RAISE NOTICE 'Idempotency guarantees:';
RAISE NOTICE '  • Batch level: UNIQUE(source_system, source_batch_id, file_hash)';
RAISE NOTICE '  • Row level: UNIQUE(dedupe_key) on plaintiffs_raw';
RAISE NOTICE '';
RAISE NOTICE 'Views for operators:';
RAISE NOTICE '  • ingest.v_import_runs_summary';
RAISE NOTICE '  • ingest.v_blocked_duplicates';
RAISE NOTICE '  • ingest.v_errored_rows';
END $$;
COMMIT;
-- =============================================================================
-- OPERATOR QUERIES (for reference)
-- =============================================================================
/*
 -- Show last 10 import runs
 SELECT * FROM ingest.v_import_runs_summary LIMIT 10;
 
 -- Find duplicates blocked
 SELECT * FROM ingest.v_blocked_duplicates LIMIT 50;
 
 -- Show errored rows
 SELECT * FROM ingest.v_errored_rows LIMIT 50;
 
 -- Check batch idempotency constraint
 SELECT 
 source_system,
 source_batch_id,
 file_hash,
 COUNT(*) as run_count
 FROM ingest.import_runs
 GROUP BY source_system, source_batch_id, file_hash
 HAVING COUNT(*) > 1;
 
 -- Check row-level dedupe stats for a specific run
 SELECT 
 ir.id,
 ir.filename,
 COUNT(pr.id) as total_rows,
 COUNT(CASE WHEN pr.status = 'pending' THEN 1 END) as pending,
 COUNT(CASE WHEN pr.status = 'promoted' THEN 1 END) as promoted,
 COUNT(CASE WHEN pr.status = 'skipped' THEN 1 END) as skipped,
 COUNT(CASE WHEN pr.status = 'failed' THEN 1 END) as failed
 FROM ingest.import_runs ir
 LEFT JOIN ingest.plaintiffs_raw pr ON pr.import_run_id = ir.id
 GROUP BY ir.id, ir.filename
 ORDER BY ir.created_at DESC
 LIMIT 10;
 */
-- =============================================================================