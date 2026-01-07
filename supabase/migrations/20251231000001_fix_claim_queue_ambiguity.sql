-- ============================================================================
-- Migration: 20251231000000_fix_claim_queue_ambiguity.sql
-- Purpose: Reconcile RPC signatures for ops.claim_pending_job and ops.queue_job
-- ============================================================================
-- PROBLEM:
--   1. ops.claim_pending_job has multiple overloaded versions with different
--      signatures, causing "function is not unique" errors:
--      - (TEXT[], INTEGER) from 20251230 world_class_security
--      - (TEXT[], INTEGER, TEXT) from 20251220 queue_hardening
--   2. Python code (rpc_client.py) calls with p_worker_id parameter
--   3. We need ONE canonical signature that matches all Python usage
--
-- SOLUTION:
--   1. DROP all existing variants
--   2. CREATE single canonical version matching Python code exactly
-- ============================================================================
-- ============================================================================
-- 1. DROP ALL EXISTING claim_pending_job VARIANTS
-- ============================================================================
-- Drop all known signatures to clear the slate
DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT [], INTEGER);
DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT [], INTEGER, TEXT);
DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT [], INTEGER, UUID);
DROP FUNCTION IF EXISTS ops.claim_pending_job(UUID, TEXT []);
-- ============================================================================
-- 2. CREATE CANONICAL ops.claim_pending_job
-- ============================================================================
-- Signature matches Python rpc_client.py exactly:
--   rpc.claim_pending_job(job_types=list, lock_timeout_minutes=int, worker_id=str)
--
-- Features:
--   - Respects next_run_at for backoff scheduling
--   - Sets started_at for timeout tracking
--   - Records worker_id for observability
--   - Uses FOR UPDATE SKIP LOCKED for safe concurrency
--   - SECURITY DEFINER for RPC access
CREATE OR REPLACE FUNCTION ops.claim_pending_job(
        p_job_types TEXT [],
        p_lock_timeout_minutes INTEGER DEFAULT 30,
        p_worker_id TEXT DEFAULT NULL
    ) RETURNS TABLE (
        job_id UUID,
        job_type TEXT,
        payload JSONB,
        attempts INTEGER,
        created_at TIMESTAMPTZ
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
        ORDER BY COALESCE(inner_jq.next_run_at, inner_jq.created_at) ASC
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
COMMENT ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) IS 'Canonical job claim RPC. Respects backoff scheduling, sets worker_id. SECURITY DEFINER.';
-- Grants
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) TO dragonfly_app;
-- ============================================================================
-- 3. ENSURE ops.queue_job HAS CANONICAL SIGNATURE
-- ============================================================================
-- Python code calls:
--   ops.queue_job(p_type, p_payload::jsonb, p_priority, p_run_at::timestamptz)
--
-- This matches 20251219180000_least_privilege_security_model.sql, so we
-- just ensure grants are correct.
-- Drop any conflicting signatures (public schema had old versions)
DROP FUNCTION IF EXISTS public.queue_job(jsonb);
DROP FUNCTION IF EXISTS public.queue_job(text, jsonb);
-- Ensure the canonical ops.queue_job exists and has correct grants
CREATE OR REPLACE FUNCTION ops.queue_job(
        p_type TEXT,
        p_payload JSONB,
        p_priority INTEGER DEFAULT 0,
        p_run_at TIMESTAMPTZ DEFAULT now()
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$
DECLARE v_job_id UUID;
BEGIN
INSERT INTO ops.job_queue (
        job_type,
        payload,
        priority,
        status,
        run_at,
        created_at
    )
VALUES (
        p_type::ops.job_type_enum,
        p_payload,
        p_priority,
        'pending',
        COALESCE(p_run_at, now()),
        now()
    )
RETURNING id INTO v_job_id;
RETURN v_job_id;
EXCEPTION
WHEN invalid_text_representation THEN RAISE EXCEPTION 'Invalid job type: %',
p_type;
END;
$$;
COMMENT ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) IS 'Canonical job enqueue RPC. Validates job_type against enum. SECURITY DEFINER.';
-- Grants
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO service_role;
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO dragonfly_app;
-- ============================================================================
-- 4. ENSURE ops.update_job_status HAS BACKOFF SUPPORT
-- ============================================================================
-- Python code calls:
--   rpc.update_job_status(job_id, status, error_message, backoff_seconds)
CREATE OR REPLACE FUNCTION ops.update_job_status(
        p_job_id UUID,
        p_status TEXT,
        p_error_message TEXT DEFAULT NULL,
        p_backoff_seconds INTEGER DEFAULT NULL
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_next_run_at TIMESTAMPTZ := NULL;
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
COMMENT ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) IS 'Update job status with optional backoff scheduling. Clears processing fields on terminal states.';
-- Grants
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) TO dragonfly_app;
-- ============================================================================
-- 5. ENSURE ops.reap_stuck_jobs EXISTS (for stuck job recovery)
-- ============================================================================
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
v_max_attempts INTEGER := 5;
-- Default max attempts
BEGIN FOR v_stuck_job IN
SELECT jq.id,
    jq.job_type::text AS job_type_text,
    jq.attempts,
    COALESCE(jq.max_attempts, v_max_attempts) AS job_max_attempts,
    jq.worker_id,
    jq.started_at
FROM ops.job_queue jq
WHERE jq.status = 'processing'
    AND jq.started_at IS NOT NULL
    AND jq.started_at < now() - (p_lock_timeout_minutes || ' minutes')::interval FOR
UPDATE SKIP LOCKED LOOP IF v_stuck_job.attempts >= v_stuck_job.job_max_attempts THEN -- DLQ: Exceeded max attempts
UPDATE ops.job_queue
SET status = 'failed',
    last_error = format(
        '[DLQ] Reaped: Timeout exceeded after %s attempts. Last worker: %s. Started: %s',
        v_stuck_job.attempts,
        COALESCE(v_stuck_job.worker_id, 'unknown'),
        v_stuck_job.started_at
    ),
    reap_count = COALESCE(reap_count, 0) + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE id = v_stuck_job.id;
v_action := 'moved_to_dlq';
ELSE -- Retry: Reset to pending with exponential backoff
v_backoff_seconds := LEAST(POWER(2, v_stuck_job.attempts) * 30, 3600);
UPDATE ops.job_queue
SET status = 'pending',
    last_error = format(
        'Reaped: Timeout after %s minutes. Attempt %s/%s. Backoff: %ss',
        p_lock_timeout_minutes,
        v_stuck_job.attempts,
        v_stuck_job.job_max_attempts,
        v_backoff_seconds
    ),
    next_run_at = now() + (v_backoff_seconds || ' seconds')::interval,
    reap_count = COALESCE(reap_count, 0) + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE id = v_stuck_job.id;
v_action := 'reset_with_backoff';
END IF;
job_id := v_stuck_job.id;
job_type := v_stuck_job.job_type_text;
action_taken := v_action;
attempts := v_stuck_job.attempts;
max_attempts := v_stuck_job.job_max_attempts;
RETURN NEXT;
END LOOP;
END;
$$;
COMMENT ON FUNCTION ops.reap_stuck_jobs(INTEGER) IS 'Reaper for stuck jobs. Resets with backoff or moves to DLQ. SECURITY DEFINER.';
-- Grants (service_role only for reaper)
REVOKE ALL ON FUNCTION ops.reap_stuck_jobs(INTEGER)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTEGER) TO postgres;
-- ============================================================================
-- 6. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';
