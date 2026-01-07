-- Migration: Generic FOIL Ingestion Adapter
-- Version: Dragonfly Engine v0.4.x
-- Description: Creates intake.foil_datasets schema for messy public FOIL data
--              with quarantine table for unmatched rows and fuzzy matching support
-- ============================================================================
-- Business Purpose:
-- FOIL (Freedom of Information Law) data comes in messy formats with varying
-- column names. This migration creates:
--   1. intake.foil_datasets - Primary FOIL dataset tracking (user-requested schema)
--   2. intake.foil_raw_rows - Raw FOIL rows as JSONB for processing
--   3. intake.foil_quarantine - Dead letter queue for unmappable rows
--   4. intake.foil_column_mappings - Discovered/confirmed column mappings
--   5. Views for monitoring FOIL ingestion pipeline
-- ============================================================================
-- ============================================================================
-- 1. intake.foil_datasets - Primary FOIL dataset tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.foil_datasets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Dataset identification
    dataset_name TEXT NOT NULL,
    source_agency TEXT,
    -- e.g., 'NYC Civil Court', 'Nassau County'
    foil_request_number TEXT,
    -- Original FOIL request reference
    -- File metadata
    original_filename TEXT NOT NULL,
    file_size_bytes BIGINT,
    row_count_raw INTEGER NOT NULL DEFAULT 0,
    column_count INTEGER NOT NULL DEFAULT 0,
    detected_columns TEXT [] NOT NULL DEFAULT '{}',
    -- Array of column names
    -- Column mapping results
    column_mapping JSONB NOT NULL DEFAULT '{}',
    -- {"raw_col": "canonical_col"}
    column_mapping_reverse JSONB NOT NULL DEFAULT '{}',
    -- {"canonical_col": "raw_col"}
    unmapped_columns TEXT [] NOT NULL DEFAULT '{}',
    -- Columns that couldn't be mapped
    mapping_confidence NUMERIC(5, 2),
    -- 0-100 confidence
    required_fields_missing TEXT [] DEFAULT '{}',
    -- Missing required fields
    -- Processing status
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            -- Just uploaded, no mapping
            'mapping',
            -- Auto-mapping in progress
            'needs_review',
            -- Low confidence, human review needed
            'confirmed',
            -- Mapping confirmed by human
            'processing',
            -- Rows being imported
            'completed',
            -- All valid rows imported
            'failed',
            -- Processing failed
            'partial' -- Completed with some errors
        )
    ),
    -- Row counts after processing
    row_count_mapped INTEGER NOT NULL DEFAULT 0,
    -- Rows successfully mapped
    row_count_valid INTEGER NOT NULL DEFAULT 0,
    -- Rows passing validation
    row_count_invalid INTEGER NOT NULL DEFAULT 0,
    -- Rows failing validation
    row_count_quarantined INTEGER NOT NULL DEFAULT 0,
    -- Rows in quarantine
    row_count_duplicate INTEGER NOT NULL DEFAULT 0,
    -- Duplicate case numbers
    -- Error handling
    error_summary TEXT,
    sample_errors JSONB DEFAULT '[]',
    -- Link to ops.ingest_batches (when processed)
    ingest_batch_id UUID REFERENCES ops.ingest_batches(id),
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    mapping_started_at TIMESTAMPTZ,
    mapping_completed_at TIMESTAMPTZ,
    processing_started_at TIMESTAMPTZ,
    processed_at TIMESTAMPTZ,
    -- User tracking
    created_by TEXT,
    mapping_confirmed_by TEXT,
    -- Metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}'
);
COMMENT ON TABLE intake.foil_datasets IS 'Tracks FOIL dataset imports with column mapping status and validation metrics';
COMMENT ON COLUMN intake.foil_datasets.mapping_confidence IS 'Auto-detection confidence 0-100; <70 triggers needs_review status';
COMMENT ON COLUMN intake.foil_datasets.status IS 'pending→mapping→needs_review/confirmed→processing→completed/failed/partial';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_intake_foil_datasets_status ON intake.foil_datasets(status);
CREATE INDEX IF NOT EXISTS idx_intake_foil_datasets_created_at ON intake.foil_datasets(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_intake_foil_datasets_source_agency ON intake.foil_datasets(source_agency);
CREATE INDEX IF NOT EXISTS idx_intake_foil_datasets_batch ON intake.foil_datasets(ingest_batch_id);
-- ============================================================================
-- 2. intake.foil_raw_rows - Raw FOIL rows as JSONB
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.foil_raw_rows (
    id BIGSERIAL PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES intake.foil_datasets(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    -- 0-based row position
    raw_data JSONB NOT NULL,
    -- Original row as key-value pairs
    -- Processing status
    validation_status TEXT NOT NULL DEFAULT 'pending' CHECK (
        validation_status IN (
            'pending',
            'mapped',
            'valid',
            'invalid',
            'quarantined',
            'skipped'
        )
    ),
    validation_errors TEXT [],
    -- Array of error messages
    -- Link to resulting judgment (if successfully imported)
    judgment_id UUID,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE intake.foil_raw_rows IS 'Raw FOIL CSV rows stored as JSONB for processing and audit';
-- Indexes for batch processing
CREATE INDEX IF NOT EXISTS idx_intake_foil_raw_rows_dataset ON intake.foil_raw_rows(dataset_id);
CREATE INDEX IF NOT EXISTS idx_intake_foil_raw_rows_dataset_row ON intake.foil_raw_rows(dataset_id, row_index);
CREATE INDEX IF NOT EXISTS idx_intake_foil_raw_rows_status ON intake.foil_raw_rows(dataset_id, validation_status);
-- ============================================================================
-- 3. intake.foil_quarantine - Dead letter queue for unmappable rows
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.foil_quarantine (
    id BIGSERIAL PRIMARY KEY,
    dataset_id UUID NOT NULL REFERENCES intake.foil_datasets(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    -- Original row position
    raw_row_id BIGINT REFERENCES intake.foil_raw_rows(id) ON DELETE
    SET NULL,
        -- Raw data for review
        raw_data JSONB NOT NULL,
        -- Quarantine reason
        quarantine_reason TEXT NOT NULL CHECK (
            quarantine_reason IN (
                'unmappable',
                -- Columns couldn't be mapped
                'missing_required',
                -- Missing case_number or amount
                'invalid_data',
                -- Data validation failed
                'duplicate',
                -- Duplicate case number
                'parse_error',
                -- Couldn't parse row data
                'transform_error',
                -- Transform to canonical format failed
                'manual_review' -- Flagged for manual review
            )
        ),
        -- Error details
        error_code TEXT,
        error_message TEXT NOT NULL,
        error_details JSONB DEFAULT '{}',
        -- Mapped data attempt (if any)
        mapped_data JSONB DEFAULT '{}',
        -- What we could map before failure
        matched_columns JSONB DEFAULT '{}',
        -- Columns that did match
        unmatched_columns TEXT [] DEFAULT '{}',
        -- Columns that didn't match
        -- Resolution tracking
        resolution_status TEXT NOT NULL DEFAULT 'pending' CHECK (
            resolution_status IN (
                'pending',
                'resolved',
                'ignored',
                'retry_scheduled'
            )
        ),
        resolved_at TIMESTAMPTZ,
        resolved_by TEXT,
        resolution_notes TEXT,
        -- Retry tracking
        retry_count INTEGER NOT NULL DEFAULT 0,
        last_retry_at TIMESTAMPTZ,
        created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE intake.foil_quarantine IS 'Dead letter queue for FOIL rows that cannot be automatically processed';
COMMENT ON COLUMN intake.foil_quarantine.quarantine_reason IS 'Why the row was quarantined';
COMMENT ON COLUMN intake.foil_quarantine.mapped_data IS 'Partial mapping data before failure';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_intake_foil_quarantine_dataset ON intake.foil_quarantine(dataset_id);
CREATE INDEX IF NOT EXISTS idx_intake_foil_quarantine_reason ON intake.foil_quarantine(quarantine_reason);
CREATE INDEX IF NOT EXISTS idx_intake_foil_quarantine_unresolved ON intake.foil_quarantine(dataset_id)
WHERE resolution_status = 'pending';
CREATE INDEX IF NOT EXISTS idx_intake_foil_quarantine_created ON intake.foil_quarantine(created_at DESC);
-- ============================================================================
-- 4. intake.foil_column_mappings - Reusable column mapping templates
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.foil_column_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Template identification
    mapping_name TEXT NOT NULL,
    source_agency TEXT,
    -- Agency this template is for
    is_default BOOLEAN NOT NULL DEFAULT false,
    -- Column patterns for auto-detection (canonical -> patterns)
    column_patterns JSONB NOT NULL DEFAULT '{
        "case_number": ["Case Number", "Case No", "Case #", "CaseNo", "Case_Number", "CASENO", "Index No", "Docket No"],
        "defendant_name": ["Defendant", "Def. Name", "DefName", "Defendant Name", "DEF_NAME", "Debtor", "Judgment Debtor"],
        "plaintiff_name": ["Plaintiff", "Plf. Name", "PlfName", "Plaintiff Name", "PLF_NAME", "Creditor", "Judgment Creditor"],
        "judgment_amount": ["Amt", "Amount", "Judgment Amount", "Judgment Amt", "JudgmentAmt", "AMOUNT", "Total", "Principal"],
        "filing_date": ["Date Filed", "Filing Date", "FilingDate", "Filed Date", "DATE_FILED", "File Date"],
        "judgment_date": ["Judgment Date", "Jdgmt Date", "JdgmtDate", "JUDGMENT_DATE", "Entry Date", "Date of Judgment"],
        "county": ["County", "COUNTY", "Venue", "Jurisdiction"],
        "court": ["Court", "COURT", "Court Name", "Tribunal"]
    }',
    -- Explicit column mapping override
    explicit_mapping JSONB DEFAULT '{}',
    -- {"raw_col": "canonical_col"}
    -- Fuzzy matching threshold (0-100)
    fuzzy_threshold INTEGER NOT NULL DEFAULT 80,
    -- Stats
    times_used INTEGER NOT NULL DEFAULT 0,
    last_used_at TIMESTAMPTZ,
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by TEXT,
    CONSTRAINT uq_intake_foil_mapping_name UNIQUE (mapping_name)
);
COMMENT ON TABLE intake.foil_column_mappings IS 'Reusable column mapping templates for FOIL data by agency';
COMMENT ON COLUMN intake.foil_column_mappings.column_patterns IS 'Canonical field -> array of possible raw column names';
COMMENT ON COLUMN intake.foil_column_mappings.fuzzy_threshold IS 'Minimum similarity score (0-100) for fuzzy matching';
-- Insert default template
INSERT INTO intake.foil_column_mappings (
        mapping_name,
        source_agency,
        is_default,
        created_by
    )
VALUES (
        'Default FOIL Template',
        NULL,
        true,
        'system'
    ) ON CONFLICT (mapping_name) DO NOTHING;
-- ============================================================================
-- 5. Views for monitoring
-- ============================================================================
-- FOIL Pipeline Monitor
CREATE OR REPLACE VIEW intake.v_foil_pipeline AS
SELECT fd.id,
    fd.dataset_name,
    fd.source_agency,
    fd.original_filename,
    fd.status,
    fd.row_count_raw,
    fd.row_count_mapped,
    fd.row_count_valid,
    fd.row_count_invalid,
    fd.row_count_quarantined,
    fd.row_count_duplicate,
    -- Computed metrics
    CASE
        WHEN fd.row_count_raw > 0 THEN ROUND(
            (fd.row_count_valid::NUMERIC / fd.row_count_raw) * 100,
            1
        )
        ELSE 0
    END AS success_rate_pct,
    fd.mapping_confidence,
    CASE
        WHEN fd.mapping_confirmed_by IS NOT NULL THEN true
        ELSE false
    END AS mapping_confirmed,
    array_length(fd.unmapped_columns, 1) AS unmapped_column_count,
    array_length(fd.required_fields_missing, 1) AS required_missing_count,
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
FROM intake.foil_datasets fd
ORDER BY fd.created_at DESC;
COMMENT ON VIEW intake.v_foil_pipeline IS 'FOIL dataset ingestion pipeline monitor';
-- FOIL Aggregate Stats
CREATE OR REPLACE VIEW intake.v_foil_stats AS
SELECT COUNT(*) AS total_datasets,
    COALESCE(SUM(row_count_raw), 0) AS total_rows_imported,
    COALESCE(SUM(row_count_valid), 0) AS total_rows_valid,
    COALESCE(SUM(row_count_invalid), 0) AS total_rows_invalid,
    COALESCE(SUM(row_count_quarantined), 0) AS total_rows_quarantined,
    COUNT(*) FILTER (
        WHERE status = 'pending'
    ) AS datasets_pending,
    COUNT(*) FILTER (
        WHERE status = 'needs_review'
    ) AS datasets_needs_review,
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
    -- Quarantine stats
    (
        SELECT COUNT(*)
        FROM intake.foil_quarantine
        WHERE resolution_status = 'pending'
    ) AS quarantine_pending,
    (
        SELECT COUNT(*)
        FROM intake.foil_quarantine
        WHERE resolution_status = 'resolved'
    ) AS quarantine_resolved,
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
FROM intake.foil_datasets;
COMMENT ON VIEW intake.v_foil_stats IS 'Aggregate statistics for FOIL ingestion pipeline';
-- Quarantine overview
CREATE OR REPLACE VIEW intake.v_foil_quarantine_overview AS
SELECT fq.id,
    fq.dataset_id,
    fd.dataset_name,
    fd.source_agency,
    fq.row_index,
    fq.quarantine_reason,
    fq.error_message,
    fq.resolution_status,
    fq.retry_count,
    fq.created_at,
    fq.resolved_at,
    fq.resolved_by
FROM intake.foil_quarantine fq
    JOIN intake.foil_datasets fd ON fd.id = fq.dataset_id
ORDER BY fq.created_at DESC;
COMMENT ON VIEW intake.v_foil_quarantine_overview IS 'Overview of quarantined FOIL rows with dataset context';
-- ============================================================================
-- 6. Add 'foil_ingest' to job_types (comment documentation)
-- ============================================================================
COMMENT ON TABLE ops.job_queue IS 'Job queue for async processing. job_type values: ingest_csv, foil_ingest, simplicity_ingest';
-- ============================================================================
-- 7. RLS Policies
-- ============================================================================
-- intake.foil_datasets
ALTER TABLE intake.foil_datasets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_foil_datasets_all" ON intake.foil_datasets;
CREATE POLICY "service_foil_datasets_all" ON intake.foil_datasets FOR ALL USING (true) WITH CHECK (true);
-- intake.foil_raw_rows  
ALTER TABLE intake.foil_raw_rows ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_foil_raw_rows_all" ON intake.foil_raw_rows;
CREATE POLICY "service_foil_raw_rows_all" ON intake.foil_raw_rows FOR ALL USING (true) WITH CHECK (true);
-- intake.foil_quarantine
ALTER TABLE intake.foil_quarantine ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_foil_quarantine_all" ON intake.foil_quarantine;
CREATE POLICY "service_foil_quarantine_all" ON intake.foil_quarantine FOR ALL USING (true) WITH CHECK (true);
-- intake.foil_column_mappings
ALTER TABLE intake.foil_column_mappings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_foil_column_mappings_all" ON intake.foil_column_mappings;
CREATE POLICY "service_foil_column_mappings_all" ON intake.foil_column_mappings FOR ALL USING (true) WITH CHECK (true);
-- ============================================================================
-- 8. Grants
-- ============================================================================
GRANT ALL ON intake.foil_datasets TO service_role;
GRANT ALL ON intake.foil_raw_rows TO service_role;
GRANT ALL ON intake.foil_quarantine TO service_role;
GRANT ALL ON intake.foil_column_mappings TO service_role;
GRANT SELECT ON intake.v_foil_pipeline TO service_role;
GRANT SELECT ON intake.v_foil_stats TO service_role;
GRANT SELECT ON intake.v_foil_quarantine_overview TO service_role;
-- Sequences
GRANT USAGE,
    SELECT ON SEQUENCE intake.foil_raw_rows_id_seq TO service_role;
GRANT USAGE,
    SELECT ON SEQUENCE intake.foil_quarantine_id_seq TO service_role;
-- ============================================================================
-- 9. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';
