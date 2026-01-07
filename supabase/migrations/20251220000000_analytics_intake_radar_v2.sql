-- ============================================================================
-- Migration: analytics.v_intake_radar (v2 - Full Spec)
-- Created: 2025-12-09
-- Purpose: Single-row intake radar metrics for CEO Dashboard
-- ============================================================================
-- Replaces existing v_intake_radar with expanded metrics:
--   - judgments_ingested_24h: Count from public.judgments (last 24h)
--   - judgments_ingested_7d: Count from public.judgments (last 7d)
--   - new_aum_24h: Sum of judgment_amount (last 24h)
--   - validity_rate_24h: (row_count_valid / row_count_raw) * 100 from batches
--   - queue_depth_pending: Count of pending jobs in ops.job_queue
--   - critical_failures_24h: Count of failed batches (last 24h)
--   - avg_processing_time_seconds: Avg seconds from start to complete (last 24h)
-- ============================================================================
-- Ensure analytics schema exists
CREATE SCHEMA IF NOT EXISTS analytics;
GRANT USAGE ON SCHEMA analytics TO authenticated,
    service_role;
-- ============================================================================
-- VIEW: analytics.v_intake_radar (v2)
-- ============================================================================
-- Uses CTEs for efficient aggregation across:
--   - public.judgments
--   - ops.ingest_batches
--   - ops.job_queue
-- Returns exactly ONE ROW with all metrics COALESCE'd to 0 (never null).
-- ============================================================================
-- Drop existing view to allow column name changes
DROP VIEW IF EXISTS analytics.v_intake_radar CASCADE;
CREATE VIEW analytics.v_intake_radar AS WITH judgment_cte AS (
    -- Aggregate judgment metrics for last 24h and 7d
    SELECT COALESCE(
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) AS judgments_ingested_24h,
        COALESCE(
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '7 days'
            ),
            0
        ) AS judgments_ingested_7d,
        COALESCE(
            SUM(judgment_amount) FILTER (
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) AS new_aum_24h
    FROM public.judgments
),
batch_cte AS (
    -- Aggregate batch metrics for last 24h
    SELECT COALESCE(SUM(row_count_valid), 0) AS total_valid_24h,
        COALESCE(SUM(row_count_raw), 0) AS total_raw_24h,
        COALESCE(
            COUNT(*) FILTER (
                WHERE status = 'failed'
            ),
            0
        ) AS critical_failures_24h,
        COALESCE(
            AVG(
                EXTRACT(
                    EPOCH
                    FROM (processed_at - created_at)
                )
            ) FILTER (
                WHERE processed_at IS NOT NULL
            ),
            0
        ) AS avg_processing_time_seconds
    FROM ops.ingest_batches
    WHERE created_at >= NOW() - INTERVAL '24 hours'
),
queue_cte AS (
    -- Count pending jobs in queue
    SELECT COALESCE(
            COUNT(*) FILTER (
                WHERE status::text = 'pending'
            ),
            0
        ) AS queue_depth_pending
    FROM ops.job_queue
)
SELECT -- Judgment intake metrics
    jc.judgments_ingested_24h::INTEGER AS judgments_ingested_24h,
    jc.judgments_ingested_7d::INTEGER AS judgments_ingested_7d,
    ROUND(jc.new_aum_24h::NUMERIC, 2) AS new_aum_24h,
    -- Validity rate: (valid / raw) * 100, default to 100 if no rows
    CASE
        WHEN bc.total_raw_24h = 0 THEN 100.0
        ELSE ROUND(
            (
                bc.total_valid_24h::NUMERIC / bc.total_raw_24h::NUMERIC
            ) * 100,
            2
        )
    END AS validity_rate_24h,
    -- Queue depth
    qc.queue_depth_pending::INTEGER AS queue_depth_pending,
    -- Failures and processing time
    bc.critical_failures_24h::INTEGER AS critical_failures_24h,
    ROUND(bc.avg_processing_time_seconds::NUMERIC, 2) AS avg_processing_time_seconds
FROM judgment_cte jc
    CROSS JOIN batch_cte bc
    CROSS JOIN queue_cte qc;
-- ============================================================================
-- COMMENT on view
-- ============================================================================
COMMENT ON VIEW analytics.v_intake_radar IS 'Single-row intake radar metrics for CEO Dashboard: judgment counts, AUM, validity rate, queue depth, failures, and processing time.';
-- ============================================================================
-- RPC FUNCTION: public.intake_radar_metrics_v2
-- ============================================================================
-- Wrapper function for Supabase REST API consumption.
-- Returns exactly one row with the same columns as the view.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.intake_radar_metrics_v2() RETURNS TABLE (
        judgments_ingested_24h INTEGER,
        judgments_ingested_7d INTEGER,
        new_aum_24h NUMERIC,
        validity_rate_24h NUMERIC,
        queue_depth_pending INTEGER,
        critical_failures_24h INTEGER,
        avg_processing_time_seconds NUMERIC
    ) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
SELECT judgments_ingested_24h,
    judgments_ingested_7d,
    new_aum_24h,
    validity_rate_24h,
    queue_depth_pending,
    critical_failures_24h,
    avg_processing_time_seconds
FROM analytics.v_intake_radar
LIMIT 1;
$$;
COMMENT ON FUNCTION public.intake_radar_metrics_v2() IS 'RPC wrapper for analytics.v_intake_radar - returns single-row intake metrics for CEO Dashboard.';
-- ============================================================================
-- GRANTS
-- ============================================================================
-- View grants
GRANT SELECT ON analytics.v_intake_radar TO authenticated;
GRANT SELECT ON analytics.v_intake_radar TO service_role;
-- RPC function grants
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics_v2() TO authenticated;
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics_v2() TO service_role;
-- ============================================================================
-- Verification (run manually after migration)
-- ============================================================================
-- SELECT * FROM analytics.v_intake_radar;
-- SELECT * FROM public.intake_radar_metrics_v2();
