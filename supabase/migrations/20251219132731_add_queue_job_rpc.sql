-- Migration: Add ops.queue_job RPC with priority and run_at support
-- Purpose: SECURITY DEFINER function for inserting jobs into ops.job_queue
-- This is the canonical RPC for all job enqueue operations in the Dragonfly system.
-- =============================================================================
-- ---------------------------------------------------------------------------
-- 1. Add priority and run_at columns to ops.job_queue (if not exist)
-- ---------------------------------------------------------------------------
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
        AND column_name = 'priority'
) THEN
ALTER TABLE ops.job_queue
ADD COLUMN priority int NOT NULL DEFAULT 0;
COMMENT ON COLUMN ops.job_queue.priority IS 'Job priority (higher = more urgent). 0 is default.';
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
        AND column_name = 'run_at'
) THEN
ALTER TABLE ops.job_queue
ADD COLUMN run_at timestamptz NOT NULL DEFAULT now();
COMMENT ON COLUMN ops.job_queue.run_at IS 'Earliest time the job should be picked up. Enables delayed/scheduled jobs.';
END IF;
END $$;
-- ---------------------------------------------------------------------------
-- 2. Create index for priority-based job picking
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_job_queue_priority_run_at ON ops.job_queue (priority DESC, run_at ASC)
WHERE status = 'pending';
-- ---------------------------------------------------------------------------
-- 3. ops.queue_job - The canonical job enqueue RPC
-- ---------------------------------------------------------------------------
-- Safely inserts a new job into the queue with input validation.
-- All job producers MUST use this RPC instead of raw INSERT.
CREATE OR REPLACE FUNCTION ops.queue_job(
        p_type text,
        p_payload jsonb,
        p_priority int DEFAULT 0,
        p_run_at timestamptz DEFAULT now()
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_job_id uuid;
BEGIN -- 1. Input Validation
IF p_type IS NULL
OR p_type = '' THEN RAISE EXCEPTION 'Job type is required';
END IF;
IF p_payload IS NULL THEN p_payload := '{}'::jsonb;
END IF;
-- 2. Insert safely (job_type is cast to enum for type safety)
INSERT INTO ops.job_queue (job_type, payload, priority, status, run_at)
VALUES (
        p_type::ops.job_type_enum,
        p_payload,
        COALESCE(p_priority, 0),
        'pending',
        COALESCE(p_run_at, now())
    )
RETURNING id INTO v_job_id;
-- 3. Minimal Logging (visible in Postgres logs, not client)
RAISE LOG 'Job queued: % (Type: %, Priority: %)',
v_job_id,
p_type,
p_priority;
RETURN v_job_id;
END;
$$;
COMMENT ON FUNCTION ops.queue_job IS 'Securely enqueue a job into ops.job_queue. Validates input and handles insert atomically. All job producers must use this RPC instead of raw INSERT for least-privilege security.';
-- ---------------------------------------------------------------------------
-- 4. Grants - Allow dragonfly_app and service_role to execute
-- ---------------------------------------------------------------------------
GRANT EXECUTE ON FUNCTION ops.queue_job(text, jsonb, int, timestamptz) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.queue_job(text, jsonb, int, timestamptz) TO service_role;
-- ---------------------------------------------------------------------------
-- 5. Drop old ops.enqueue_job if exists (consolidate to queue_job)
-- ---------------------------------------------------------------------------
-- Keep for backward compatibility, but mark deprecated
COMMENT ON FUNCTION ops.enqueue_job IS 'DEPRECATED: Use ops.queue_job instead. This function will be removed in a future release.';