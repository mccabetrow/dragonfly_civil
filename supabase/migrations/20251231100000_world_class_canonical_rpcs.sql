-- ============================================================================
-- Migration: 20251220180001_world_class_canonical_rpcs.sql
-- Purpose: Definitive canonical DB contract for ops schema RPCs
-- ============================================================================
-- 
-- INVARIANTS ENFORCED:
--   1. App code NEVER directly writes to ops/intake/enforcement tables - RPC ONLY
--   2. All privileged RPCs are SECURITY DEFINER with SET search_path
--   3. No DML grants to anon/authenticated/dragonfly_app - only GRANT EXECUTE
--   4. claim_pending_job has ONE canonical signature (no ambiguous refs)
--   5. All RPCs use fully qualified column references to avoid ambiguity
--
-- CANONICAL RPC SIGNATURES (matching rpc_client.py exactly):
--   ops.claim_pending_job(TEXT[], INTEGER, TEXT) -> TABLE
--   ops.update_job_status(UUID, TEXT, TEXT, INTEGER) -> BOOLEAN
--   ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) -> UUID
--   ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) -> TEXT
--   ops.reap_stuck_jobs(INTEGER) -> TABLE
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. DROP ALL CONFLICTING RPC VARIANTS (clean slate)
-- ============================================================================
-- Drop all known signatures of ops.claim_pending_job to clear the slate
DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT [], INTEGER);
DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT [], INTEGER, TEXT);
DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT [], INTEGER, UUID);
DROP FUNCTION IF EXISTS ops.claim_pending_job(UUID, TEXT []);
-- Drop conflicting public.queue_job signatures
DROP FUNCTION IF EXISTS public.queue_job(jsonb);
DROP FUNCTION IF EXISTS public.queue_job(text, jsonb);
-- Drop any old update_job_status with wrong signature
DROP FUNCTION IF EXISTS ops.update_job_status(UUID, TEXT);
DROP FUNCTION IF EXISTS ops.update_job_status(UUID, TEXT, TEXT);
-- ============================================================================
-- 2. ENSURE ops.job_queue HAS ALL REQUIRED COLUMNS
-- ============================================================================
-- These columns are expected by rpc_client.py and workers
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS max_attempts INTEGER NOT NULL DEFAULT 5;
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS next_run_at TIMESTAMPTZ;
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS started_at TIMESTAMPTZ;
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS worker_id TEXT;
ALTER TABLE ops.job_queue
ADD COLUMN IF NOT EXISTS reap_count INTEGER NOT NULL DEFAULT 0;
COMMENT ON COLUMN ops.job_queue.max_attempts IS 'Maximum retry attempts before job is moved to DLQ (failed status)';
COMMENT ON COLUMN ops.job_queue.next_run_at IS 'Backoff scheduling - job won''t be picked up before this time';
COMMENT ON COLUMN ops.job_queue.started_at IS 'When job processing started (for timeout detection)';
COMMENT ON COLUMN ops.job_queue.worker_id IS 'ID of the worker currently processing this job';
COMMENT ON COLUMN ops.job_queue.reap_count IS 'Number of times this job was reaped due to timeout';
-- Indexes for efficient job claiming and stuck detection
CREATE INDEX IF NOT EXISTS idx_job_queue_stuck_detection ON ops.job_queue (status, started_at)
WHERE status = 'processing';
CREATE INDEX IF NOT EXISTS idx_job_queue_scheduled ON ops.job_queue (status, next_run_at, created_at)
WHERE status = 'pending';
-- ============================================================================
-- 3. CANONICAL ops.claim_pending_job
-- ============================================================================
-- Signature: (TEXT[], INTEGER DEFAULT 30, TEXT DEFAULT NULL) -> TABLE
-- Matches rpc_client.py:
--   rpc.claim_pending_job(job_types=list, lock_timeout_minutes=int, worker_id=str|None)
--
-- CRITICAL: Uses fully qualified column references (jq.column, inner_jq.column)
--           to eliminate ambiguity errors.
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
            AND inner_jq.status::text = 'pending' -- Respect backoff scheduling (next_run_at)
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
COMMENT ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) IS 'Canonical job claim RPC. Args: p_job_types (array of job types), p_lock_timeout_minutes (default 30), p_worker_id (optional). Uses FOR UPDATE SKIP LOCKED for safe concurrent access. SECURITY DEFINER.';
-- Grants: Only privileged roles can claim jobs
REVOKE ALL ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) TO postgres;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) TO dragonfly_worker;
END IF;
IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER, TEXT) TO dragonfly_app;
END IF;
END $$;
-- ============================================================================
-- 4. CANONICAL ops.update_job_status
-- ============================================================================
-- Signature: (UUID, TEXT, TEXT DEFAULT NULL, INTEGER DEFAULT NULL) -> BOOLEAN
-- Matches rpc_client.py:
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
UPDATE ops.job_queue jq
SET status = p_status::ops.job_status_enum,
    last_error = COALESCE(LEFT(p_error_message, 2000), jq.last_error),
    next_run_at = v_next_run_at,
    updated_at = now(),
    -- Clear processing fields on terminal states
    locked_at = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE jq.locked_at
    END,
    started_at = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE jq.started_at
    END,
    worker_id = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE jq.worker_id
    END
WHERE jq.id = p_job_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) IS 'Update job status with optional backoff scheduling. Clears processing fields on terminal states. SECURITY DEFINER.';
-- Grants
REVOKE ALL ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) TO postgres;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) TO dragonfly_worker;
END IF;
IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT, INTEGER) TO dragonfly_app;
END IF;
END $$;
-- ============================================================================
-- 5. CANONICAL ops.queue_job
-- ============================================================================
-- Signature: (TEXT, JSONB, INTEGER DEFAULT 0, TIMESTAMPTZ DEFAULT now()) -> UUID
-- Matches rpc_client.py:
--   rpc.queue_job(job_type, payload, priority, run_at)
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
WHEN invalid_text_representation THEN RAISE EXCEPTION 'Invalid job type: %. Valid types: SELECT enumlabel FROM pg_enum WHERE enumtypid = ''ops.job_type_enum''::regtype',
p_type;
END;
$$;
COMMENT ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) IS 'Canonical job enqueue RPC. Validates job_type against enum. SECURITY DEFINER.';
-- Grants
REVOKE ALL ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO service_role;
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO postgres;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO dragonfly_worker;
END IF;
IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO dragonfly_app;
END IF;
END $$;
-- ============================================================================
-- 6. CANONICAL ops.register_heartbeat
-- ============================================================================
-- Signature: (TEXT, TEXT, TEXT DEFAULT NULL, TEXT DEFAULT 'running') -> TEXT
-- Matches rpc_client.py:
--   rpc.register_heartbeat(worker_id, worker_type, hostname, status)
CREATE OR REPLACE FUNCTION ops.register_heartbeat(
        p_worker_id TEXT,
        p_worker_type TEXT,
        p_hostname TEXT DEFAULT NULL,
        p_status TEXT DEFAULT 'running'
    ) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN
INSERT INTO ops.worker_heartbeats (
        worker_id,
        worker_type,
        hostname,
        status,
        last_seen_at
    )
VALUES (
        p_worker_id,
        p_worker_type,
        p_hostname,
        p_status,
        now()
    ) ON CONFLICT (worker_id) DO
UPDATE
SET status = EXCLUDED.status,
    hostname = COALESCE(
        EXCLUDED.hostname,
        ops.worker_heartbeats.hostname
    ),
    last_seen_at = now(),
    updated_at = now();
RETURN p_worker_id;
END;
$$;
COMMENT ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) IS 'Register or update worker heartbeat. SECURITY DEFINER.';
-- Grants
REVOKE ALL ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) TO service_role;
GRANT EXECUTE ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) TO postgres;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN
GRANT EXECUTE ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) TO dragonfly_worker;
END IF;
IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT EXECUTE ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) TO dragonfly_app;
END IF;
END $$;
-- ============================================================================
-- 7. CANONICAL ops.reap_stuck_jobs
-- ============================================================================
-- Signature: (INTEGER DEFAULT 30) -> TABLE
-- For scheduled job recovery
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
BEGIN FOR v_stuck_job IN
SELECT jq.id,
    jq.job_type::text AS job_type_text,
    jq.attempts,
    COALESCE(jq.max_attempts, v_max_attempts) AS job_max_attempts,
    jq.worker_id AS stuck_worker_id,
    jq.started_at AS stuck_started_at
FROM ops.job_queue jq
WHERE jq.status = 'processing'
    AND jq.started_at IS NOT NULL
    AND jq.started_at < now() - (p_lock_timeout_minutes || ' minutes')::interval FOR
UPDATE SKIP LOCKED LOOP IF v_stuck_job.attempts >= v_stuck_job.job_max_attempts THEN -- DLQ: Exceeded max attempts
UPDATE ops.job_queue jq
SET status = 'failed',
    last_error = format(
        '[DLQ] Reaped: Timeout exceeded after %s attempts. Last worker: %s. Started: %s',
        v_stuck_job.attempts,
        COALESCE(v_stuck_job.stuck_worker_id, 'unknown'),
        v_stuck_job.stuck_started_at
    ),
    reap_count = COALESCE(jq.reap_count, 0) + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE jq.id = v_stuck_job.id;
v_action := 'moved_to_dlq';
ELSE -- Retry: Reset to pending with exponential backoff
v_backoff_seconds := LEAST(
    POWER(2, v_stuck_job.attempts)::integer * 30,
    3600
);
UPDATE ops.job_queue jq
SET status = 'pending',
    last_error = format(
        'Reaped: Timeout after %s minutes. Attempt %s/%s. Backoff: %ss',
        p_lock_timeout_minutes,
        v_stuck_job.attempts,
        v_stuck_job.job_max_attempts,
        v_backoff_seconds
    ),
    next_run_at = now() + (v_backoff_seconds || ' seconds')::interval,
    reap_count = COALESCE(jq.reap_count, 0) + 1,
    locked_at = NULL,
    started_at = NULL,
    worker_id = NULL
WHERE jq.id = v_stuck_job.id;
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
COMMENT ON FUNCTION ops.reap_stuck_jobs(INTEGER) IS 'Reaper for stuck jobs. Resets with backoff or moves to DLQ after max_attempts. SECURITY DEFINER.';
-- Grants (service_role/postgres only for reaper - not for general app use)
REVOKE ALL ON FUNCTION ops.reap_stuck_jobs(INTEGER)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTEGER) TO postgres;
-- ============================================================================
-- 8. REVOKE RAW DML ON ops TABLES
-- ============================================================================
-- Ensure no raw INSERT/UPDATE/DELETE for anon/authenticated/dragonfly_app
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.job_queue
FROM anon;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.job_queue
FROM authenticated;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats
FROM anon;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats
FROM authenticated;
-- dragonfly_app only gets SELECT + RPC EXECUTE (no raw DML)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.job_queue
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats
FROM dragonfly_app;
GRANT SELECT ON ops.job_queue TO dragonfly_app;
GRANT SELECT ON ops.worker_heartbeats TO dragonfly_app;
END IF;
END $$;
-- ============================================================================
-- 9. NOTIFY POSTGREST TO RELOAD SCHEMA
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- ROLLBACK PLAN (run manually if needed)
-- ============================================================================
-- To rollback this migration, run:
--
-- BEGIN;
-- -- Restore original claim_pending_job (2-arg version)
-- DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT[], INTEGER, TEXT);
-- CREATE OR REPLACE FUNCTION ops.claim_pending_job(
--     p_job_types TEXT[],
--     p_lock_timeout_minutes INTEGER DEFAULT 30
-- ) RETURNS TABLE (...) LANGUAGE plpgsql SECURITY DEFINER SET search_path = ops AS $$...$$;
-- 
-- -- Restore original update_job_status (3-arg version)  
-- DROP FUNCTION IF EXISTS ops.update_job_status(UUID, TEXT, TEXT, INTEGER);
-- CREATE OR REPLACE FUNCTION ops.update_job_status(
--     p_job_id UUID,
--     p_status TEXT,
--     p_error TEXT DEFAULT NULL
-- ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER SET search_path = ops AS $$...$$;
--
-- NOTIFY pgrst, 'reload schema';
-- COMMIT;
