-- Migration: Fix ambiguous column reference in ops.claim_pending_job
-- The inner subquery needs explicit table alias for job_type column
CREATE OR REPLACE FUNCTION ops.claim_pending_job(
        p_job_types text [],
        p_lock_timeout_minutes integer DEFAULT 30
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
    attempts = jq.attempts + 1
WHERE jq.id = (
        SELECT inner_jq.id
        FROM ops.job_queue inner_jq
        WHERE inner_jq.job_type::text = ANY(p_job_types)
            AND inner_jq.status::text = 'pending'
            AND (
                inner_jq.locked_at IS NULL
                OR inner_jq.locked_at < now() - (p_lock_timeout_minutes || ' minutes')::interval
            )
        ORDER BY inner_jq.created_at ASC
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
COMMENT ON FUNCTION ops.claim_pending_job IS 'Securely claim a pending job from the queue using FOR UPDATE SKIP LOCKED.';
-- Ensure grants are in place
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER) TO service_role;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER) TO dragonfly_app;
