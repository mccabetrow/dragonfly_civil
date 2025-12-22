-- ============================================================================
-- Migration: Self-Healing Reaper Scheduler
-- Created: 2025-12-22
-- Purpose: Automate ops.reap_stuck_jobs via pg_cron with full audit visibility
-- ============================================================================
--
-- SELF-HEALING ARCHITECTURE:
-- ============================================================================
-- This migration establishes the "Always-On" reaper for Dragonfly Civil:
--
--   1. pg_cron runs ops.reap_stuck_jobs(10) every 5 minutes
--   2. All reaper activity is logged in cron.job_run_details
--   3. Audit views expose reaper metrics to dashboards
--   4. CEO Dashboard can show recovery statistics
--
-- RELIABILITY INVARIANT:
-- Stuck jobs (processing > 10 min) are automatically recovered:
--   - Reset to 'pending' with exponential backoff (if attempts < max)
--   - Move to DLQ (failed) if max attempts exceeded
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. ENABLE PG_CRON EXTENSION
-- ============================================================================
-- pg_cron is available on Supabase Pro, Team, and Enterprise tiers
DO $$ BEGIN -- Check if pg_cron extension is available
IF EXISTS (
    SELECT 1
    FROM pg_available_extensions
    WHERE name = 'pg_cron'
) THEN -- Enable pg_cron if not already enabled
CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA extensions;
RAISE NOTICE '[pg_cron] Extension enabled successfully';
ELSE RAISE NOTICE '[pg_cron] Extension not available on this tier - using Python fallback';
END IF;
EXCEPTION
WHEN insufficient_privilege THEN RAISE NOTICE '[pg_cron] Insufficient privileges to create extension';
WHEN OTHERS THEN RAISE NOTICE '[pg_cron] Could not enable extension: %',
SQLERRM;
END $$;
-- ============================================================================
-- 2. GRANT EXECUTE PERMISSION ON REAPER FUNCTION
-- ============================================================================
-- Ensure the postgres user (cron executor) can call the reaper
DO $$ BEGIN -- Grant execute to postgres (cron runs as postgres)
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INT) TO postgres;
RAISE NOTICE '[Permissions] EXECUTE granted on ops.reap_stuck_jobs to postgres';
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE '[Permissions] ops.reap_stuck_jobs function not found - will be created separately';
WHEN OTHERS THEN RAISE NOTICE '[Permissions] Could not grant: %',
SQLERRM;
END $$;
-- ============================================================================
-- 3. SCHEDULE THE DRAGONFLY REAPER JOB
-- ============================================================================
-- Schedule: Every 5 minutes (*/5 * * * *)
-- Timeout: 10 minutes (jobs processing > 10 min are stuck)
-- Job Name: 'dragonfly_reaper'
DO $$
DECLARE job_exists BOOLEAN;
BEGIN -- Check if cron schema exists (pg_cron enabled)
IF NOT EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'cron'
) THEN RAISE NOTICE '[Scheduler] cron schema not found - pg_cron not enabled';
RETURN;
END IF;
-- Check if job already exists
SELECT EXISTS (
        SELECT 1
        FROM cron.job
        WHERE jobname = 'dragonfly_reaper'
    ) INTO job_exists;
-- Remove existing schedule if present (idempotent)
IF job_exists THEN PERFORM cron.unschedule('dragonfly_reaper');
RAISE NOTICE '[Scheduler] Removed existing dragonfly_reaper schedule';
END IF;
-- Create new schedule
-- Job: dragonfly_reaper | Schedule: every 5 min | Timeout: 10 min
PERFORM cron.schedule(
    'dragonfly_reaper',
    '*/5 * * * *',
    'SELECT ops.reap_stuck_jobs(10)'
);
RAISE NOTICE '[Scheduler] Created dragonfly_reaper: runs every 5 minutes with 10 min timeout';
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE '[Scheduler] cron.schedule not available';
WHEN OTHERS THEN RAISE NOTICE '[Scheduler] Could not schedule reaper: %',
SQLERRM;
END $$;
-- ============================================================================
-- 4. CREATE REAPER AUDIT VIEW
-- ============================================================================
-- View: ops.v_reaper_audit
-- Shows detailed reaper run history from cron.job_run_details
-- Only created if pg_cron is enabled (cron schema exists)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'cron'
) THEN RAISE NOTICE '[Views] Skipping v_reaper_audit - cron schema not found';
RETURN;
END IF;
EXECUTE $view$
CREATE OR REPLACE VIEW ops.v_reaper_audit AS
SELECT jrd.runid AS run_id,
    jrd.job_pid,
    jrd.start_time,
    jrd.end_time,
    jrd.status,
    jrd.return_message,
    -- Parse the return value (reap_stuck_jobs returns an integer count)
    CASE
        WHEN jrd.status = 'succeeded'
        AND jrd.return_message ~ '^\d+$' THEN jrd.return_message::INT
        ELSE 0
    END AS jobs_reaped,
    -- Calculate duration
    EXTRACT(
        EPOCH
        FROM (jrd.end_time - jrd.start_time)
    ) AS duration_seconds
FROM cron.job_run_details jrd
    JOIN cron.job j ON j.jobid = jrd.jobid
WHERE j.jobname = 'dragonfly_reaper'
ORDER BY jrd.start_time DESC $view$;
COMMENT ON VIEW ops.v_reaper_audit IS 'Audit trail of all dragonfly_reaper cron runs with parsed results';
-- Grant access to monitoring roles
BEGIN
GRANT SELECT ON ops.v_reaper_audit TO service_role;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
BEGIN
GRANT SELECT ON ops.v_reaper_audit TO dragonfly_app;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
BEGIN
GRANT SELECT ON ops.v_reaper_audit TO dragonfly_readonly;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
BEGIN
GRANT SELECT ON ops.v_reaper_audit TO dragonfly_viewer;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
RAISE NOTICE '[Views] Created ops.v_reaper_audit';
END $$;
-- ============================================================================
-- 5. CREATE CEO DASHBOARD METRICS VIEW
-- ============================================================================
-- View: ops.v_reaper_metrics
-- Provides summary metrics for the CEO Dashboard
-- Only created if pg_cron is enabled (cron schema exists)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'cron'
) THEN RAISE NOTICE '[Views] Skipping v_reaper_metrics - cron schema not found';
RETURN;
END IF;
EXECUTE $view$
CREATE OR REPLACE VIEW ops.v_reaper_metrics AS
SELECT -- Run counts
    COUNT(*) FILTER (
        WHERE start_time > NOW() - INTERVAL '24 hours'
    ) AS reaper_runs_24h,
    COUNT(*) FILTER (
        WHERE start_time > NOW() - INTERVAL '1 hour'
    ) AS reaper_runs_1h,
    -- Success rate (last 24 hours)
    ROUND(
        100.0 * COUNT(*) FILTER (
            WHERE status = 'succeeded'
                AND start_time > NOW() - INTERVAL '24 hours'
        ) / NULLIF(
            COUNT(*) FILTER (
                WHERE start_time > NOW() - INTERVAL '24 hours'
            ),
            0
        ),
        2
    ) AS reaper_success_rate_24h,
    -- Last reap time
    MAX(start_time) FILTER (
        WHERE status = 'succeeded'
    ) AS last_successful_reap,
    MAX(start_time) AS last_reap_attempt,
    -- Jobs recovered (parsing return_message as integer)
    COALESCE(
        SUM(
            CASE
                WHEN status = 'succeeded'
                AND return_message ~ '^\d+$' THEN return_message::INT
                ELSE 0
            END
        ) FILTER (
            WHERE start_time > NOW() - INTERVAL '24 hours'
        ),
        0
    ) AS jobs_recovered_24h,
    COALESCE(
        SUM(
            CASE
                WHEN status = 'succeeded'
                AND return_message ~ '^\d+$' THEN return_message::INT
                ELSE 0
            END
        ) FILTER (
            WHERE start_time > NOW() - INTERVAL '1 hour'
        ),
        0
    ) AS jobs_recovered_1h,
    -- Failure count (for alerting)
    COUNT(*) FILTER (
        WHERE status = 'failed'
            AND start_time > NOW() - INTERVAL '24 hours'
    ) AS reaper_failures_24h,
    -- Average duration
    ROUND(
        AVG(
            EXTRACT(
                EPOCH
                FROM (end_time - start_time)
            )
        ) FILTER (
            WHERE status = 'succeeded'
                AND start_time > NOW() - INTERVAL '24 hours'
        ),
        2
    ) AS avg_duration_seconds_24h
FROM cron.job_run_details jrd
    JOIN cron.job j ON j.jobid = jrd.jobid
WHERE j.jobname = 'dragonfly_reaper' $view$;
COMMENT ON VIEW ops.v_reaper_metrics IS 'CEO Dashboard metrics for the self-healing reaper system';
-- Grant access to monitoring roles
BEGIN
GRANT SELECT ON ops.v_reaper_metrics TO service_role;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
BEGIN
GRANT SELECT ON ops.v_reaper_metrics TO dragonfly_app;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
BEGIN
GRANT SELECT ON ops.v_reaper_metrics TO dragonfly_readonly;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
RAISE NOTICE '[Views] Created ops.v_reaper_metrics';
END $$;
-- ============================================================================
-- 6. UPDATE EXISTING REAPER STATUS VIEW
-- ============================================================================
-- Enhanced v_reaper_status with cron integration
-- Only created if pg_cron is enabled (cron schema exists)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'cron'
) THEN RAISE NOTICE '[Views] Skipping v_reaper_status - cron schema not found';
RETURN;
END IF;
-- Drop existing view to avoid column name/order conflicts
DROP VIEW IF EXISTS ops.v_reaper_status;
EXECUTE $view$ CREATE VIEW ops.v_reaper_status (
    scheduler_type,
    is_scheduled,
    currently_stuck_jobs,
    recently_failed_jobs,
    pending_jobs,
    last_successful_reap,
    health_status
) AS
SELECT -- Scheduler info
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM pg_namespace
            WHERE nspname = 'cron'
        ) THEN 'pg_cron'
        ELSE 'python_fallback'
    END,
    -- Is the job scheduled?
    EXISTS (
        SELECT 1
        FROM cron.job
        WHERE jobname = 'dragonfly_reaper'
    ),
    -- Current queue health
    (
        SELECT COUNT(*)
        FROM ops.job_queue
        WHERE status = 'processing'
            AND started_at < NOW() - INTERVAL '10 minutes'
    ),
    (
        SELECT COUNT(*)
        FROM ops.job_queue
        WHERE status = 'failed'
            AND updated_at > NOW() - INTERVAL '1 hour'
    ),
    (
        SELECT COUNT(*)
        FROM ops.job_queue
        WHERE status = 'pending'
    ),
    -- Last reaper activity from cron
    (
        SELECT MAX(start_time)
        FROM cron.job_run_details jrd
            JOIN cron.job j ON j.jobid = jrd.jobid
        WHERE j.jobname = 'dragonfly_reaper'
            AND jrd.status = 'succeeded'
    ),
    -- Health status
    CASE
        WHEN (
            SELECT COUNT(*)
            FROM ops.job_queue
            WHERE status = 'processing'
                AND started_at < NOW() - INTERVAL '10 minutes'
        ) > 10 THEN 'critical'
        WHEN (
            SELECT COUNT(*)
            FROM ops.job_queue
            WHERE status = 'processing'
                AND started_at < NOW() - INTERVAL '10 minutes'
        ) > 0 THEN 'warning'
        ELSE 'healthy'
    END $view$;
COMMENT ON VIEW ops.v_reaper_status IS 'Real-time reaper and queue health status';
-- Grant access to monitoring roles
BEGIN
GRANT SELECT ON ops.v_reaper_status TO service_role;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
BEGIN
GRANT SELECT ON ops.v_reaper_status TO dragonfly_app;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
BEGIN
GRANT SELECT ON ops.v_reaper_status TO dragonfly_readonly;
EXCEPTION
WHEN undefined_object THEN NULL;
END;
RAISE NOTICE '[Views] Created ops.v_reaper_status';
END $$;
-- ============================================================================
-- 7. VERIFICATION QUERIES
-- ============================================================================
-- Run these after applying the migration to verify success:
--
-- 1. Check if the job is scheduled:
--    SELECT * FROM cron.job WHERE jobname = 'dragonfly_reaper';
--
-- 2. View recent reaper runs:
--    SELECT * FROM ops.v_reaper_audit LIMIT 10;
--
-- 3. Check CEO Dashboard metrics:
--    SELECT * FROM ops.v_reaper_metrics;
--
-- 4. Check overall reaper health:
--    SELECT * FROM ops.v_reaper_status;
--
-- 5. Manually trigger the reaper (for testing):
--    SELECT ops.reap_stuck_jobs(10);
--
-- ============================================================================
COMMIT;
-- ============================================================================
-- CEO DASHBOARD METRIC QUERY
-- ============================================================================
-- Use this query directly in the CEO Dashboard or wrap in an RPC:
--
-- SELECT
--     reaper_runs_24h,
--     reaper_success_rate_24h,
--     last_successful_reap AS last_reap_time,
--     jobs_recovered_24h,
--     reaper_failures_24h,
--     CASE
--         WHEN reaper_failures_24h > 5 THEN 'critical'
--         WHEN reaper_failures_24h > 0 THEN 'warning'
--         WHEN jobs_recovered_24h > 0 THEN 'active'
--         ELSE 'healthy'
--     END AS reaper_status
-- FROM ops.v_reaper_metrics;
--
-- ============================================================================