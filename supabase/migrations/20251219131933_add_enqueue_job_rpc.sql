-- Migration: Add ops.enqueue_job RPC
-- Purpose: Provide SECURITY DEFINER function for inserting jobs into ops.job_queue
-- This replaces raw INSERT INTO ops.job_queue statements in worker code
-- =============================================================================
-- ---------------------------------------------------------------------------
-- ops.enqueue_job - Secure job enqueueing
-- ---------------------------------------------------------------------------
-- Used by workers/services to add jobs to the queue without raw INSERT grant
CREATE OR REPLACE FUNCTION ops.enqueue_job(
        p_job_type TEXT,
        p_payload JSONB DEFAULT '{}'::jsonb,
        p_status TEXT DEFAULT 'pending'
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$
DECLARE v_job_id UUID;
BEGIN
INSERT INTO ops.job_queue (job_type, payload, status)
VALUES (
        p_job_type::ops.job_type_enum,
        p_payload,
        p_status
    )
RETURNING id INTO v_job_id;
RETURN v_job_id;
END;
$$;
COMMENT ON FUNCTION ops.enqueue_job IS 'Securely enqueue a job into ops.job_queue. Used by workers/services to create jobs without raw INSERT grant.';
-- Grant execute to dragonfly_app role
GRANT EXECUTE ON FUNCTION ops.enqueue_job(TEXT, JSONB, TEXT) TO dragonfly_app;