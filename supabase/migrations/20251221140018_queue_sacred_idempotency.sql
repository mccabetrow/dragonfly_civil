-- ============================================================================
-- Migration: 20251221140018_queue_sacred_idempotency.sql
-- Sacred Queue Hardening: Idempotency Key + Unique Constraint
-- ============================================================================
-- PURPOSE:
--   1. Add idempotency_key column for duplicate job prevention
--   2. Backfill existing NULL keys with job_id::text
--   3. Create unique index on (job_type, idempotency_key)
--   4. Update queue_job RPC to accept and enforce idempotency_key
-- ============================================================================
-- SAFETY:
--   - All operations are idempotent (IF NOT EXISTS / IF EXISTS checks)
--   - Existing jobs get idempotency_key backfilled from their UUID
--   - The unique constraint prevents duplicate job submissions
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. Add idempotency_key column (idempotent)
-- ============================================================================
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS idempotency_key TEXT;
COMMENT ON COLUMN ops.job_queue.idempotency_key IS 'Unique key within job_type to prevent duplicate submissions. Format: <source>:<external_id>';
-- ============================================================================
-- 2. Backfill NULL idempotency_keys with job_id::text
-- ============================================================================
-- This ensures all existing jobs have a key before we apply the constraint
UPDATE ops.job_queue
SET idempotency_key = id::text
WHERE idempotency_key IS NULL;
-- ============================================================================
-- 3. Create unique index on (job_type, idempotency_key)
-- ============================================================================
-- This enforces: within a job_type, each idempotency_key is unique
-- Using a partial index that only applies when idempotency_key IS NOT NULL
-- allows optional idempotency (though we've backfilled all existing)
CREATE UNIQUE INDEX IF NOT EXISTS idx_job_queue_idempotency ON ops.job_queue (job_type, idempotency_key)
WHERE idempotency_key IS NOT NULL;
COMMENT ON INDEX ops.idx_job_queue_idempotency IS 'Enforces unique (job_type, idempotency_key) to prevent duplicate job submissions';
-- ============================================================================
-- 4. Create ops.queue_job_idempotent - Queue with duplicate prevention
-- ============================================================================
-- This function returns the existing job_id if a duplicate is submitted,
-- or creates a new job if the idempotency_key is new.
CREATE OR REPLACE FUNCTION ops.queue_job_idempotent(
        p_type TEXT,
        p_payload JSONB,
        p_idempotency_key TEXT,
        p_priority INTEGER DEFAULT 0,
        p_run_at TIMESTAMPTZ DEFAULT NULL
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_existing_id UUID;
v_new_id UUID;
BEGIN -- Check for existing job with same type + idempotency_key
SELECT id INTO v_existing_id
FROM ops.job_queue
WHERE job_type = p_type::ops.job_type_enum
    AND idempotency_key = p_idempotency_key
LIMIT 1;
IF v_existing_id IS NOT NULL THEN -- Return existing job ID (idempotent behavior)
RETURN v_existing_id;
END IF;
-- Insert new job
INSERT INTO ops.job_queue (
        job_type,
        payload,
        idempotency_key,
        priority,
        next_run_at,
        status
    )
VALUES (
        p_type::ops.job_type_enum,
        p_payload,
        p_idempotency_key,
        COALESCE(p_priority, 0),
        COALESCE(p_run_at, NOW()),
        'pending'
    )
RETURNING id INTO v_new_id;
RETURN v_new_id;
END;
$$;
COMMENT ON FUNCTION ops.queue_job_idempotent(TEXT, JSONB, TEXT, INTEGER, TIMESTAMPTZ) IS 'Idempotent job queueing: returns existing job_id if duplicate, else creates new job. SECURITY DEFINER.';
-- Security grants
REVOKE ALL ON FUNCTION ops.queue_job_idempotent(TEXT, JSONB, TEXT, INTEGER, TIMESTAMPTZ)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.queue_job_idempotent(TEXT, JSONB, TEXT, INTEGER, TIMESTAMPTZ) TO service_role;
GRANT EXECUTE ON FUNCTION ops.queue_job_idempotent(TEXT, JSONB, TEXT, INTEGER, TIMESTAMPTZ) TO postgres;
-- ============================================================================
-- 5. Enhanced ops.reap_stuck_jobs - Deterministic Reaper v2
-- ============================================================================
-- Improvements:
--   - Logs recovery action to last_error with full context
--   - Exponential backoff: 2^attempts * 30s (capped at 1 hour)
--   - Clear action_taken enum: 'recovered', 'dlq'
CREATE OR REPLACE FUNCTION ops.reap_stuck_jobs(
        p_lock_timeout_minutes INTEGER DEFAULT 30
    ) RETURNS TABLE (
        job_id UUID,
        job_type TEXT,
        action_taken TEXT,
        attempts INTEGER,
        max_attempts INTEGER
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_stuck_job RECORD;
v_action TEXT;
v_backoff_seconds INTEGER;
v_default_max_attempts INTEGER := 3;
-- Sacred default: 3 attempts
BEGIN FOR v_stuck_job IN
SELECT jq.id,
    jq.job_type::text AS job_type_text,
    jq.attempts,
    COALESCE(jq.max_attempts, v_default_max_attempts) AS job_max_attempts,
    jq.worker_id AS stuck_worker_id,
    jq.started_at AS stuck_started_at,
    jq.idempotency_key AS stuck_idem_key
FROM ops.job_queue jq
WHERE jq.status = 'processing'
    AND jq.started_at IS NOT NULL
    AND jq.started_at < NOW() - (p_lock_timeout_minutes || ' minutes')::interval FOR
UPDATE SKIP LOCKED LOOP IF v_stuck_job.attempts >= v_stuck_job.job_max_attempts THEN -- ============================================================
    -- CASE B: EXHAUSTED - Move to DLQ (failed status)
    -- ============================================================
UPDATE ops.job_queue jq
SET status = 'failed',
    last_error = format(
        '[DLQ] Reaped: Max attempts (%s/%s) exceeded. Worker: %s. Key: %s. Started: %s',
        v_stuck_job.attempts,
        v_stuck_job.job_max_attempts,
        COALESCE(v_stuck_job.stuck_worker_id, 'unknown'),
        COALESCE(v_stuck_job.stuck_idem_key, 'none'),
        v_stuck_job.stuck_started_at
    ),
    reap_count = COALESCE(jq.reap_count, 0) + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE jq.id = v_stuck_job.id;
v_action := 'dlq';
ELSE -- ============================================================
-- CASE A: RETRYABLE - Reset to pending with exponential backoff
-- ============================================================
-- Backoff: 2^attempts * 30s = 30s, 60s, 120s, 240s... (capped at 3600s)
v_backoff_seconds := LEAST(
    POWER(2, v_stuck_job.attempts)::integer * 30,
    3600
);
UPDATE ops.job_queue jq
SET status = 'pending',
    last_error = format(
        '[RECOVERED] Job recovered by Reaper. Attempt %s/%s. Backoff: %ss. Worker: %s',
        v_stuck_job.attempts,
        v_stuck_job.job_max_attempts,
        v_backoff_seconds,
        COALESCE(v_stuck_job.stuck_worker_id, 'unknown')
    ),
    next_run_at = NOW() + (v_backoff_seconds || ' seconds')::interval,
    reap_count = COALESCE(jq.reap_count, 0) + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE jq.id = v_stuck_job.id;
v_action := 'recovered';
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
COMMENT ON FUNCTION ops.reap_stuck_jobs(INTEGER) IS 'Sacred Reaper: Recovers stuck jobs (attempts < max_attempts with backoff) or moves to DLQ. SECURITY DEFINER.';
-- Security grants
REVOKE ALL ON FUNCTION ops.reap_stuck_jobs(INTEGER)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTEGER) TO postgres;
-- ============================================================================
-- 6. Verify schema state
-- ============================================================================
DO $$
DECLARE v_col_exists BOOLEAN;
v_idx_exists BOOLEAN;
BEGIN -- Check idempotency_key column
SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'ops'
            AND table_name = 'job_queue'
            AND column_name = 'idempotency_key'
    ) INTO v_col_exists;
IF NOT v_col_exists THEN RAISE EXCEPTION 'MIGRATION FAILED: idempotency_key column not created';
END IF;
-- Check unique index
SELECT EXISTS (
        SELECT 1
        FROM pg_indexes
        WHERE schemaname = 'ops'
            AND tablename = 'job_queue'
            AND indexname = 'idx_job_queue_idempotency'
    ) INTO v_idx_exists;
IF NOT v_idx_exists THEN RAISE EXCEPTION 'MIGRATION FAILED: idempotency unique index not created';
END IF;
RAISE NOTICE '[OK] Sacred Queue Hardening complete: idempotency_key + unique index verified';
END $$;
COMMIT;
-- Notify PostgREST to reload schema
NOTIFY pgrst,
'reload schema';
