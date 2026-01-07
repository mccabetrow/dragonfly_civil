-- ============================================================================
-- Migration: Move Ops Alerts to public schema
-- Created: 2024-12-21
-- Description: Creates public.v_ops_alerts for PostgREST access
-- ============================================================================
-- Drop analytics schema objects if they exist
DROP FUNCTION IF EXISTS analytics.get_ops_alerts CASCADE;
DROP VIEW IF EXISTS analytics.v_ops_alerts CASCADE;
-- VIEW: public.v_ops_alerts
-- Single-row summary of system health alerts for the Ops Console sidebar
DROP VIEW IF EXISTS public.v_ops_alerts CASCADE;
CREATE VIEW public.v_ops_alerts AS
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
COMMENT ON VIEW public.v_ops_alerts IS 'System health alerts for Ops Console sidebar - shows failed jobs, ingest failures, and stalled workflows';
-- ============================================================================
-- PERMISSIONS
-- ============================================================================
GRANT SELECT ON public.v_ops_alerts TO authenticated;
GRANT SELECT ON public.v_ops_alerts TO service_role;
GRANT SELECT ON public.v_ops_alerts TO anon;
