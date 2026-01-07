-- Migration: World-Class Intake Ingestion
-- Description: Enhance intake schema for deterministic, idempotent, observable ingestion
-- ============================================================================
-- Goals:
--   1. Add storage_path and row_count_duplicate columns for observability
--   2. Add dedup_key column for compound key deduplication
--   3. Create insert_or_get_judgment RPC for true idempotent upserts
--   4. Add batch summary view for Discord notifications
-- ============================================================================
-- ============================================================================
-- 1. Add missing columns to intake.simplicity_batches
-- ============================================================================
-- Storage path for raw CSV (Supabase Storage)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS storage_path TEXT;
COMMENT ON COLUMN intake.simplicity_batches.storage_path IS 'Supabase Storage path: intake/simplicity/{batch_id}.csv';
-- Duplicate count (rows that matched existing judgments)
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS row_count_duplicate INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN intake.simplicity_batches.row_count_duplicate IS 'Rows skipped because they already exist in public.judgments';
-- Discord notification sent flag
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS discord_notified BOOLEAN NOT NULL DEFAULT false;
COMMENT ON COLUMN intake.simplicity_batches.discord_notified IS 'Whether Discord summary was sent for this batch';
-- ============================================================================
-- 2. Add dedup_key column to simplicity_validated_rows for compound matching
-- ============================================================================
ALTER TABLE intake.simplicity_validated_rows
ADD COLUMN IF NOT EXISTS dedup_key TEXT;
COMMENT ON COLUMN intake.simplicity_validated_rows.dedup_key IS 'Compound deduplication key: UPPER(case_number)|NORMALIZED(defendant)';
CREATE INDEX IF NOT EXISTS idx_simplicity_validated_dedup ON intake.simplicity_validated_rows(dedup_key)
WHERE dedup_key IS NOT NULL;
-- ============================================================================
-- 3. Create insert_or_get_judgment RPC for idempotent upserts
-- ============================================================================
CREATE OR REPLACE FUNCTION public.insert_or_get_judgment(
        p_case_number TEXT,
        p_plaintiff_name TEXT DEFAULT NULL,
        p_defendant_name TEXT DEFAULT NULL,
        p_judgment_amount NUMERIC DEFAULT NULL,
        p_entry_date DATE DEFAULT NULL,
        p_court TEXT DEFAULT NULL,
        p_county TEXT DEFAULT NULL,
        p_source_file TEXT DEFAULT NULL
    ) RETURNS TABLE (id BIGINT, was_inserted BOOLEAN) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_id BIGINT;
v_inserted BOOLEAN := false;
BEGIN -- Try to find existing judgment
SELECT j.id INTO v_id
FROM public.judgments j
WHERE j.case_number = UPPER(TRIM(p_case_number))
LIMIT 1;
IF v_id IS NOT NULL THEN -- Existing judgment found
RETURN QUERY
SELECT v_id,
    false;
RETURN;
END IF;
-- Insert new judgment
INSERT INTO public.judgments (
        case_number,
        plaintiff_name,
        defendant_name,
        judgment_amount,
        entry_date,
        court,
        county,
        source_file,
        status,
        enforcement_stage,
        created_at,
        updated_at
    )
VALUES (
        UPPER(TRIM(p_case_number)),
        TRIM(p_plaintiff_name),
        TRIM(p_defendant_name),
        p_judgment_amount,
        p_entry_date,
        TRIM(p_court),
        TRIM(p_county),
        p_source_file,
        'active',
        'pre_enforcement',
        NOW(),
        NOW()
    )
RETURNING public.judgments.id INTO v_id;
RETURN QUERY
SELECT v_id,
    true;
EXCEPTION
WHEN unique_violation THEN -- Race condition: another process inserted first
SELECT j.id INTO v_id
FROM public.judgments j
WHERE j.case_number = UPPER(TRIM(p_case_number))
LIMIT 1;
RETURN QUERY
SELECT v_id,
    false;
END;
$$;
COMMENT ON FUNCTION public.insert_or_get_judgment IS 'Idempotent judgment upsert: returns existing ID or inserts new. Race-condition safe.';
GRANT EXECUTE ON FUNCTION public.insert_or_get_judgment TO service_role;
-- ============================================================================
-- 4. Create batch summary view for Discord notifications
-- ============================================================================
CREATE OR REPLACE VIEW intake.v_batch_summary AS
SELECT b.id AS batch_id,
    b.filename,
    b.status,
    b.storage_path,
    b.file_hash,
    b.row_count_total,
    b.row_count_inserted,
    b.row_count_duplicate,
    b.row_count_invalid,
    b.discord_notified,
    b.created_at,
    b.completed_at,
    -- Derived metrics
    CASE
        WHEN b.row_count_total > 0 THEN ROUND(
            (
                b.row_count_inserted::NUMERIC / b.row_count_total
            ) * 100,
            1
        )
        ELSE 0
    END AS insert_rate_pct,
    CASE
        WHEN b.row_count_total > 0 THEN ROUND(
            (
                b.row_count_duplicate::NUMERIC / b.row_count_total
            ) * 100,
            1
        )
        ELSE 0
    END AS duplicate_rate_pct,
    CASE
        WHEN b.row_count_total > 0 THEN ROUND(
            (b.row_count_invalid::NUMERIC / b.row_count_total) * 100,
            1
        )
        ELSE 0
    END AS error_rate_pct,
    -- Duration in seconds
    EXTRACT(
        EPOCH
        FROM (b.completed_at - b.created_at)
    ) AS duration_seconds,
    -- Health classification
    CASE
        WHEN b.status = 'failed' THEN 'critical'
        WHEN b.row_count_invalid > 0
        AND (
            b.row_count_invalid::NUMERIC / NULLIF(b.row_count_total, 0)
        ) > 0.2 THEN 'critical'
        WHEN b.row_count_invalid > 0 THEN 'warning'
        ELSE 'healthy'
    END AS health_status,
    -- First 5 errors for summary
    (
        SELECT jsonb_agg(
                jsonb_build_object(
                    'row_index',
                    f.row_index,
                    'error_code',
                    f.error_code,
                    'error_message',
                    LEFT(f.error_message, 100)
                )
            )
        FROM (
                SELECT row_index,
                    error_code,
                    error_message
                FROM intake.simplicity_failed_rows
                WHERE batch_id = b.id
                ORDER BY row_index
                LIMIT 5
            ) f
    ) AS first_errors
FROM intake.simplicity_batches b
ORDER BY b.created_at DESC;
GRANT SELECT ON intake.v_batch_summary TO service_role;
COMMENT ON VIEW intake.v_batch_summary IS 'Batch summary view with derived metrics for Discord notifications and dashboard';
-- ============================================================================
-- 5. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';
