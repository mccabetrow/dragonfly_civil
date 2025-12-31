-- 20251230101000_plaintiff_intake_support.sql
-- Plaintiff ingestion instrumentation and telemetry for intake batches.
-- ============================================================================
-- 1. Extend intake.simplicity_batches with plaintiff counters
-- ============================================================================
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS plaintiff_inserted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS plaintiff_duplicate INTEGER NOT NULL DEFAULT 0;
ALTER TABLE intake.simplicity_batches
ADD COLUMN IF NOT EXISTS plaintiff_failed INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN intake.simplicity_batches.plaintiff_inserted IS 'Number of unique plaintiffs created during ingestion.';
COMMENT ON COLUMN intake.simplicity_batches.plaintiff_duplicate IS 'Number of rows where an existing plaintiff was reused.';
COMMENT ON COLUMN intake.simplicity_batches.plaintiff_failed IS 'Rows that failed before a plaintiff association could be recorded.';
-- ============================================================================
-- 2. Extend ops.ingest_batches for dashboard parity
-- ============================================================================
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS plaintiff_inserted INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS plaintiff_duplicate INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS plaintiff_failed INTEGER NOT NULL DEFAULT 0;
-- ============================================================================
-- 3. Enrich public.plaintiffs with ingestion metadata and deterministic dedupe key
-- ============================================================================
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS source_system TEXT,
    ADD COLUMN IF NOT EXISTS source_reference TEXT,
    ADD COLUMN IF NOT EXISTS source_batch_id UUID REFERENCES intake.simplicity_batches (id) ON DELETE
SET NULL,
    ADD COLUMN IF NOT EXISTS source_row_index INTEGER,
    ADD COLUMN IF NOT EXISTS source_file_hash TEXT,
    ADD COLUMN IF NOT EXISTS first_ingested_at TIMESTAMPTZ NOT NULL DEFAULT timezone('utc', now()),
    ADD COLUMN IF NOT EXISTS dedupe_key TEXT GENERATED ALWAYS AS (
        regexp_replace(upper(trim(name)), '\\s+', ' ', 'g')
    ) STORED;
CREATE UNIQUE INDEX IF NOT EXISTS idx_plaintiffs_dedupe_key ON public.plaintiffs (dedupe_key);
COMMENT ON COLUMN public.plaintiffs.dedupe_key IS 'Upper-cased + whitespace-normalized plaintiff name used for deterministic deduplication.';
-- ============================================================================
-- 4. RPC: insert_or_get_plaintiff (idempotent plaintiff upsert)
-- ============================================================================
CREATE OR REPLACE FUNCTION public.insert_or_get_plaintiff(
        p_name TEXT,
        p_source_system TEXT DEFAULT NULL,
        p_source_batch_id UUID DEFAULT NULL,
        p_source_row_index INTEGER DEFAULT NULL,
        p_source_file_hash TEXT DEFAULT NULL
    ) RETURNS TABLE (id BIGINT, was_inserted BOOLEAN) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_id BIGINT;
v_key TEXT;
BEGIN IF p_name IS NULL
OR btrim(p_name) = '' THEN RAISE EXCEPTION 'Plaintiff name is required for insert_or_get_plaintiff';
END IF;
v_key := regexp_replace(upper(trim(p_name)), '\\s+', ' ', 'g');
SELECT pl.id INTO v_id
FROM public.plaintiffs pl
WHERE pl.dedupe_key = v_key
LIMIT 1;
IF v_id IS NOT NULL THEN RETURN QUERY
SELECT v_id,
    false;
RETURN;
END IF;
INSERT INTO public.plaintiffs (
        name,
        status,
        metadata,
        source_system,
        source_reference,
        source_batch_id,
        source_row_index,
        source_file_hash,
        first_ingested_at
    )
VALUES (
        trim(p_name),
        'intake_pending',
        '{}'::jsonb,
        p_source_system,
        CASE
            WHEN p_source_batch_id IS NOT NULL THEN CONCAT_WS(':', p_source_system, p_source_batch_id::text)
            ELSE p_source_system
        END,
        p_source_batch_id,
        p_source_row_index,
        p_source_file_hash,
        timezone('utc', now())
    )
RETURNING id INTO v_id;
RETURN QUERY
SELECT v_id,
    true;
EXCEPTION
WHEN unique_violation THEN
SELECT pl.id INTO v_id
FROM public.plaintiffs pl
WHERE pl.dedupe_key = v_key
LIMIT 1;
RETURN QUERY
SELECT v_id,
    false;
END;
$$;
COMMENT ON FUNCTION public.insert_or_get_plaintiff(TEXT, TEXT, UUID, INTEGER, TEXT) IS 'Idempotently find or create a plaintiff using a deterministic dedupe key and return (id, was_inserted).';
GRANT EXECUTE ON FUNCTION public.insert_or_get_plaintiff(TEXT, TEXT, UUID, INTEGER, TEXT) TO service_role;
-- ============================================================================
-- 5. Update insert_or_get_judgment RPC to accept plaintiff_id
-- ============================================================================
CREATE OR REPLACE FUNCTION public.insert_or_get_judgment(
        p_case_number TEXT,
        p_plaintiff_name TEXT DEFAULT NULL,
        p_defendant_name TEXT DEFAULT NULL,
        p_judgment_amount NUMERIC DEFAULT NULL,
        p_entry_date DATE DEFAULT NULL,
        p_court TEXT DEFAULT NULL,
        p_county TEXT DEFAULT NULL,
        p_source_file TEXT DEFAULT NULL,
        p_plaintiff_id BIGINT DEFAULT NULL
    ) RETURNS TABLE (id BIGINT, was_inserted BOOLEAN) LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_id BIGINT;
BEGIN
SELECT j.id INTO v_id
FROM public.judgments j
WHERE j.case_number = UPPER(TRIM(p_case_number))
LIMIT 1;
IF v_id IS NOT NULL THEN RETURN QUERY
SELECT v_id,
    false;
RETURN;
END IF;
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
        updated_at,
        plaintiff_id
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
        NOW(),
        p_plaintiff_id
    )
RETURNING public.judgments.id INTO v_id;
RETURN QUERY
SELECT v_id,
    true;
EXCEPTION
WHEN unique_violation THEN
SELECT j.id INTO v_id
FROM public.judgments j
WHERE j.case_number = UPPER(TRIM(p_case_number))
LIMIT 1;
RETURN QUERY
SELECT v_id,
    false;
END;
$$;
COMMENT ON FUNCTION public.insert_or_get_judgment(
    TEXT,
    TEXT,
    TEXT,
    NUMERIC,
    DATE,
    TEXT,
    TEXT,
    TEXT,
    BIGINT
) IS 'Idempotent upsert for judgments with optional plaintiff linkage.';
GRANT EXECUTE ON FUNCTION public.insert_or_get_judgment(
        TEXT,
        TEXT,
        TEXT,
        NUMERIC,
        DATE,
        TEXT,
        TEXT,
        TEXT,
        BIGINT
    ) TO service_role;
-- ============================================================================
-- 6. Refresh ops.v_intake_monitor with plaintiff counters surfaced
-- ============================================================================
-- DROP the view first since column names are changing (cannot use CREATE OR REPLACE alone)
DROP VIEW IF EXISTS ops.v_intake_monitor;
CREATE VIEW ops.v_intake_monitor AS WITH batch_stats AS (
    SELECT b.id,
        b.filename,
        b.source,
        b.status,
        b.row_count_raw AS total_rows,
        b.row_count_valid AS valid_rows,
        b.row_count_invalid AS error_rows,
        b.plaintiff_inserted,
        b.plaintiff_duplicate,
        b.plaintiff_failed,
        COALESCE(
            b.stats,
            '{}'::jsonb
        ) || jsonb_build_object(
            'plaintiffs_inserted',
            b.plaintiff_inserted,
            'plaintiffs_duplicate',
            b.plaintiff_duplicate,
            'plaintiffs_failed',
            b.plaintiff_failed
        ) AS stats,
        b.created_at,
        b.started_at,
        b.completed_at,
        b.created_by,
        b.worker_id,
        CASE
            WHEN b.row_count_raw > 0 THEN ROUND(
                (b.row_count_valid::numeric / b.row_count_raw) * 100,
                1
            )
            ELSE 0
        END AS success_rate,
        CASE
            WHEN b.completed_at IS NOT NULL
            AND b.started_at IS NOT NULL THEN EXTRACT(
                EPOCH
                FROM (b.completed_at - b.started_at)
            )::integer
            ELSE NULL
        END AS duration_seconds
    FROM ops.ingest_batches b
),
error_preview AS (
    SELECT batch_id,
        jsonb_agg(
            jsonb_build_object(
                'row',
                row_index,
                'code',
                error_code,
                'message',
                LEFT(error_details, 100)
            )
            ORDER BY row_index
        ) FILTER (
            WHERE status = 'error'
        ) AS recent_errors
    FROM (
            SELECT batch_id,
                row_index,
                error_code,
                error_details,
                status
            FROM ops.intake_logs
            WHERE status = 'error'
            ORDER BY created_at DESC
            LIMIT 5
        ) sub
    GROUP BY batch_id
)
SELECT bs.id,
    bs.filename,
    bs.source,
    bs.status,
    bs.total_rows,
    bs.valid_rows,
    bs.error_rows,
    bs.plaintiff_inserted,
    bs.plaintiff_duplicate,
    bs.plaintiff_failed,
    bs.success_rate,
    bs.duration_seconds,
    bs.created_at,
    bs.started_at,
    bs.completed_at,
    bs.created_by,
    bs.worker_id,
    bs.stats,
    COALESCE(ep.recent_errors, '[]'::jsonb) AS recent_errors,
    CASE
        WHEN bs.status = 'failed' THEN 'critical'
        WHEN bs.error_rows > 0
        AND bs.success_rate < 90 THEN 'warning'
        WHEN bs.status = 'completed' THEN 'healthy'
        WHEN bs.status = 'processing' THEN 'running'
        ELSE 'pending'
    END AS health_status
FROM batch_stats bs
    LEFT JOIN error_preview ep ON bs.id = ep.batch_id
ORDER BY bs.created_at DESC;
-- ============================================================================
-- 7. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';