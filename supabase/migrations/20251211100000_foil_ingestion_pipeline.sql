-- Migration: FOIL Ingestion Pipeline
-- Version: Dragonfly Engine v0.3.x
-- Description: Creates raw.foil_datasets schema for massive FOIL court data imports
-- ============================================================================
-- Business Purpose:
-- FOIL (Freedom of Information Law) requests return large dumps of raw court
-- data with varying schemas. This migration creates:
--   1. raw schema for unstructured/messy data
--   2. raw.foil_datasets table to store raw imports before mapping
--   3. raw.foil_column_mappings for dynamic column mapping configuration
--   4. Views for monitoring FOIL ingestion pipeline
-- ============================================================================
-- ============================================================================
-- 1. Create raw schema for unstructured data staging
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS raw;
COMMENT ON SCHEMA raw IS 'Staging area for raw, unstructured data imports (FOIL, court dumps, etc.)';
-- ============================================================================
-- 2. raw.foil_datasets - Store entire FOIL dataset metadata
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw.foil_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Dataset identification
    dataset_name TEXT NOT NULL,
    source_agency TEXT,
    -- e.g., 'NYC Civil Court', 'Nassau County'
    foil_request_id TEXT,
    -- Reference to the FOIL request that generated this
    -- File metadata
    original_filename TEXT NOT NULL,
    file_size_bytes BIGINT,
    row_count_raw INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    detected_columns JSONB NOT NULL DEFAULT '[]',
    -- Array of column names found
    -- Processing status
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'mapping',
            'processing',
            'completed',
            'failed',
            'partial'
        )
    ),
    -- Row counts after processing
    row_count_mapped INTEGER NOT NULL DEFAULT 0,
    row_count_valid INTEGER NOT NULL DEFAULT 0,
    row_count_invalid INTEGER NOT NULL DEFAULT 0,
    row_count_duplicate INTEGER NOT NULL DEFAULT 0,
    -- Column mapping (discovered or manual)
    column_mapping JSONB NOT NULL DEFAULT '{}',
    -- {"raw_col": "canonical_col", ...}
    mapping_confidence NUMERIC(5, 2),
    -- 0-100 confidence in auto-mapping
    mapping_locked_at TIMESTAMPTZ,
    -- When a human confirmed the mapping
    mapping_locked_by TEXT,
    -- Error handling
    error_summary TEXT,
    sample_errors JSONB DEFAULT '[]',
    -- First N errors for preview
    -- Batch link (if processed)
    ingest_batch_id UUID REFERENCES ops.ingest_batches(id),
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    created_by TEXT,
    -- Notes/metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}'
);
COMMENT ON TABLE raw.foil_datasets IS 'Tracks FOIL datasets with their raw column structure and mapping status';
COMMENT ON COLUMN raw.foil_datasets.detected_columns IS 'Array of column names found in the raw CSV';
COMMENT ON COLUMN raw.foil_datasets.column_mapping IS 'JSON mapping from raw columns to canonical judgment fields';
COMMENT ON COLUMN raw.foil_datasets.mapping_confidence IS 'Percentage confidence in auto-detected column mapping';
COMMENT ON COLUMN raw.foil_datasets.status IS 'pending=awaiting mapping, mapping=needs human review, processing=being imported, completed/failed/partial=done';
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_foil_datasets_status ON raw.foil_datasets(status);
CREATE INDEX IF NOT EXISTS idx_foil_datasets_created_at ON raw.foil_datasets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_foil_datasets_source_agency ON raw.foil_datasets(source_agency);
CREATE INDEX IF NOT EXISTS idx_foil_datasets_ingest_batch ON raw.foil_datasets(ingest_batch_id);
-- ============================================================================
-- 3. raw.foil_raw_rows - Store raw rows as JSONB for audit/reprocessing
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw.foil_raw_rows (
    id BIGSERIAL PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES raw.foil_datasets(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    raw_json JSONB NOT NULL,
    -- Validation status after mapping attempt
    validation_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        validation_status IN ('pending', 'valid', 'invalid', 'skipped')
    ),
    validation_errors TEXT [],
    -- Link to resulting judgment (if successfully mapped)
    judgment_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE raw.foil_raw_rows IS 'Raw FOIL CSV rows stored as JSONB for audit trail and reprocessing';
-- Indexes for efficient batch processing
CREATE INDEX IF NOT EXISTS idx_foil_raw_rows_dataset ON raw.foil_raw_rows(dataset_id);
CREATE INDEX IF NOT EXISTS idx_foil_raw_rows_dataset_row ON raw.foil_raw_rows(dataset_id, row_index);
CREATE INDEX IF NOT EXISTS idx_foil_raw_rows_status ON raw.foil_raw_rows(dataset_id, validation_status);
-- ============================================================================
-- 4. raw.foil_column_templates - Reusable column mappings per agency
-- ============================================================================
CREATE TABLE IF NOT EXISTS raw.foil_column_templates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Template identification
    template_name TEXT NOT NULL,
    source_agency TEXT,
    -- Optional: agency this template is for
    -- Column patterns for auto-detection
    -- Keys are canonical fields, values are arrays of possible raw column names
    column_patterns JSONB NOT NULL DEFAULT '{
        "case_number": ["Case Number", "Case No", "Case #", "CaseNo", "Case_Number", "CASENO"],
        "defendant_name": ["Defendant", "Def. Name", "DefName", "Defendant Name", "DEF_NAME"],
        "plaintiff_name": ["Plaintiff", "Plf. Name", "PlfName", "Plaintiff Name", "PLF_NAME"],
        "judgment_amount": ["Amt", "Amount", "Judgment Amount", "Judgment Amt", "JudgmentAmt", "AMOUNT"],
        "filing_date": ["Date Filed", "Filing Date", "FilingDate", "Filed Date", "DATE_FILED"],
        "judgment_date": ["Judgment Date", "Jdgmt Date", "JdgmtDate", "JUDGMENT_DATE"],
        "county": ["County", "COUNTY", "Venue"],
        "court": ["Court", "COURT", "Court Name"]
    }',
    -- Explicit column mapping override (if patterns don't work)
    explicit_mapping JSONB DEFAULT '{}',
    -- Stats
    times_used INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    is_default BOOLEAN NOT NULL DEFAULT false,
    CONSTRAINT uq_foil_template_name UNIQUE (template_name)
);
COMMENT ON TABLE raw.foil_column_templates IS 'Reusable column mapping templates for FOIL imports by agency';
-- Insert a default template
INSERT INTO raw.foil_column_templates (
        template_name,
        source_agency,
        is_default,
        created_by
    )
VALUES (
        'Default FOIL Template',
        NULL,
        true,
        'system'
    ) ON CONFLICT (template_name) DO NOTHING;
-- ============================================================================
-- 5. View: FOIL pipeline monitor
-- ============================================================================
CREATE OR REPLACE VIEW raw.v_foil_pipeline AS
SELECT fd.id,
    fd.dataset_name,
    fd.source_agency,
    fd.original_filename,
    fd.status,
    fd.row_count_raw,
    fd.row_count_mapped,
    fd.row_count_valid,
    fd.row_count_invalid,
    fd.row_count_duplicate,
    -- Computed metrics
    CASE
        WHEN fd.row_count_raw > 0 THEN ROUND(
            (fd.row_count_valid::numeric / fd.row_count_raw) * 100,
            1
        )
        ELSE 0
    END AS success_rate_pct,
    fd.mapping_confidence,
    CASE
        WHEN fd.mapping_locked_at IS NOT NULL THEN true
        ELSE false
    END AS mapping_confirmed,
    fd.error_summary,
    fd.created_at,
    fd.processed_at,
    fd.created_by,
    -- Duration
    CASE
        WHEN fd.processed_at IS NOT NULL THEN EXTRACT(
            EPOCH
            FROM (fd.processed_at - fd.created_at)
        )
        ELSE NULL
    END AS duration_seconds
FROM raw.foil_datasets fd
ORDER BY fd.created_at DESC;
COMMENT ON VIEW raw.v_foil_pipeline IS 'FOIL dataset ingestion pipeline monitor';
-- ============================================================================
-- 6. View: FOIL aggregate stats
-- ============================================================================
CREATE OR REPLACE VIEW raw.v_foil_stats AS
SELECT COUNT(*) AS total_datasets,
    COALESCE(SUM(row_count_raw), 0) AS total_rows_imported,
    COALESCE(SUM(row_count_valid), 0) AS total_rows_valid,
    COALESCE(SUM(row_count_invalid), 0) AS total_rows_invalid,
    COUNT(*) FILTER (
        WHERE status = 'pending'
    ) AS datasets_pending,
    COUNT(*) FILTER (
        WHERE status = 'mapping'
    ) AS datasets_awaiting_mapping,
    COUNT(*) FILTER (
        WHERE status = 'processing'
    ) AS datasets_processing,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS datasets_completed,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS datasets_failed,
    COUNT(*) FILTER (
        WHERE status = 'partial'
    ) AS datasets_partial,
    -- Last 24h
    COUNT(*) FILTER (
        WHERE created_at > now() - interval '24 hours'
    ) AS datasets_24h,
    COALESCE(
        SUM(row_count_valid) FILTER (
            WHERE created_at > now() - interval '24 hours'
        ),
        0
    ) AS rows_valid_24h
FROM raw.foil_datasets;
COMMENT ON VIEW raw.v_foil_stats IS 'Aggregate statistics for FOIL ingestion pipeline';
-- ============================================================================
-- 7. Add 'foil' as valid source in ops.ingest_batches
-- ============================================================================
-- Update check constraint to include 'foil' (idempotent approach)
DO $$ BEGIN -- Drop existing constraint if it exists
IF EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'ingest_batches_source_check'
        AND conrelid = 'ops.ingest_batches'::regclass
) THEN
ALTER TABLE ops.ingest_batches DROP CONSTRAINT ingest_batches_source_check;
END IF;
END $$;
-- Note: Supabase uses TEXT without constraint for source, so this is just documentation
COMMENT ON COLUMN ops.ingest_batches.source IS 'Source system: simplicity, jbi, foil, manual, csv_upload, api';
-- ============================================================================
-- 8. RLS and Grants (service_role only)
-- ============================================================================
-- raw.foil_datasets
ALTER TABLE raw.foil_datasets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS service_foil_datasets_all ON raw.foil_datasets;
CREATE POLICY service_foil_datasets_all ON raw.foil_datasets FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
REVOKE ALL ON raw.foil_datasets
FROM public,
    anon,
    authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON raw.foil_datasets TO service_role;
-- raw.foil_raw_rows
ALTER TABLE raw.foil_raw_rows ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS service_foil_raw_rows_all ON raw.foil_raw_rows;
CREATE POLICY service_foil_raw_rows_all ON raw.foil_raw_rows FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
REVOKE ALL ON raw.foil_raw_rows
FROM public,
    anon,
    authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON raw.foil_raw_rows TO service_role;
-- raw.foil_column_templates
ALTER TABLE raw.foil_column_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS service_foil_column_templates_all ON raw.foil_column_templates;
CREATE POLICY service_foil_column_templates_all ON raw.foil_column_templates FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
REVOKE ALL ON raw.foil_column_templates
FROM public,
    anon,
    authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON raw.foil_column_templates TO service_role;
-- Views
GRANT SELECT ON raw.v_foil_pipeline TO service_role;
GRANT SELECT ON raw.v_foil_stats TO service_role;
-- Sequences
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_sequences
    WHERE schemaname = 'raw'
        AND sequencename = 'foil_raw_rows_id_seq'
) THEN
GRANT USAGE,
    SELECT ON SEQUENCE raw.foil_raw_rows_id_seq TO service_role;
END IF;
END $$;
-- ============================================================================
-- Done
-- ============================================================================