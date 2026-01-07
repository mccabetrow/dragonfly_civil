-- ============================================================================
-- Migration: 20250104_ops_views.sql
-- Description: SRE Observability Views for Ingestion Pipeline
-- ============================================================================
-- Purpose:
--   Production-grade visibility into the Dragonfly ingestion engine.
--   Creates three analytics views in the ops schema for:
--     1. Batch performance metrics (throughput, timing, dedupe rates)
--     2. Error distribution analysis
--     3. Pipeline health monitoring (stuck batches)
--
-- Schema: ops (operational analytics)
-- Target: Dashboards + Alerting (Sentinel script)
-- ============================================================================
BEGIN;
-- ============================================================================
-- SECTION 0: CREATE OPS SCHEMA (IF NOT EXISTS)
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ops;
COMMENT ON SCHEMA ops IS 'Operational analytics and monitoring views for SRE dashboards and alerting';
-- ============================================================================
-- SECTION 1: BATCH PERFORMANCE METRICS
-- ============================================================================
-- Purpose: Hourly rollup of batch ingestion performance
-- Use Case: Dashboard showing throughput trends, timing metrics, dedupe efficiency
-- Query Pattern: SELECT * FROM ops.v_batch_performance ORDER BY hour_bucket DESC LIMIT 24;
-- ============================================================================
DROP VIEW IF EXISTS ops.v_batch_performance CASCADE;
CREATE VIEW ops.v_batch_performance AS
SELECT date_trunc('hour', created_at) AS hour_bucket,
    COUNT(*) AS total_batches,
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ) AS completed_batches,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ) AS failed_batches,
    -- Timing Metrics (averages for completed batches only)
    ROUND(
        AVG(parse_duration_ms) FILTER (
            WHERE status = 'completed'
        ),
        2
    ) AS avg_parse_ms,
    ROUND(
        AVG(db_duration_ms) FILTER (
            WHERE status = 'completed'
        ),
        2
    ) AS avg_db_ms,
    ROUND(
        AVG(parse_duration_ms + db_duration_ms) FILTER (
            WHERE status = 'completed'
        ),
        2
    ) AS avg_total_ms,
    -- Row Counts
    SUM(row_count_total) AS total_rows,
    SUM(row_count_inserted) AS inserted_rows,
    SUM(row_count_duplicate) AS skipped_rows,
    SUM(row_count_invalid) AS error_rows,
    -- Dedupe Rate (skipped / total)
    CASE
        WHEN SUM(row_count_total) > 0 THEN ROUND(
            100.0 * SUM(row_count_duplicate) / SUM(row_count_total),
            2
        )
        ELSE 0.0
    END AS dedupe_rate_pct,
    -- Error Rate (invalid / total)
    CASE
        WHEN SUM(row_count_total) > 0 THEN ROUND(
            100.0 * SUM(row_count_invalid) / SUM(row_count_total),
            2
        )
        ELSE 0.0
    END AS error_rate_pct
FROM intake.simplicity_batches
WHERE created_at >= NOW() - INTERVAL '7 days' -- Rolling 7-day window
GROUP BY date_trunc('hour', created_at)
ORDER BY hour_bucket DESC;
COMMENT ON VIEW ops.v_batch_performance IS 'Hourly rollup of ingestion performance: throughput, timing, dedupe rates, error rates. For SRE dashboards.';
-- ============================================================================
-- SECTION 2: ERROR DISTRIBUTION ANALYSIS
-- ============================================================================
-- Purpose: Aggregate error codes across batches to identify systemic issues
-- Use Case: Error report showing "Top 10 Errors by Frequency"
-- Query Pattern: SELECT * FROM ops.v_error_distribution ORDER BY occurrence_count DESC LIMIT 10;
-- ============================================================================
DROP VIEW IF EXISTS ops.v_error_distribution CASCADE;
CREATE VIEW ops.v_error_distribution AS
SELECT re.error_code,
    COUNT(*) AS occurrence_count,
    COUNT(DISTINCT re.batch_id) AS affected_batches,
    -- Sample error message (first alphabetically for consistency)
    MIN(re.error_message) AS sample_message,
    -- Recent occurrence
    MAX(re.created_at) AS last_seen_at
FROM intake.row_errors re
WHERE re.created_at >= NOW() - INTERVAL '7 days' -- Rolling 7-day window
GROUP BY re.error_code
ORDER BY occurrence_count DESC;
COMMENT ON VIEW ops.v_error_distribution IS 'Top error codes by frequency across all batches. For identifying systemic validation issues.';
-- ============================================================================
-- SECTION 3: PIPELINE HEALTH MONITOR
-- ============================================================================
-- Purpose: Real-time snapshot of pipeline state with age tracking
-- Use Case: Sentinel script checks for stuck batches (processing > 10 mins)
-- Query Pattern: SELECT * FROM ops.v_pipeline_health WHERE status = 'processing' AND age_minutes > 10;
-- ============================================================================
DROP VIEW IF EXISTS ops.v_pipeline_health CASCADE;
CREATE VIEW ops.v_pipeline_health AS
SELECT status,
    COUNT(*) AS batch_count,
    -- Oldest batch in this state
    MIN(created_at) AS oldest_batch_at,
    -- Age of oldest batch in minutes
    EXTRACT(
        EPOCH
        FROM (NOW() - MIN(created_at))
    ) / 60 AS oldest_age_minutes,
    -- Recent batch for context
    MAX(created_at) AS newest_batch_at
FROM intake.simplicity_batches
WHERE status IN (
        'uploaded',
        'staging',
        'validating',
        'transforming',
        'inserting',
        'upserting',
        'processing',
        'failed'
    )
GROUP BY status
ORDER BY CASE
        status
        WHEN 'failed' THEN 1
        WHEN 'processing' THEN 2
        WHEN 'inserting' THEN 3
        WHEN 'upserting' THEN 4
        WHEN 'transforming' THEN 5
        WHEN 'validating' THEN 6
        WHEN 'staging' THEN 7
        WHEN 'uploaded' THEN 8
        ELSE 9
    END;
COMMENT ON VIEW ops.v_pipeline_health IS 'Real-time pipeline status with age tracking. Used by Sentinel to detect stuck batches.';
-- ============================================================================
-- SECTION 4: GRANT PERMISSIONS (anon read-only)
-- ============================================================================
-- Ops views are safe for frontend dashboards (no PII, aggregated only)
GRANT USAGE ON SCHEMA ops TO anon;
GRANT SELECT ON ops.v_batch_performance TO anon;
GRANT SELECT ON ops.v_error_distribution TO anon;
GRANT SELECT ON ops.v_pipeline_health TO anon;
-- Service role (backend) already has superuser access
-- ============================================================================
-- MIGRATION COMPLETE
-- ============================================================================
COMMIT;
-- ============================================================================
-- USAGE EXAMPLES
-- ============================================================================
-- Example 1: Get last 24 hours of batch performance
-- SELECT * FROM ops.v_batch_performance ORDER BY hour_bucket DESC LIMIT 24;
-- Example 2: Find top 10 error codes
-- SELECT error_code, occurrence_count, affected_batches, sample_message 
-- FROM ops.v_error_distribution 
-- ORDER BY occurrence_count DESC 
-- LIMIT 10;
-- Example 3: Check for stuck batches (Sentinel use case)
-- SELECT * 
-- FROM ops.v_pipeline_health 
-- WHERE status IN ('processing', 'validating', 'inserting') 
--   AND oldest_age_minutes > 10;
-- Example 4: Dashboard - Today's throughput
-- SELECT 
--     hour_bucket::time AS hour,
--     total_batches,
--     completed_batches,
--     total_rows,
--     ROUND(total_rows::numeric / NULLIF(total_batches, 0), 0) AS avg_rows_per_batch
-- FROM ops.v_batch_performance
-- WHERE hour_bucket >= CURRENT_DATE
-- ORDER BY hour_bucket;
