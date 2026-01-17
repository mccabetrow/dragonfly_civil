-- =============================================================================
-- Plaintiff Intake Moat: Operator Queries
-- =============================================================================
-- 
-- Purpose: Ready-to-run SQL queries for monitoring and debugging the
--          plaintiff intake pipeline.
--
-- Usage: Copy/paste into Supabase SQL Editor or run via psql.
--
-- =============================================================================
-- =============================================================================
-- 1. SHOW LAST 10 IMPORT RUNS
-- =============================================================================
-- Use this to see recent import activity, success rates, and timing.
SELECT ir.id,
    ir.source_system,
    ir.source_batch_id,
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
    )::numeric(10, 2) AS duration_secs,
    ir.error_details->>'message' AS error_message
FROM ingest.import_runs ir
ORDER BY ir.created_at DESC
LIMIT 10;
-- =============================================================================
-- 2. FIND DUPLICATES BLOCKED
-- =============================================================================
-- Shows records that were skipped due to duplicate dedupe_key.
-- These are plaintiffs that already existed from a previous import.
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
ORDER BY pr.created_at DESC
LIMIT 50;
-- =============================================================================
-- 3. SHOW ERRORED ROWS
-- =============================================================================
-- Records that failed processing with error details.
-- Use this to debug parsing or validation failures.
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
ORDER BY pr.created_at DESC
LIMIT 50;
-- =============================================================================
-- 4. CHECK FOR BATCH-LEVEL DUPLICATES
-- =============================================================================
-- Verifies that no duplicate batches exist (should return 0 rows).
-- If rows are returned, the idempotency constraint may have been bypassed.
SELECT source_system,
    source_batch_id,
    file_hash,
    COUNT(*) as run_count,
    array_agg(
        id
        ORDER BY created_at
    ) as run_ids
FROM ingest.import_runs
GROUP BY source_system,
    source_batch_id,
    file_hash
HAVING COUNT(*) > 1
ORDER BY run_count DESC;
-- =============================================================================
-- 5. IMPORT RUN STATISTICS BY SOURCE
-- =============================================================================
-- Aggregated stats per source system for capacity planning.
SELECT source_system,
    COUNT(*) as total_runs,
    SUM(rows_fetched) as total_rows_fetched,
    SUM(rows_inserted) as total_rows_inserted,
    SUM(rows_skipped) as total_rows_skipped,
    SUM(rows_errored) as total_rows_errored,
    ROUND(
        100.0 * SUM(rows_inserted) / NULLIF(SUM(rows_fetched), 0),
        2
    ) as insert_rate_pct,
    MIN(created_at) as first_import,
    MAX(created_at) as last_import
FROM ingest.import_runs
WHERE status = 'completed'
GROUP BY source_system
ORDER BY total_runs DESC;
-- =============================================================================
-- 6. PENDING RECORDS AWAITING PROMOTION
-- =============================================================================
-- Records in plaintiffs_raw that haven't been promoted to public.plaintiffs.
-- Use this to monitor the promotion pipeline backlog.
SELECT pr.source_system,
    COUNT(*) as pending_count,
    MIN(pr.created_at) as oldest_pending,
    MAX(pr.created_at) as newest_pending
FROM ingest.plaintiffs_raw pr
WHERE pr.status = 'pending'
GROUP BY pr.source_system
ORDER BY pending_count DESC;
-- =============================================================================
-- 7. ROW-LEVEL DEDUPE STATS FOR A SPECIFIC RUN
-- =============================================================================
-- Replace the UUID with your target import_run_id.
-- SELECT 
--     ir.id,
--     ir.filename,
--     ir.source_system,
--     COUNT(pr.id) as total_rows,
--     COUNT(CASE WHEN pr.status = 'pending' THEN 1 END) as pending,
--     COUNT(CASE WHEN pr.status = 'processing' THEN 1 END) as processing,
--     COUNT(CASE WHEN pr.status = 'promoted' THEN 1 END) as promoted,
--     COUNT(CASE WHEN pr.status = 'skipped' THEN 1 END) as skipped,
--     COUNT(CASE WHEN pr.status = 'failed' THEN 1 END) as failed
-- FROM ingest.import_runs ir
-- LEFT JOIN ingest.plaintiffs_raw pr ON pr.import_run_id = ir.id
-- WHERE ir.id = 'YOUR-IMPORT-RUN-ID-HERE'
-- GROUP BY ir.id, ir.filename, ir.source_system;
-- =============================================================================
-- 8. FIND PLAINTIFFS BY NAME (FUZZY SEARCH)
-- =============================================================================
-- Search for a plaintiff across all raw records.
-- Replace 'search_term' with the name to search for.
-- SELECT 
--     pr.plaintiff_name,
--     pr.plaintiff_name_normalized,
--     pr.dedupe_key,
--     pr.source_system,
--     pr.status,
--     pr.created_at
-- FROM ingest.plaintiffs_raw pr
-- WHERE pr.plaintiff_name_normalized ILIKE '%search_term%'
-- ORDER BY pr.created_at DESC
-- LIMIT 20;
-- =============================================================================
-- 9. FAILED IMPORTS REQUIRING ATTENTION
-- =============================================================================
-- Import runs that failed completely (not just partial failures).
SELECT ir.id,
    ir.source_system,
    ir.source_batch_id,
    ir.filename,
    ir.created_at,
    ir.error_details->>'message' AS error_message,
    ir.error_details
FROM ingest.import_runs ir
WHERE ir.status = 'failed'
ORDER BY ir.created_at DESC
LIMIT 20;
-- =============================================================================
-- 10. IDEMPOTENCY VERIFICATION
-- =============================================================================
-- Count unique dedupe_keys in plaintiffs_raw to verify no duplicates.
-- total_rows should equal unique_dedupe_keys.
SELECT COUNT(*) as total_rows,
    COUNT(DISTINCT dedupe_key) as unique_dedupe_keys,
    COUNT(*) - COUNT(DISTINCT dedupe_key) as duplicate_count
FROM ingest.plaintiffs_raw;
-- =============================================================================
-- 11. DAILY IMPORT VOLUME
-- =============================================================================
-- Track import volume over time for trend analysis.
SELECT DATE(created_at) as import_date,
    COUNT(*) as runs,
    SUM(rows_fetched) as total_fetched,
    SUM(rows_inserted) as total_inserted,
    SUM(rows_skipped) as total_skipped
FROM ingest.import_runs
WHERE created_at >= now() - interval '30 days'
GROUP BY DATE(created_at)
ORDER BY import_date DESC;
-- =============================================================================
-- 12. SCHEMA HEALTH CHECK
-- =============================================================================
-- Verify the intake moat schema is properly configured.
SELECT 'ingest.import_runs' as table_name,
    (
        SELECT COUNT(*)
        FROM ingest.import_runs
    ) as row_count,
    (
        SELECT COUNT(*)
        FROM ingest.import_runs
        WHERE status = 'completed'
    ) as completed,
    (
        SELECT COUNT(*)
        FROM ingest.import_runs
        WHERE status = 'failed'
    ) as failed
UNION ALL
SELECT 'ingest.plaintiffs_raw' as table_name,
    (
        SELECT COUNT(*)
        FROM ingest.plaintiffs_raw
    ) as row_count,
    (
        SELECT COUNT(*)
        FROM ingest.plaintiffs_raw
        WHERE status = 'promoted'
    ) as promoted,
    (
        SELECT COUNT(*)
        FROM ingest.plaintiffs_raw
        WHERE status = 'pending'
    ) as pending;
-- =============================================================================
-- END OF OPERATOR QUERIES
-- =============================================================================