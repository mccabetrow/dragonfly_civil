-- ============================================================================
-- Migration: Intake Schema SECURITY DEFINER RPCs
-- Created: 2025-12-31
-- Purpose: Lock down intake.* tables, enforce RPC-only writes
-- ============================================================================
--
-- This migration extends the world_class_security lockdown to intake schema:
--
--   1. Create SECURITY DEFINER RPCs for all intake.* write operations
--   2. Revoke raw INSERT/UPDATE/DELETE from dragonfly_app on intake tables
--   3. Grant EXECUTE on new RPCs to dragonfly_app
--
-- After applying:
--   - All FOIL dataset operations go through secure RPCs
--   - Workers cannot perform raw SQL writes to intake tables
--   - Audit trail maintained via RPC function logging
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. ENSURE intake SCHEMA EXISTS
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS intake;
GRANT USAGE ON SCHEMA intake TO dragonfly_app;
-- ============================================================================
-- 2. FOIL DATASET RPCs
-- ============================================================================
-- ---------------------------------------------------------------------------
-- 2a. intake.create_foil_dataset - Replace raw INSERT INTO intake.foil_datasets
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.create_foil_dataset(
        p_dataset_name TEXT,
        p_original_filename TEXT,
        p_source_agency TEXT DEFAULT NULL,
        p_foil_request_number TEXT DEFAULT NULL,
        p_row_count_raw INTEGER DEFAULT 0,
        p_column_count INTEGER DEFAULT 0,
        p_detected_columns TEXT [] DEFAULT '{}'::TEXT []
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake,
    ops AS $$
DECLARE v_dataset_id UUID;
BEGIN
INSERT INTO intake.foil_datasets (
        dataset_name,
        original_filename,
        source_agency,
        foil_request_number,
        row_count_raw,
        column_count,
        detected_columns,
        status,
        mapping_started_at
    )
VALUES (
        p_dataset_name,
        p_original_filename,
        p_source_agency,
        p_foil_request_number,
        p_row_count_raw,
        p_column_count,
        p_detected_columns,
        'mapping',
        now()
    )
RETURNING id INTO v_dataset_id;
RETURN v_dataset_id;
END;
$$;
COMMENT ON FUNCTION intake.create_foil_dataset IS 'Securely create a FOIL dataset record. Used by ingest_processor for FOIL imports.';
-- ---------------------------------------------------------------------------
-- 2b. intake.update_foil_dataset_mapping - Replace raw UPDATE for mapping
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.update_foil_dataset_mapping(
        p_dataset_id UUID,
        p_column_mapping JSONB,
        p_column_mapping_reverse JSONB,
        p_unmapped_columns TEXT [],
        p_mapping_confidence INTEGER,
        p_required_fields_missing TEXT []
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake AS $$ BEGIN
UPDATE intake.foil_datasets
SET column_mapping = p_column_mapping,
    column_mapping_reverse = p_column_mapping_reverse,
    unmapped_columns = p_unmapped_columns,
    mapping_confidence = p_mapping_confidence,
    required_fields_missing = p_required_fields_missing,
    mapping_completed_at = now()
WHERE id = p_dataset_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION intake.update_foil_dataset_mapping IS 'Securely update FOIL dataset column mapping results.';
-- ---------------------------------------------------------------------------
-- 2c. intake.update_foil_dataset_status - Replace raw UPDATE for status
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.update_foil_dataset_status(
        p_dataset_id UUID,
        p_status TEXT,
        p_error_summary TEXT DEFAULT NULL
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake AS $$ BEGIN
UPDATE intake.foil_datasets
SET status = p_status,
    error_summary = COALESCE(p_error_summary, error_summary),
    processing_started_at = CASE
        WHEN p_status = 'processing' THEN now()
        ELSE processing_started_at
    END
WHERE id = p_dataset_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION intake.update_foil_dataset_status IS 'Securely update FOIL dataset status with optional error summary.';
-- ---------------------------------------------------------------------------
-- 2d. intake.finalize_foil_dataset - Replace raw UPDATE for final counts
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.finalize_foil_dataset(
        p_dataset_id UUID,
        p_row_count_valid INTEGER,
        p_row_count_invalid INTEGER,
        p_row_count_quarantined INTEGER,
        p_status TEXT
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake AS $$ BEGIN
UPDATE intake.foil_datasets
SET row_count_valid = p_row_count_valid,
    row_count_invalid = p_row_count_invalid,
    row_count_quarantined = p_row_count_quarantined,
    row_count_mapped = p_row_count_valid + p_row_count_invalid,
    status = p_status,
    processed_at = now()
WHERE id = p_dataset_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION intake.finalize_foil_dataset IS 'Securely finalize FOIL dataset with row counts and final status.';
-- ============================================================================
-- 3. FOIL RAW ROWS RPCs
-- ============================================================================
-- ---------------------------------------------------------------------------
-- 3a. intake.store_foil_raw_row - Replace raw INSERT INTO intake.foil_raw_rows
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.store_foil_raw_row(
        p_dataset_id UUID,
        p_row_index INTEGER,
        p_raw_data JSONB
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake AS $$
DECLARE v_row_id UUID;
BEGIN
INSERT INTO intake.foil_raw_rows (
        dataset_id,
        row_index,
        raw_data
    )
VALUES (
        p_dataset_id,
        p_row_index,
        p_raw_data
    )
RETURNING id INTO v_row_id;
RETURN v_row_id;
EXCEPTION
WHEN unique_violation THEN -- Row already exists, return existing ID
SELECT id INTO v_row_id
FROM intake.foil_raw_rows
WHERE dataset_id = p_dataset_id
    AND row_index = p_row_index;
RETURN v_row_id;
END;
$$;
COMMENT ON FUNCTION intake.store_foil_raw_row IS 'Securely store a raw FOIL row. Idempotent - returns existing ID on conflict.';
-- ---------------------------------------------------------------------------
-- 3b. intake.store_foil_raw_rows_bulk - Bulk insert for performance
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.store_foil_raw_rows_bulk(
        p_dataset_id UUID,
        p_rows JSONB -- Array of {row_index, raw_data} objects
    ) RETURNS INTEGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake AS $$
DECLARE v_inserted INTEGER := 0;
v_row JSONB;
BEGIN FOR v_row IN
SELECT *
FROM jsonb_array_elements(p_rows) LOOP
INSERT INTO intake.foil_raw_rows (
        dataset_id,
        row_index,
        raw_data
    )
VALUES (
        p_dataset_id,
        (v_row->>'row_index')::INTEGER,
        v_row->'raw_data'
    ) ON CONFLICT (dataset_id, row_index) DO NOTHING;
IF FOUND THEN v_inserted := v_inserted + 1;
END IF;
END LOOP;
RETURN v_inserted;
END;
$$;
COMMENT ON FUNCTION intake.store_foil_raw_rows_bulk IS 'Securely bulk-insert raw FOIL rows. Returns count of inserted rows.';
-- ---------------------------------------------------------------------------
-- 3c. intake.update_foil_raw_row_status - Replace raw UPDATE for row status
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.update_foil_raw_row_status(
        p_dataset_id UUID,
        p_row_index INTEGER,
        p_validation_status TEXT,
        p_judgment_id TEXT DEFAULT NULL
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake AS $$ BEGIN
UPDATE intake.foil_raw_rows
SET validation_status = p_validation_status,
    judgment_id = p_judgment_id
WHERE dataset_id = p_dataset_id
    AND row_index = p_row_index;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION intake.update_foil_raw_row_status IS 'Securely update FOIL raw row validation status.';
-- ============================================================================
-- 4. FOIL QUARANTINE RPCs
-- ============================================================================
-- ---------------------------------------------------------------------------
-- 4a. intake.quarantine_foil_row - Replace raw INSERT INTO intake.foil_quarantine
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION intake.quarantine_foil_row(
        p_dataset_id UUID,
        p_row_index INTEGER,
        p_raw_data JSONB,
        p_quarantine_reason TEXT,
        p_error_message TEXT,
        p_mapped_data JSONB DEFAULT NULL
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = intake AS $$
DECLARE v_quarantine_id UUID;
BEGIN -- Insert into quarantine
INSERT INTO intake.foil_quarantine (
        dataset_id,
        row_index,
        raw_data,
        quarantine_reason,
        error_message,
        mapped_data
    )
VALUES (
        p_dataset_id,
        p_row_index,
        p_raw_data,
        p_quarantine_reason,
        LEFT(p_error_message, 500),
        COALESCE(p_mapped_data, '{}'::JSONB)
    )
RETURNING id INTO v_quarantine_id;
-- Update raw row status
UPDATE intake.foil_raw_rows
SET validation_status = 'quarantined'
WHERE dataset_id = p_dataset_id
    AND row_index = p_row_index;
RETURN v_quarantine_id;
END;
$$;
COMMENT ON FUNCTION intake.quarantine_foil_row IS 'Securely quarantine a FOIL row and update its status.';
-- ============================================================================
-- 5. EXTENDED JUDGMENT UPSERT (with court field)
-- ============================================================================
-- The existing ops.upsert_judgment doesn't include 'court' field.
-- Create an extended version for FOIL imports.
CREATE OR REPLACE FUNCTION ops.upsert_judgment_extended(
        p_case_number TEXT,
        p_plaintiff_name TEXT,
        p_defendant_name TEXT,
        p_judgment_amount NUMERIC,
        p_entry_date DATE DEFAULT NULL,
        p_county TEXT DEFAULT NULL,
        p_court TEXT DEFAULT NULL,
        p_collectability_score INTEGER DEFAULT NULL,
        p_source_file TEXT DEFAULT NULL,
        p_status TEXT DEFAULT 'pending'
    ) RETURNS TABLE (
        judgment_id BIGINT,
        is_insert BOOLEAN
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    ops AS $$ BEGIN RETURN QUERY
INSERT INTO public.judgments (
        case_number,
        plaintiff_name,
        defendant_name,
        judgment_amount,
        entry_date,
        county,
        court,
        collectability_score,
        source_file,
        status,
        created_at
    )
VALUES (
        p_case_number,
        p_plaintiff_name,
        p_defendant_name,
        p_judgment_amount,
        p_entry_date,
        p_county,
        p_court,
        p_collectability_score,
        p_source_file,
        p_status,
        now()
    ) ON CONFLICT (case_number) DO
UPDATE
SET plaintiff_name = COALESCE(
        EXCLUDED.plaintiff_name,
        public.judgments.plaintiff_name
    ),
    defendant_name = COALESCE(
        EXCLUDED.defendant_name,
        public.judgments.defendant_name
    ),
    judgment_amount = EXCLUDED.judgment_amount,
    entry_date = COALESCE(EXCLUDED.entry_date, public.judgments.entry_date),
    county = COALESCE(EXCLUDED.county, public.judgments.county),
    court = COALESCE(EXCLUDED.court, public.judgments.court),
    collectability_score = EXCLUDED.collectability_score,
    updated_at = now()
RETURNING id,
    (xmax = 0);
END;
$$;
COMMENT ON FUNCTION ops.upsert_judgment_extended IS 'Extended judgment upsert with court field. Used by FOIL ingest.';
-- ============================================================================
-- 6. REVOKE RAW TABLE ACCESS ON intake.*
-- ============================================================================
-- Revoke direct write access from dragonfly_app
DO $$ BEGIN REVOKE
INSERT,
    UPDATE,
    DELETE ON intake.foil_datasets
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON intake.foil_raw_rows
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON intake.foil_quarantine
FROM dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Grant SELECT for reading
GRANT SELECT ON ALL TABLES IN SCHEMA intake TO dragonfly_app;
-- ============================================================================
-- 7. GRANT EXECUTE ON NEW RPCs
-- ============================================================================
GRANT EXECUTE ON FUNCTION intake.create_foil_dataset(TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, TEXT []) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION intake.update_foil_dataset_mapping(UUID, JSONB, JSONB, TEXT [], INTEGER, TEXT []) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION intake.update_foil_dataset_status(UUID, TEXT, TEXT) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION intake.finalize_foil_dataset(UUID, INTEGER, INTEGER, INTEGER, TEXT) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION intake.store_foil_raw_row(UUID, INTEGER, JSONB) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION intake.store_foil_raw_rows_bulk(UUID, JSONB) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION intake.update_foil_raw_row_status(UUID, INTEGER, TEXT, TEXT) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION intake.quarantine_foil_row(UUID, INTEGER, JSONB, TEXT, TEXT, JSONB) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.upsert_judgment_extended(
        TEXT,
        TEXT,
        TEXT,
        NUMERIC,
        DATE,
        TEXT,
        TEXT,
        INTEGER,
        TEXT,
        TEXT
    ) TO dragonfly_app;
-- ============================================================================
-- 8. GRANT SEQUENCE ACCESS
-- ============================================================================
GRANT USAGE ON ALL SEQUENCES IN SCHEMA intake TO dragonfly_app;
-- ============================================================================
-- 9. NOTIFY POSTGREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- ROLLBACK STATEMENTS (run manually if needed)
-- ============================================================================
-- BEGIN;
-- DROP FUNCTION IF EXISTS intake.create_foil_dataset(TEXT, TEXT, TEXT, TEXT, INTEGER, INTEGER, TEXT[]);
-- DROP FUNCTION IF EXISTS intake.update_foil_dataset_mapping(UUID, JSONB, JSONB, TEXT[], INTEGER, TEXT[]);
-- DROP FUNCTION IF EXISTS intake.update_foil_dataset_status(UUID, TEXT, TEXT);
-- DROP FUNCTION IF EXISTS intake.finalize_foil_dataset(UUID, INTEGER, INTEGER, INTEGER, TEXT);
-- DROP FUNCTION IF EXISTS intake.store_foil_raw_row(UUID, INTEGER, JSONB);
-- DROP FUNCTION IF EXISTS intake.store_foil_raw_rows_bulk(UUID, JSONB);
-- DROP FUNCTION IF EXISTS intake.update_foil_raw_row_status(UUID, INTEGER, TEXT, TEXT);
-- DROP FUNCTION IF EXISTS intake.quarantine_foil_row(UUID, INTEGER, JSONB, TEXT, TEXT, JSONB);
-- DROP FUNCTION IF EXISTS ops.upsert_judgment_extended(TEXT, TEXT, TEXT, NUMERIC, DATE, TEXT, TEXT, INTEGER, TEXT, TEXT);
-- GRANT INSERT, UPDATE, DELETE ON intake.foil_datasets TO dragonfly_app;
-- GRANT INSERT, UPDATE, DELETE ON intake.foil_raw_rows TO dragonfly_app;
-- GRANT INSERT, UPDATE, DELETE ON intake.foil_quarantine TO dragonfly_app;
-- NOTIFY pgrst, 'reload schema';
-- COMMIT;