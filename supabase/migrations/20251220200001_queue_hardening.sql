-- ============================================================================
-- Migration: 20251220200000_queue_hardening.sql
-- Dragonfly Queue Hardening: Stuck Job Reaper, DLQ Support, Observability
-- ============================================================================
-- PURPOSE:
--   1. Add max_attempts column and next_run_at for backoff scheduling
--   2. Create ops.reap_stuck_jobs() for automatic stuck job recovery
--   3. Create ops.queue_health view for dashboard observability
--   4. Add indexes for efficient reaping and health queries
-- ============================================================================
-- ============================================================================
-- 1. Add queue hardening columns (idempotent)
-- ============================================================================
-- max_attempts: Jobs exceeding this are moved to DLQ (failed status)
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS max_attempts integer NOT NULL DEFAULT 5;
-- next_run_at: Backoff scheduling - job won't be picked up until this time
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS next_run_at timestamptz;
-- started_at: When job processing actually began (for timeout tracking)
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS started_at timestamptz;
-- worker_id: Which worker is processing this job
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS worker_id text;
-- reap_count: How many times this job has been reaped (diagnostic)
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS reap_count integer NOT NULL DEFAULT 0;
COMMENT ON COLUMN ops.job_queue.max_attempts IS 'Maximum retry attempts before job is moved to DLQ (failed status)';
COMMENT ON COLUMN ops.job_queue.next_run_at IS 'Backoff scheduling - job won''t be picked up before this time';
COMMENT ON COLUMN ops.job_queue.started_at IS 'When job processing started (for timeout detection)';
COMMENT ON COLUMN ops.job_queue.worker_id IS 'ID of the worker currently processing this job';
COMMENT ON COLUMN ops.job_queue.reap_count IS 'Number of times this job was reaped due to timeout';
-- ============================================================================
-- 2. Add indexes for efficient reaping and scheduling
-- ============================================================================
-- Index for finding stuck jobs (processing + started_at timeout)
CREATE INDEX IF NOT EXISTS idx_job_queue_stuck_detection ON ops.job_queue (status, started_at)
WHERE status = 'processing';
-- Index for backoff scheduling (pending + next_run_at)
CREATE INDEX IF NOT EXISTS idx_job_queue_scheduled ON ops.job_queue (status, next_run_at, created_at)
WHERE status = 'pending';
-- ============================================================================
-- 3. Update claim_pending_job to respect next_run_at and set started_at
-- ============================================================================
-- Drop old 2-param signature if it exists (we're upgrading to 3-param)
DROP FUNCTION IF EXISTS ops.claim_pending_job(text [], integer);
CREATE OR REPLACE FUNCTION ops.claim_pending_job(
        p_job_types text [],
        p_lock_timeout_minutes integer DEFAULT 30,
        p_worker_id text DEFAULT NULL
    ) RETURNS TABLE (
        job_id uuid,
        job_type text,
        payload jsonb,
        attempts integer,
        created_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$ BEGIN RETURN QUERY
UPDATE ops.job_queue jq
SET status = 'processing',
    locked_at = now(),
    started_at = now(),
    worker_id = p_worker_id,
    attempts = jq.attempts + 1
WHERE jq.id = (
        SELECT inner_jq.id
        FROM ops.job_queue inner_jq
        WHERE inner_jq.job_type::text = ANY(p_job_types)
            AND inner_jq.status::text = 'pending' -- Respect backoff scheduling
            AND (
                inner_jq.next_run_at IS NULL
                OR inner_jq.next_run_at <= now()
            ) -- Handle stale locks
            AND (
                inner_jq.locked_at IS NULL
                OR inner_jq.locked_at < now() - (p_lock_timeout_minutes || ' minutes')::interval
            )
        ORDER BY -- Priority: older jobs first, but respect scheduling
            COALESCE(inner_jq.next_run_at, inner_jq.created_at) ASC
        LIMIT 1 FOR
        UPDATE SKIP LOCKED
    )
RETURNING jq.id,
    jq.job_type::text,
    jq.payload,
    jq.attempts,
    jq.created_at;
END;
$$;
COMMENT ON FUNCTION ops.claim_pending_job(text [], integer, text) IS 'Securely claim a pending job from the queue. Respects backoff scheduling (next_run_at) and uses FOR UPDATE SKIP LOCKED.';
-- ============================================================================
-- 4. Create ops.reap_stuck_jobs() - The Stuck Job Reaper
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.reap_stuck_jobs(
        p_lock_timeout_minutes integer DEFAULT 30
    ) RETURNS TABLE (
        job_id uuid,
        job_type text,
        action_taken text,
        attempts integer,
        max_attempts integer
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_stuck_job RECORD;
v_action text;
v_backoff_seconds integer;
BEGIN -- Find and process all stuck jobs
FOR v_stuck_job IN
SELECT jq.id,
    jq.job_type::text as job_type_text,
    jq.attempts,
    jq.max_attempts as job_max_attempts,
    jq.worker_id,
    jq.started_at
FROM ops.job_queue jq
WHERE jq.status = 'processing'
    AND jq.started_at IS NOT NULL
    AND jq.started_at < now() - (p_lock_timeout_minutes || ' minutes')::interval FOR
UPDATE SKIP LOCKED LOOP IF v_stuck_job.attempts >= v_stuck_job.job_max_attempts THEN -- DLQ: Exceeded max attempts, move to failed
UPDATE ops.job_queue
SET status = 'failed',
    last_error = format(
        '[DLQ] Reaped: Timeout exceeded after %s attempts. Last worker: %s. Started: %s',
        v_stuck_job.attempts,
        COALESCE(v_stuck_job.worker_id, 'unknown'),
        v_stuck_job.started_at
    ),
    reap_count = reap_count + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE id = v_stuck_job.id;
v_action := 'moved_to_dlq';
ELSE -- Retry: Reset to pending with exponential backoff
-- Backoff formula: 2^attempts * 30 seconds (capped at 1 hour)
v_backoff_seconds := LEAST(POWER(2, v_stuck_job.attempts) * 30, 3600);
UPDATE ops.job_queue
SET status = 'pending',
    last_error = format(
        'Reaped: Timeout after %s minutes. Attempt %s/%s. Backoff: %ss. Worker: %s',
        p_lock_timeout_minutes,
        v_stuck_job.attempts,
        v_stuck_job.job_max_attempts,
        v_backoff_seconds,
        COALESCE(v_stuck_job.worker_id, 'unknown')
    ),
    next_run_at = now() + (v_backoff_seconds || ' seconds')::interval,
    reap_count = reap_count + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE id = v_stuck_job.id;
v_action := 'reset_with_backoff';
END IF;
-- Return the action taken
job_id := v_stuck_job.id;
job_type := v_stuck_job.job_type_text;
action_taken := v_action;
attempts := v_stuck_job.attempts;
max_attempts := v_stuck_job.job_max_attempts;
RETURN NEXT;
END LOOP;
END;
$$;
COMMENT ON FUNCTION ops.reap_stuck_jobs(integer) IS 'Reaper for stuck jobs: Resets jobs exceeding lock timeout. If attempts < max, resets to pending with backoff. If attempts >= max, moves to DLQ (failed).';
-- Security: Only service_role and postgres can run the reaper
REVOKE ALL ON FUNCTION ops.reap_stuck_jobs(integer)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(integer) TO service_role;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(integer) TO postgres;
-- ============================================================================
-- 5. Create ops.update_job_status with backoff support
-- ============================================================================
-- Drop old 3-param signature if it exists (upgrading to 4-param with backoff)
DROP FUNCTION IF EXISTS ops.update_job_status(uuid, text, text);
CREATE OR REPLACE FUNCTION ops.update_job_status(
        p_job_id uuid,
        p_status text,
        p_error_message text DEFAULT NULL,
        p_backoff_seconds integer DEFAULT NULL
    ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_next_run_at timestamptz := NULL;
BEGIN -- Calculate next_run_at if backoff is specified
IF p_backoff_seconds IS NOT NULL
AND p_backoff_seconds > 0 THEN v_next_run_at := now() + (p_backoff_seconds || ' seconds')::interval;
END IF;
UPDATE ops.job_queue
SET status = p_status::ops.job_status_enum,
    last_error = COALESCE(p_error_message, last_error),
    next_run_at = v_next_run_at,
    -- Clear processing fields on completion/failure
    locked_at = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE locked_at
    END,
    started_at = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE started_at
    END,
    worker_id = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE worker_id
    END
WHERE id = p_job_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION ops.update_job_status(uuid, text, text, integer) IS 'Update job status with optional backoff scheduling. Clears processing fields on completion/failure.';
-- Grants for update_job_status
GRANT EXECUTE ON FUNCTION ops.update_job_status(uuid, text, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION ops.update_job_status(uuid, text, text, integer) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.update_job_status(uuid, text, text, integer) TO dragonfly_app;
-- ============================================================================
-- 6. Create Queue Health View for Dashboard
-- ============================================================================
CREATE OR REPLACE VIEW ops.v_queue_health AS
SELECT jq.job_type::text AS job_type,
    -- Counts by status
    COUNT(*) FILTER (
        WHERE jq.status = 'pending'
    ) AS pending_count,
    COUNT(*) FILTER (
        WHERE jq.status = 'processing'
    ) AS processing_count,
    COUNT(*) FILTER (
        WHERE jq.status = 'completed'
    ) AS completed_count,
    COUNT(*) FILTER (
        WHERE jq.status = 'failed'
    ) AS failed_count,
    -- Age metrics (critical for alerting)
    EXTRACT(
        EPOCH
        FROM (
                now() - MIN(jq.created_at) FILTER (
                    WHERE jq.status = 'pending'
                )
            )
    ) / 60.0 AS oldest_pending_minutes,
    -- Stuck job detection (processing > 1 hour)
    COUNT(*) FILTER (
        WHERE jq.status = 'processing'
            AND jq.started_at < now() - interval '1 hour'
    ) AS stuck_jobs_count,
    -- Scheduled jobs (pending with future next_run_at)
    COUNT(*) FILTER (
        WHERE jq.status = 'pending'
            AND jq.next_run_at IS NOT NULL
            AND jq.next_run_at > now()
    ) AS scheduled_count,
    -- Jobs in backoff (recently reaped or failed, retrying)
    COUNT(*) FILTER (
        WHERE jq.reap_count > 0
    ) AS reaped_total,
    -- Throughput (last hour)
    COUNT(*) FILTER (
        WHERE jq.status = 'completed'
            AND jq.updated_at > now() - interval '1 hour'
    ) AS completed_last_hour,
    COUNT(*) FILTER (
        WHERE jq.status = 'failed'
            AND jq.updated_at > now() - interval '1 hour'
    ) AS failed_last_hour
FROM ops.job_queue jq
GROUP BY jq.job_type;
COMMENT ON VIEW ops.v_queue_health IS 'Queue health dashboard: Shows pending/processing/failed counts, oldest pending age, stuck jobs, and throughput per job type.';
GRANT SELECT ON ops.v_queue_health TO service_role;
GRANT SELECT ON ops.v_queue_health TO dragonfly_app;
-- ============================================================================
-- 7. Create Queue Health Summary Function (single row)
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.get_queue_health_summary() RETURNS TABLE (
        total_pending integer,
        total_processing integer,
        total_failed integer,
        oldest_pending_minutes numeric,
        stuck_jobs_count integer,
        dlq_size integer,
        health_status text
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_oldest_pending numeric;
v_stuck integer;
v_status text;
BEGIN
SELECT COUNT(*) FILTER (
        WHERE status = 'pending'
    )::integer,
    COUNT(*) FILTER (
        WHERE status = 'processing'
    )::integer,
    COUNT(*) FILTER (
        WHERE status = 'failed'
    )::integer,
    EXTRACT(
        EPOCH
        FROM (
                now() - MIN(created_at) FILTER (
                    WHERE status = 'pending'
                )
            )
    ) / 60.0,
    COUNT(*) FILTER (
        WHERE status = 'processing'
            AND started_at < now() - interval '1 hour'
    )::integer,
    COUNT(*) FILTER (
        WHERE status = 'failed'
            AND last_error LIKE '[DLQ]%'
    )::integer INTO total_pending,
    total_processing,
    total_failed,
    v_oldest_pending,
    v_stuck,
    dlq_size
FROM ops.job_queue;
oldest_pending_minutes := COALESCE(v_oldest_pending, 0);
stuck_jobs_count := v_stuck;
-- Determine health status
IF v_stuck > 0 THEN v_status := 'critical';
ELSIF oldest_pending_minutes > 60 THEN v_status := 'warning';
ELSIF total_failed > 100 THEN v_status := 'degraded';
ELSE v_status := 'healthy';
END IF;
health_status := v_status;
RETURN NEXT;
END;
$$;
COMMENT ON FUNCTION ops.get_queue_health_summary() IS 'Returns a single-row summary of queue health with status classification (healthy/warning/critical).';
GRANT EXECUTE ON FUNCTION ops.get_queue_health_summary() TO service_role;
GRANT EXECUTE ON FUNCTION ops.get_queue_health_summary() TO dragonfly_app;
-- ============================================================================
-- 8. Ensure proper grants on claim_pending_job (updated signature)
-- ============================================================================
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(text [], integer, text) TO service_role;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(text [], integer, text) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(text [], integer, text) TO dragonfly_app;
-- ============================================================================
-- 9. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';