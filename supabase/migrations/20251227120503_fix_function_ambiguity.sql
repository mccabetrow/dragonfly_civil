-- Migration: 20251227120503_fix_function_ambiguity.sql
-- Purpose: Clean up ambiguous function overloads in ops schema
-- 
-- PROBLEM:
--   Multiple function signatures exist for the same logical operation,
--   causing "function is not unique" errors during GRANT/REVOKE operations.
--
-- CURRENT STATE (ops schema):
--   ops.claim_pending_job(p_job_types text[], p_lock_timeout_minutes integer) -- OLD
--   ops.claim_pending_job(p_worker_id uuid) -- WRONG
--   ops.claim_pending_job(p_job_types text[], p_lock_timeout_minutes integer, p_worker_id text) -- CANONICAL
--   ops.reap_stuck_jobs(p_lock_timeout_minutes integer) -- OLD
--   ops.reap_stuck_jobs(p_stuck_threshold interval) -- CANONICAL
--
-- SOLUTION:
--   1. Drop all non-canonical overloads using explicit signatures
--   2. Verify canonical versions remain intact
--   3. Re-apply grants to canonical versions only
--
-- ROLLBACK: None - we're removing ambiguity, not changing behavior
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. DROP OBSOLETE claim_pending_job OVERLOADS
-- ============================================================================
-- Drop the 2-arg version (missing worker_id)
DROP FUNCTION IF EXISTS ops.claim_pending_job(text [], integer);
-- Drop the wrong UUID-only version
DROP FUNCTION IF EXISTS ops.claim_pending_job(uuid);
-- Verify canonical 3-arg version exists
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'claim_pending_job'
        AND pg_get_function_identity_arguments(p.oid) = 'p_job_types text[], p_lock_timeout_minutes integer, p_worker_id text'
) THEN RAISE EXCEPTION 'Canonical ops.claim_pending_job(text[], integer, text) not found! Migration aborted.';
END IF;
RAISE NOTICE 'OK: ops.claim_pending_job(text[], integer, text) exists';
END $$;
-- ============================================================================
-- 2. DROP OBSOLETE reap_stuck_jobs OVERLOADS  
-- ============================================================================
-- Drop the integer-arg version (old signature)
DROP FUNCTION IF EXISTS ops.reap_stuck_jobs(integer);
-- Verify canonical interval version exists
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'ops'
        AND p.proname = 'reap_stuck_jobs'
        AND pg_get_function_identity_arguments(p.oid) = 'p_stuck_threshold interval'
) THEN RAISE EXCEPTION 'Canonical ops.reap_stuck_jobs(interval) not found! Migration aborted.';
END IF;
RAISE NOTICE 'OK: ops.reap_stuck_jobs(interval) exists';
END $$;
-- ============================================================================
-- 3. RE-APPLY GRANTS (Canonical Signatures Only)
-- ============================================================================
-- claim_pending_job: workers need to claim jobs
REVOKE ALL ON FUNCTION ops.claim_pending_job(text [], integer, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(text [], integer, text) TO service_role;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(text [], integer, text) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(text [], integer, text) TO dragonfly_app;
-- reap_stuck_jobs: only service_role and postgres should reap
REVOKE ALL ON FUNCTION ops.reap_stuck_jobs(interval)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(interval) TO service_role;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(interval) TO postgres;
-- ============================================================================
-- 4. VERIFY NO AMBIGUITY REMAINS
-- ============================================================================
DO $$
DECLARE claim_count integer;
reap_count integer;
BEGIN -- Count claim_pending_job overloads
SELECT count(*) INTO claim_count
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'ops'
    AND p.proname = 'claim_pending_job';
IF claim_count != 1 THEN RAISE EXCEPTION 'Expected 1 claim_pending_job function, found %',
claim_count;
END IF;
-- Count reap_stuck_jobs overloads
SELECT count(*) INTO reap_count
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'ops'
    AND p.proname = 'reap_stuck_jobs';
IF reap_count != 1 THEN RAISE EXCEPTION 'Expected 1 reap_stuck_jobs function, found %',
reap_count;
END IF;
RAISE NOTICE 'SUCCESS: No function ambiguity - claim_pending_job=%, reap_stuck_jobs=%',
claim_count,
reap_count;
END $$;
COMMIT;
-- ============================================================================
-- VERIFICATION QUERY (run after migration)
-- ============================================================================
-- SELECT n.nspname, p.proname, pg_get_function_identity_arguments(p.oid) as args
-- FROM pg_proc p 
-- JOIN pg_namespace n ON p.pronamespace = n.oid 
-- WHERE n.nspname = 'ops' 
-- AND (p.proname LIKE '%reap%' OR p.proname LIKE '%claim%')
-- ORDER BY p.proname;
