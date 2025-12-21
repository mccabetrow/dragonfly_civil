-- ============================================================================
-- ROLLBACK: 20251220180001_world_class_canonical_rpcs.sql
-- ============================================================================
-- Execute this script ONLY if the canonical migration causes issues and you
-- need to revert to the previous state.
--
-- WARNING: This will restore the 2-param claim_pending_job signature.
--          Any code expecting p_worker_id will break.
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. DROP CANONICAL FUNCTIONS
-- ============================================================================
DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT [], INTEGER, TEXT);
DROP FUNCTION IF EXISTS ops.update_job_status(UUID, TEXT, TEXT, INTEGER);
DROP FUNCTION IF EXISTS ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ);
DROP FUNCTION IF EXISTS ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT);
DROP FUNCTION IF EXISTS ops.reap_stuck_jobs(INTEGER);
-- ============================================================================
-- 2. RESTORE PREVIOUS claim_pending_job (2-param version)
-- ============================================================================
-- This is the version from 20251230000000_world_class_security.sql
CREATE OR REPLACE FUNCTION ops.claim_pending_job(
        p_job_types TEXT [],
        p_lock_timeout_minutes INTEGER DEFAULT 30
    ) RETURNS TABLE (
        job_id UUID,
        job_type TEXT,
        payload JSONB,
        attempts INTEGER,
        created_at TIMESTAMPTZ
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN RETURN QUERY
UPDATE ops.job_queue jq
SET status = 'processing',
    locked_at = now(),
    attempts = jq.attempts + 1
WHERE jq.id = (
        SELECT id
        FROM ops.job_queue
        WHERE job_type::text = ANY(p_job_types)
            AND status::text = 'pending'
            AND (
                locked_at IS NULL
                OR locked_at < now() - (p_lock_timeout_minutes || ' minutes')::interval
            )
        ORDER BY created_at ASC
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
COMMENT ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER) IS '[ROLLBACK] 2-param version. Consider upgrading to 3-param version.';
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER) TO service_role;
-- ============================================================================
-- 3. RESTORE PREVIOUS update_job_status (3-param version)
-- ============================================================================
-- This is the version from 20251230000000_world_class_security.sql
CREATE OR REPLACE FUNCTION ops.update_job_status(
        p_job_id UUID,
        p_status TEXT,
        p_error TEXT DEFAULT NULL
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN
UPDATE ops.job_queue
SET status = p_status,
    locked_at = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE locked_at
    END,
    last_error = COALESCE(LEFT(p_error, 2000), last_error),
    updated_at = now()
WHERE id = p_job_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT) IS '[ROLLBACK] 3-param version. Consider upgrading to 4-param version with backoff.';
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT) TO service_role;
-- ============================================================================
-- 4. NOTIFY POSTGREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- VERIFICATION
-- ============================================================================
\ echo 'Rollback complete. Verify with:' \ echo '  SELECT proname, pg_get_function_identity_arguments(oid) FROM pg_proc WHERE proname IN (''claim_pending_job'', ''update_job_status'') AND pronamespace = ''ops''::regnamespace;'