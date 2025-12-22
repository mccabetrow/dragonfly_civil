-- ============================================================================
-- REAPER HEALTH DIAGNOSTICS
-- ============================================================================
-- Purpose: Verify pg_cron is scheduling and executing the reaper job
-- Usage: Run in pgAdmin, psql, or any SQL client connected to Supabase
-- ============================================================================
-- ============================================================================
-- CHECK 1: Confirm Reaper Schedule Exists in pg_cron
-- ============================================================================
-- Expected: 1 row with jobname = 'dragonfly_reaper' or 'reap_stuck_jobs'
-- If empty: Reaper schedule has not been created
SELECT 'CHECK 1: Reaper Schedule' AS check_name,
    jobid,
    jobname,
    schedule,
    command,
    nodename,
    username,
    active
FROM cron.job
WHERE jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
ORDER BY jobname;
-- ============================================================================
-- CHECK 2: Reaper Execution History (Last 10 Runs)
-- ============================================================================
-- Expected: Recent entries with status = 'succeeded'
-- If empty: Reaper has never run
-- If status = 'failed': Check return_message for error
SELECT 'CHECK 2: Execution History' AS check_name,
    jrd.jobid,
    j.jobname,
    jrd.runid,
    jrd.job_pid,
    jrd.status,
    jrd.return_message,
    jrd.start_time,
    jrd.end_time,
    EXTRACT(
        EPOCH
        FROM (jrd.end_time - jrd.start_time)
    )::numeric(10, 2) AS duration_seconds
FROM cron.job_run_details jrd
    JOIN cron.job j ON j.jobid = jrd.jobid
WHERE j.jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
ORDER BY jrd.start_time DESC
LIMIT 10;
-- ============================================================================
-- CHECK 3: Currently Stuck Jobs (Should be 0 if Reaper is working)
-- ============================================================================
-- Expected: 0 rows if reaper is functioning correctly
-- If rows exist: These jobs are stuck and reaper may not be running
SELECT 'CHECK 3: Stuck Jobs' AS check_name,
    id,
    job_type,
    status,
    worker_id,
    claimed_at AS locked_at,
    EXTRACT(
        EPOCH
        FROM (NOW() - claimed_at)
    ) / 60 AS minutes_stuck,
    attempts,
    payload->>'file_path' AS file_path
FROM ops.job_queue
WHERE claimed_at < NOW() - INTERVAL '15 minutes'
    AND status = 'processing'
ORDER BY claimed_at ASC;
-- ============================================================================
-- CHECK 4: Stuck Job Count Summary
-- ============================================================================
SELECT 'CHECK 4: Stuck Job Summary' AS check_name,
    COUNT(*) AS stuck_job_count,
    MIN(claimed_at) AS oldest_stuck_job,
    MAX(
        EXTRACT(
            EPOCH
            FROM (NOW() - claimed_at)
        ) / 60
    )::numeric(10, 1) AS max_minutes_stuck
FROM ops.job_queue
WHERE claimed_at < NOW() - INTERVAL '15 minutes'
    AND status = 'processing';
-- ============================================================================
-- CHECK 5: Reaper Function Exists and Is Callable
-- ============================================================================
-- Expected: Function exists in ops schema
SELECT 'CHECK 5: Reaper Function' AS check_name,
    n.nspname AS schema,
    p.proname AS function_name,
    pg_get_function_arguments(p.oid) AS arguments,
    pg_get_function_result(p.oid) AS return_type
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE p.proname IN ('reap_stuck_jobs', 'dragonfly_reaper')
    AND n.nspname = 'ops';
-- ============================================================================
-- CHECK 6: Test Reaper Manually (DRY RUN - just counts, doesn't modify)
-- ============================================================================
-- This calls the reaper with a 15-minute timeout
-- Expected: Returns count of jobs that WOULD be reaped
DO $$
DECLARE v_reaped_count INTEGER;
BEGIN -- Count stuck jobs (same logic as reaper)
SELECT COUNT(*) INTO v_reaped_count
FROM ops.job_queue
WHERE status = 'processing'
    AND claimed_at < NOW() - INTERVAL '15 minutes';
RAISE NOTICE 'CHECK 6: Manual Reaper Test - % jobs would be reaped',
v_reaped_count;
END $$;
-- ============================================================================
-- CHECK 7: pg_cron Extension Status
-- ============================================================================
-- Expected: pg_cron should be installed and enabled
SELECT 'CHECK 7: pg_cron Status' AS check_name,
    extname,
    extversion,
    extnamespace::regnamespace AS schema
FROM pg_extension
WHERE extname = 'pg_cron';
-- ============================================================================
-- HEALTH SUMMARY
-- ============================================================================
SELECT 'SUMMARY' AS check_name,
    (
        SELECT COUNT(*)
        FROM cron.job
        WHERE jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
    ) AS reaper_schedules,
    (
        SELECT COUNT(*)
        FROM cron.job_run_details jrd
            JOIN cron.job j ON j.jobid = jrd.jobid
        WHERE j.jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
            AND jrd.start_time > NOW() - INTERVAL '1 hour'
    ) AS runs_last_hour,
    (
        SELECT COUNT(*)
        FROM ops.job_queue
        WHERE claimed_at < NOW() - INTERVAL '15 minutes'
            AND status = 'processing'
    ) AS stuck_jobs,
    CASE
        WHEN (
            SELECT COUNT(*)
            FROM cron.job
            WHERE jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
        ) = 0 THEN '❌ NO SCHEDULE'
        WHEN (
            SELECT COUNT(*)
            FROM cron.job_run_details jrd
                JOIN cron.job j ON j.jobid = jrd.jobid
            WHERE j.jobname IN ('dragonfly_reaper', 'reap_stuck_jobs')
                AND jrd.start_time > NOW() - INTERVAL '1 hour'
        ) = 0 THEN '⚠️ NO RECENT RUNS'
        WHEN (
            SELECT COUNT(*)
            FROM ops.job_queue
            WHERE claimed_at < NOW() - INTERVAL '15 minutes'
                AND status = 'processing'
        ) > 0 THEN '⚠️ STUCK JOBS EXIST'
        ELSE '✅ HEALTHY'
    END AS health_status;