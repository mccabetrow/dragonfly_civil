-- ============================================================================
-- Migration: analytics.v_intake_radar
-- Created: 2025-12-09
-- Purpose: Single-row summary view for CEO Dashboard "Intake Radar" widget
-- ============================================================================
-- Create analytics schema if not exists
CREATE SCHEMA IF NOT EXISTS analytics;
-- Grant usage on analytics schema
GRANT USAGE ON SCHEMA analytics TO authenticated,
    service_role;
-- ============================================================================
-- VIEW: analytics.v_intake_radar
-- ============================================================================
-- Returns exactly ONE ROW with key intake metrics:
--   - judgments_24h: Judgments created in last 24 hours
--   - judgments_7d: Judgments created in last 7 days
--   - total_value_24h: Sum of judgment amounts (last 24h)
--   - queue_pending: Pending jobs in ops.job_queue
--   - queue_failed: Failed jobs in ops.job_queue
--   - batch_success_rate: % of successful batches (last 30 days)
-- ============================================================================
CREATE OR REPLACE VIEW analytics.v_intake_radar AS WITH judgment_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            ) AS judgments_24h,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '7 days'
            ) AS judgments_7d,
            COALESCE(
                SUM(judgment_amount) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                ),
                0
            ) AS total_value_24h
        FROM public.judgments
    ),
    queue_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE status::text = 'pending'
            ) AS queue_pending,
            COUNT(*) FILTER (
                WHERE status::text = 'failed'
            ) AS queue_failed
        FROM ops.job_queue
    ),
    batch_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE status = 'completed'
            ) AS completed_count,
            COUNT(*) FILTER (
                WHERE status = 'failed'
            ) AS failed_count,
            COUNT(*) AS total_count,
            MAX(completed_at) FILTER (
                WHERE status = 'completed'
            ) AS last_completed_at
        FROM ops.ingest_batches
        WHERE created_at >= NOW() - INTERVAL '30 days'
    )
SELECT js.judgments_24h::INTEGER,
    js.judgments_7d::INTEGER,
    js.total_value_24h::NUMERIC(15, 2),
    qs.queue_pending::INTEGER,
    qs.queue_failed::INTEGER,
    CASE
        WHEN bs.total_count = 0 THEN 100.0
        ELSE ROUND(
            (
                bs.completed_count::NUMERIC / bs.total_count::NUMERIC
            ) * 100,
            1
        )
    END AS batch_success_rate,
    bs.last_completed_at AS last_import_ts
FROM judgment_stats js
    CROSS JOIN queue_stats qs
    CROSS JOIN batch_stats bs;
-- ============================================================================
-- RPC FUNCTION: intake_radar_metrics
-- ============================================================================
-- Wrapper function for Supabase client to query the view
-- Returns JSONB for easy consumption by REST API
-- ============================================================================
CREATE OR REPLACE FUNCTION public.intake_radar_metrics() RETURNS TABLE (
        total_batches INTEGER,
        rows_imported INTEGER,
        rows_failed INTEGER,
        success_rate NUMERIC,
        batches_in_flight INTEGER,
        last_import_ts TIMESTAMPTZ
    ) LANGUAGE SQL STABLE SECURITY DEFINER AS $$ WITH batch_agg AS (
        SELECT COUNT(*)::INTEGER AS total_batches,
            COALESCE(SUM(row_count_valid), 0)::INTEGER AS rows_imported,
            -- row_count_invalid tracks failed rows per batch
            COALESCE(SUM(row_count_invalid), 0)::INTEGER AS rows_failed,
            COUNT(*) FILTER (
                WHERE status = 'processing'
            )::INTEGER AS batches_in_flight,
            MAX(completed_at) AS last_import_ts
        FROM ops.ingest_batches
    )
SELECT ba.total_batches,
    ba.rows_imported,
    ba.rows_failed,
    CASE
        WHEN (ba.rows_imported + ba.rows_failed) = 0 THEN 100.0
        ELSE ROUND(
            (
                ba.rows_imported::NUMERIC / (ba.rows_imported + ba.rows_failed)::NUMERIC
            ) * 100,
            2
        )
    END AS success_rate,
    ba.batches_in_flight,
    ba.last_import_ts
FROM batch_agg ba;
$$;
-- Grant execute on RPC function
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics() TO authenticated;
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics() TO service_role;
-- ============================================================================
-- GRANTS
-- ============================================================================
GRANT SELECT ON analytics.v_intake_radar TO authenticated;
GRANT SELECT ON analytics.v_intake_radar TO service_role;
-- ============================================================================
-- Verification query (for manual testing)
-- ============================================================================
-- SELECT * FROM analytics.v_intake_radar;
-- SELECT * FROM public.intake_radar_metrics();
