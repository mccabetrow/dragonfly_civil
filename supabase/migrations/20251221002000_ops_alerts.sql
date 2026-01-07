-- ============================================================================
-- Migration: Ops Alerts View
-- Created: 2024-12-21
-- Description: Creates analytics.v_ops_alerts for system health monitoring
-- ============================================================================
-- Ensure analytics schema exists
CREATE SCHEMA IF NOT EXISTS analytics;
-- VIEW: analytics.v_ops_alerts
-- Single-row summary of system health alerts for the Ops Console sidebar
DROP VIEW IF EXISTS analytics.v_ops_alerts CASCADE;
CREATE VIEW analytics.v_ops_alerts AS
SELECT -- Count of failed jobs in the last 24 hours
    COALESCE(
        (
            SELECT COUNT(*)::INTEGER
            FROM ops.job_queue
            WHERE status = 'failed'
                AND created_at >= NOW() - INTERVAL '24 hours'
        ),
        0
    ) AS queue_failed_24h,
    -- Count of failed ingestion batches in the last 24 hours
    COALESCE(
        (
            SELECT COUNT(*)::INTEGER
            FROM ops.ingest_batches
            WHERE status = 'failed'
                AND created_at >= NOW() - INTERVAL '24 hours'
        ),
        0
    ) AS ingest_failures_24h,
    -- Count of stalled workflows (pending jobs older than 7 days)
    COALESCE(
        (
            SELECT COUNT(*)::INTEGER
            FROM ops.job_queue
            WHERE status = 'pending'
                AND created_at < NOW() - INTERVAL '7 days'
        ),
        0
    ) AS stalled_workflows,
    -- System status: 'Healthy' if all counts are 0, else 'Critical'
    CASE
        WHEN COALESCE(
            (
                SELECT COUNT(*)
                FROM ops.job_queue
                WHERE status = 'failed'
                    AND created_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) = 0
        AND COALESCE(
            (
                SELECT COUNT(*)
                FROM ops.ingest_batches
                WHERE status = 'failed'
                    AND created_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) = 0
        AND COALESCE(
            (
                SELECT COUNT(*)
                FROM ops.job_queue
                WHERE status = 'pending'
                    AND created_at < NOW() - INTERVAL '7 days'
            ),
            0
        ) = 0 THEN 'Healthy'::TEXT
        ELSE 'Critical'::TEXT
    END AS system_status,
    -- Timestamp for cache invalidation
    NOW() AS computed_at;
COMMENT ON VIEW analytics.v_ops_alerts IS 'System health alerts for Ops Console sidebar - shows failed jobs, ingest failures, and stalled workflows';
-- ============================================================================
-- RPC Function for easier API access
-- ============================================================================
CREATE OR REPLACE FUNCTION analytics.get_ops_alerts() RETURNS TABLE (
        queue_failed_24h INTEGER,
        ingest_failures_24h INTEGER,
        stalled_workflows INTEGER,
        system_status TEXT,
        computed_at TIMESTAMPTZ
    ) LANGUAGE sql SECURITY DEFINER STABLE AS $$
SELECT queue_failed_24h,
    ingest_failures_24h,
    stalled_workflows,
    system_status,
    computed_at
FROM analytics.v_ops_alerts;
$$;
COMMENT ON FUNCTION analytics.get_ops_alerts IS 'Returns current system health alerts for the Ops Console';
-- ============================================================================
-- PERMISSIONS
-- ============================================================================
GRANT USAGE ON SCHEMA analytics TO authenticated;
GRANT USAGE ON SCHEMA analytics TO service_role;
GRANT SELECT ON analytics.v_ops_alerts TO authenticated;
GRANT SELECT ON analytics.v_ops_alerts TO service_role;
GRANT EXECUTE ON FUNCTION analytics.get_ops_alerts TO authenticated;
GRANT EXECUTE ON FUNCTION analytics.get_ops_alerts TO service_role;
