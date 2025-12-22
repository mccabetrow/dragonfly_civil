-- ============================================================================
-- Migration: Schedule Reaper for Stuck Jobs
-- Created: 2025-12-22
-- Purpose: Automatic recovery of stuck jobs via pg_cron scheduling
-- ============================================================================
--
-- RELIABILITY INVARIANT:
-- The ops.reap_stuck_jobs function must run every 5 minutes to:
--   1. Detect jobs stuck in 'processing' state > 15 minutes
--   2. Reset them to 'pending' with exponential backoff (if attempts < max)
--   3. Move them to DLQ (failed) if max attempts exceeded
--
-- SCHEDULING:
-- Uses pg_cron extension if available (Supabase Pro+)
-- Falls back to Python worker schedule if pg_cron unavailable
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. ENABLE PG_CRON EXTENSION (if available)
-- ============================================================================
-- pg_cron is available on Supabase Pro, Team, and Enterprise tiers
-- This will fail gracefully on Free tier
DO $$ BEGIN -- Check if pg_cron extension exists
IF EXISTS (
    SELECT 1
    FROM pg_available_extensions
    WHERE name = 'pg_cron'
) THEN -- Enable pg_cron if not already enabled
CREATE EXTENSION IF NOT EXISTS pg_cron WITH SCHEMA extensions;
RAISE NOTICE 'pg_cron extension enabled';
ELSE RAISE NOTICE 'pg_cron extension not available on this tier';
END IF;
EXCEPTION
WHEN insufficient_privilege THEN RAISE NOTICE 'pg_cron: Insufficient privileges to create extension';
WHEN OTHERS THEN RAISE NOTICE 'pg_cron: Could not enable extension - %',
SQLERRM;
END $$;
-- ============================================================================
-- 2. SCHEDULE THE REAPER JOB
-- ============================================================================
-- Schedule ops.reap_stuck_jobs(15) to run every 5 minutes
-- The 15 = timeout in minutes (jobs processing > 15 min are stuck)
DO $$ BEGIN -- Check if cron schema exists (pg_cron enabled)
IF EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'cron'
) THEN -- Remove existing schedule if present (idempotent)
PERFORM cron.unschedule('reap_stuck_jobs');
RAISE NOTICE 'Removed existing reap_stuck_jobs schedule (if any)';
EXCEPTION
WHEN undefined_function THEN NULL;
-- cron.unschedule doesn't exist, skip
WHEN OTHERS THEN NULL;
-- Job didn't exist, skip
END;
-- Create new schedule
IF EXISTS (
    SELECT 1
    FROM pg_namespace
    WHERE nspname = 'cron'
) THEN PERFORM cron.schedule(
    'reap_stuck_jobs',
    -- job name
    '*/5 * * * *',
    -- every 5 minutes
    $$SELECT ops.reap_stuck_jobs(15) $$ -- 15 min timeout
);
RAISE NOTICE 'Scheduled reap_stuck_jobs: every 5 minutes with 15 min timeout';
ELSE RAISE NOTICE 'cron schema not found - use Python fallback scheduler';
END IF;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'cron.schedule not available - use Python fallback scheduler';
WHEN OTHERS THEN RAISE NOTICE 'Could not schedule reaper: % - use Python fallback scheduler',
SQLERRM;
END $$;
-- ============================================================================
-- 3. CREATE MONITORING VIEW
-- ============================================================================
-- View to monitor reaper activity
CREATE OR REPLACE VIEW ops.v_reaper_status AS
SELECT CASE
        WHEN EXISTS (
            SELECT 1
            FROM pg_namespace
            WHERE nspname = 'cron'
        ) THEN 'pg_cron'
        ELSE 'python_fallback'
    END AS scheduler_type,
    (
        SELECT COUNT(*)
        FROM ops.job_queue
        WHERE status = 'processing'
            AND started_at < NOW() - INTERVAL '15 minutes'
    ) AS currently_stuck_jobs,
    (
        SELECT COUNT(*)
        FROM ops.job_queue
        WHERE status = 'failed'
            AND updated_at > NOW() - INTERVAL '1 hour'
    ) AS recently_failed_jobs,
    (
        SELECT MAX(updated_at)
        FROM ops.job_queue
        WHERE status = 'pending'
            AND attempts > 0
    ) AS last_reaper_action;
COMMENT ON VIEW ops.v_reaper_status IS 'Monitoring view for the stuck job reaper';
-- Grant access to monitoring roles
GRANT SELECT ON ops.v_reaper_status TO service_role;
GRANT SELECT ON ops.v_reaper_status TO dragonfly_app;
GRANT SELECT ON ops.v_reaper_status TO dragonfly_readonly;
-- ============================================================================
-- 4. VERIFICATION QUERY
-- ============================================================================
-- Run this to verify the schedule is active:
--   SELECT * FROM cron.job WHERE jobname = 'reap_stuck_jobs';
--   SELECT * FROM cron.job_run_details WHERE jobid = (SELECT jobid FROM cron.job WHERE jobname = 'reap_stuck_jobs') ORDER BY start_time DESC LIMIT 10;
COMMIT;
-- ============================================================================
-- PYTHON FALLBACK SCHEDULER
-- ============================================================================
-- If pg_cron is not available, add this to backend/workers/monitor.py:
--
-- import asyncio
-- from datetime import datetime
-- from backend.db import get_supabase_client
--
-- REAPER_INTERVAL_SECONDS = 300  # 5 minutes
-- STUCK_JOB_TIMEOUT_MINUTES = 15
--
-- async def reaper_loop():
--     """Background task to reap stuck jobs every 5 minutes."""
--     client = get_supabase_client()
--     while True:
--         try:
--             result = client.rpc('reap_stuck_jobs', {'p_timeout_minutes': STUCK_JOB_TIMEOUT_MINUTES}).execute()
--             reaped_count = result.data if result.data else 0
--             if reaped_count > 0:
--                 print(f"[REAPER] {datetime.now().isoformat()} - Reaped {reaped_count} stuck jobs")
--         except Exception as e:
--             print(f"[REAPER] Error: {e}")
--         await asyncio.sleep(REAPER_INTERVAL_SECONDS)
--
-- ============================================================================