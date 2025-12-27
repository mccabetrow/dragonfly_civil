-- =============================================================================
-- ops/diagnose_cron.sql
-- Dragonfly Civil - pg_cron Health Diagnostic
-- =============================================================================
-- Run this in Supabase SQL Editor (PROD) to verify pg_cron is healthy.
-- Requires: pg_cron extension enabled (Supabase Pro/Team)
--
-- USAGE: Run each query separately or run the entire script.
--        Results appear in separate result tabs.
-- =============================================================================
-- === 1. SCHEDULED CRON JOBS ===
-- Is the reaper scheduled?
-- Expected: Should see a row for the reaper job with active = true
-- If empty: pg_cron is not configured or no jobs scheduled
SELECT jobid,
    jobname,
    schedule,
    active,
    command
FROM cron.job
ORDER BY jobname;
-- === 2. RECENT JOB RUN HISTORY (Last 10) ===
-- Is pg_cron actually executing?
-- Expected: Multiple rows with status = 'succeeded'
-- If status = 'failed': Check return_message for error details
-- If no rows: pg_cron has never run (check schedule, check extension)
SELECT rd.runid,
    j.jobname,
    rd.status,
    rd.start_time,
    rd.end_time,
    EXTRACT(
        EPOCH
        FROM (rd.end_time - rd.start_time)
    )::numeric(10, 2) AS duration_sec,
    LEFT(rd.return_message, 100) AS return_message_preview
FROM cron.job_run_details rd
    JOIN cron.job j ON j.jobid = rd.jobid
ORDER BY rd.start_time DESC
LIMIT 10;
-- === 3. STUCK JOBS CHECK ===
-- Is the reaper actually doing its job?
-- Expected: stuck_jobs = 0
-- If > 0: Reaper is not running or is failing to reclaim jobs
SELECT count(*) AS stuck_jobs,
    MIN(claimed_at) AS oldest_stuck_claim,
    NOW() - MIN(claimed_at) AS oldest_stuck_age
FROM ops.job_queue
WHERE claimed_at < NOW() - INTERVAL '20 minutes'
    AND status = 'processing';
-- === 4. REAPER LAST ACTIVITY ===
-- When did the reaper last successfully run?
-- Expected: time_since_last_run < 10 minutes (for 5-min schedule)
-- If NULL: Reaper has never succeeded
-- If > 15 min: Reaper may be failing or disabled
SELECT j.jobname,
    MAX(rd.end_time) AS last_successful_run,
    NOW() - MAX(rd.end_time) AS time_since_last_run
FROM cron.job_run_details rd
    JOIN cron.job j ON j.jobid = rd.jobid
WHERE rd.status = 'succeeded'
    AND j.jobname LIKE '%reaper%'
GROUP BY j.jobname;
-- === 5. QUEUE HEALTH SNAPSHOT ===
-- Quick snapshot of queue state by status
SELECT status,
    COUNT(*) AS job_count,
    MIN(created_at) AS oldest_job,
    MAX(created_at) AS newest_job
FROM ops.job_queue
GROUP BY status
ORDER BY status;
-- === 6. PG_CRON EXTENSION STATUS ===
-- Is the extension even enabled?
-- Expected: One row showing pg_cron with version
-- If empty: Extension not installed (Supabase free tier limitation)
SELECT extname,
    extversion,
    extnamespace::regnamespace AS schema
FROM pg_extension
WHERE extname = 'pg_cron';
-- =============================================================================
-- DIAGNOSTIC COMPLETE
-- =============================================================================
-- Review results above. Key indicators:
--   ✓ Query 1: active = true for reaper job
--   ✓ Query 2: Recent runs with status = 'succeeded'
--   ✓ Query 3: stuck_jobs = 0
--   ✓ Query 4: time_since_last_run < 15 minutes
--   ✓ Query 6: pg_cron extension present
-- =============================================================================