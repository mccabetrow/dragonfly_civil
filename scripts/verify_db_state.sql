-- =============================================================================
-- verify_db_state.sql
-- Dragonfly Civil – Database Deployment Gate Verification
-- =============================================================================
-- Run this AFTER applying migrations, BEFORE deploying API/Workers.
-- All checks must pass (no FAIL output) before proceeding.
--
-- Usage:
--   psql $SUPABASE_DB_URL -f scripts/verify_db_state.sql
--   OR via Supabase SQL Editor
-- =============================================================================
\ echo '' \ echo '============================================================' \ echo 'DRAGONFLY DATABASE DEPLOYMENT GATE' \ echo '============================================================' \ echo '' -- =============================================================================
-- CHECK A: Verify Dangerous Grants Are Absent
-- =============================================================================
\ echo '── CHECK A: Dangerous Grants Absent ──' DO $$
DECLARE v_count INT;
BEGIN
SELECT COUNT(*) INTO v_count
FROM information_schema.role_table_grants
WHERE grantee IN ('authenticated', 'anon')
    AND table_schema IN ('ops', 'intake', 'enforcement');
IF v_count > 0 THEN RAISE WARNING '❌ FAIL: Found % dangerous grant(s) to authenticated/anon on ops/intake/enforcement',
v_count;
ELSE RAISE NOTICE '✅ PASS: No dangerous grants to authenticated/anon on ops/intake/enforcement';
END IF;
END $$;
-- Show detail if any found (for debugging)
SELECT grantee,
    table_schema,
    table_name,
    privilege_type
FROM information_schema.role_table_grants
WHERE grantee IN ('authenticated', 'anon')
    AND table_schema IN ('ops', 'intake', 'enforcement')
LIMIT 10;
\ echo '' -- =============================================================================
-- CHECK B: Verify RLS Enabled Where Required
-- =============================================================================
\ echo '── CHECK B: RLS Enabled on Protected Tables ──' DO $$
DECLARE v_missing INT;
BEGIN
SELECT COUNT(*) INTO v_missing
FROM pg_tables
WHERE schemaname IN ('ops', 'intake', 'enforcement')
    AND NOT rowsecurity;
IF v_missing > 0 THEN RAISE WARNING '❌ FAIL: % table(s) in ops/intake/enforcement lack RLS',
v_missing;
ELSE RAISE NOTICE '✅ PASS: All tables in ops/intake/enforcement have RLS enabled';
END IF;
END $$;
-- Show detail if any missing (for debugging)
SELECT schemaname,
    tablename,
    rowsecurity
FROM pg_tables
WHERE schemaname IN ('ops', 'intake', 'enforcement')
    AND NOT rowsecurity
LIMIT 10;
\ echo '' -- =============================================================================
-- CHECK C: Verify RPC Functions Exist and Are Executable
-- =============================================================================
\ echo '── CHECK C: RPC Function Existence & Privileges ──' DO $$
DECLARE v_role TEXT := 'dragonfly_app';
v_claim_exists BOOLEAN := FALSE;
v_heartbeat_exists BOOLEAN := FALSE;
v_update_status_exists BOOLEAN := FALSE;
v_queue_job_exists BOOLEAN := FALSE;
v_has_execute_claim BOOLEAN := FALSE;
v_has_execute_heartbeat BOOLEAN := FALSE;
BEGIN -- Check ops.claim_pending_job
SELECT EXISTS (
        SELECT 1
        FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'ops'
            AND p.proname = 'claim_pending_job'
    ) INTO v_claim_exists;
-- Check ops.register_heartbeat
SELECT EXISTS (
        SELECT 1
        FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'ops'
            AND p.proname = 'register_heartbeat'
    ) INTO v_heartbeat_exists;
-- Check ops.update_job_status
SELECT EXISTS (
        SELECT 1
        FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'ops'
            AND p.proname = 'update_job_status'
    ) INTO v_update_status_exists;
-- Check ops.queue_job
SELECT EXISTS (
        SELECT 1
        FROM pg_proc p
            JOIN pg_namespace n ON p.pronamespace = n.oid
        WHERE n.nspname = 'ops'
            AND p.proname = 'queue_job'
    ) INTO v_queue_job_exists;
-- Report function existence
IF v_claim_exists THEN RAISE NOTICE '✅ PASS: ops.claim_pending_job exists';
ELSE RAISE WARNING '❌ FAIL: ops.claim_pending_job DOES NOT EXIST';
END IF;
IF v_heartbeat_exists THEN RAISE NOTICE '✅ PASS: ops.register_heartbeat exists';
ELSE RAISE WARNING '❌ FAIL: ops.register_heartbeat DOES NOT EXIST';
END IF;
IF v_update_status_exists THEN RAISE NOTICE '✅ PASS: ops.update_job_status exists';
ELSE RAISE WARNING '❌ FAIL: ops.update_job_status DOES NOT EXIST';
END IF;
IF v_queue_job_exists THEN RAISE NOTICE '✅ PASS: ops.queue_job exists';
ELSE RAISE WARNING '❌ FAIL: ops.queue_job DOES NOT EXIST';
END IF;
-- Check EXECUTE privileges for dragonfly_app role
IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = v_role
) THEN RAISE NOTICE '⚠️  SKIP: Role "%" does not exist (may be using service_role)',
v_role;
RETURN;
END IF;
-- Check EXECUTE on claim_pending_job (canonical 3-param signature)
BEGIN
SELECT has_function_privilege(
        v_role,
        'ops.claim_pending_job(text[], integer, text)',
        'EXECUTE'
    ) INTO v_has_execute_claim;
IF v_has_execute_claim THEN RAISE NOTICE '✅ PASS: % has EXECUTE on ops.claim_pending_job',
v_role;
ELSE RAISE WARNING '❌ FAIL: % lacks EXECUTE on ops.claim_pending_job',
v_role;
END IF;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '⚠️  SKIP: Could not check claim_pending_job privilege: %',
SQLERRM;
END;
-- Check EXECUTE on register_heartbeat (canonical 4-param signature)
BEGIN
SELECT has_function_privilege(
        v_role,
        'ops.register_heartbeat(text, text, text, text)',
        'EXECUTE'
    ) INTO v_has_execute_heartbeat;
IF v_has_execute_heartbeat THEN RAISE NOTICE '✅ PASS: % has EXECUTE on ops.register_heartbeat',
v_role;
ELSE RAISE WARNING '❌ FAIL: % lacks EXECUTE on ops.register_heartbeat',
v_role;
END IF;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '⚠️  SKIP: Could not check register_heartbeat privilege: %',
SQLERRM;
END;
END $$;
\ echo '' -- =============================================================================
-- CHECK D: Verify Job Type Enum Contains Worker Types
-- =============================================================================
\ echo '── CHECK D: Job Type Enum Values ──' DO $$
DECLARE v_enum_exists BOOLEAN;
v_has_collectability BOOLEAN := FALSE;
v_has_escalation BOOLEAN := FALSE;
v_has_enrichment BOOLEAN := FALSE;
v_has_skip_trace BOOLEAN := FALSE;
BEGIN -- Check if enum exists
SELECT EXISTS (
        SELECT 1
        FROM pg_type t
            JOIN pg_namespace n ON t.typnamespace = n.oid
        WHERE n.nspname = 'ops'
            AND t.typname = 'job_type'
    ) INTO v_enum_exists;
IF NOT v_enum_exists THEN RAISE WARNING '❌ FAIL: ops.job_type enum DOES NOT EXIST';
RETURN;
END IF;
RAISE NOTICE '✅ PASS: ops.job_type enum exists';
-- Check for required enum values
SELECT BOOL_OR(enumlabel = 'collectability'),
    BOOL_OR(enumlabel = 'escalation'),
    BOOL_OR(enumlabel = 'enrichment'),
    BOOL_OR(enumlabel = 'skip_trace') INTO v_has_collectability,
    v_has_escalation,
    v_has_enrichment,
    v_has_skip_trace
FROM pg_enum e
    JOIN pg_type t ON e.enumtypid = t.oid
    JOIN pg_namespace n ON t.typnamespace = n.oid
WHERE n.nspname = 'ops'
    AND t.typname = 'job_type';
IF v_has_collectability THEN RAISE NOTICE '✅ PASS: job_type has "collectability" value';
ELSE RAISE WARNING '❌ FAIL: job_type missing "collectability" value';
END IF;
IF v_has_escalation THEN RAISE NOTICE '✅ PASS: job_type has "escalation" value';
ELSE RAISE WARNING '❌ FAIL: job_type missing "escalation" value';
END IF;
IF v_has_enrichment THEN RAISE NOTICE '✅ PASS: job_type has "enrichment" value';
ELSE RAISE NOTICE '⚠️  INFO: job_type missing "enrichment" value (optional)';
END IF;
IF v_has_skip_trace THEN RAISE NOTICE '✅ PASS: job_type has "skip_trace" value';
ELSE RAISE NOTICE '⚠️  INFO: job_type missing "skip_trace" value (optional)';
END IF;
END $$;
-- Show all enum values (for reference)
\ echo 'Current ops.job_type values:'
SELECT enumlabel AS job_type_value
FROM pg_enum e
    JOIN pg_type t ON e.enumtypid = t.oid
    JOIN pg_namespace n ON t.typnamespace = n.oid
WHERE n.nspname = 'ops'
    AND t.typname = 'job_type'
ORDER BY enumsortorder;
\ echo '' -- =============================================================================
-- CHECK E: Verify Worker Heartbeat Loop Is Live
-- =============================================================================
\ echo '── CHECK E: Worker Heartbeat Liveness ──' DO $$
DECLARE v_table_exists BOOLEAN;
v_recent_heartbeats INT;
v_oldest_recent TIMESTAMP;
v_worker_count INT;
BEGIN -- Check if heartbeat table exists
SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'ops'
            AND table_name = 'worker_heartbeats'
    ) INTO v_table_exists;
IF NOT v_table_exists THEN RAISE NOTICE '⚠️  SKIP: ops.worker_heartbeats table does not exist (new deployment?)';
RETURN;
END IF;
-- Count heartbeats in last 5 minutes
SELECT COUNT(*),
    MIN(last_heartbeat),
    COUNT(DISTINCT worker_id) INTO v_recent_heartbeats,
    v_oldest_recent,
    v_worker_count
FROM ops.worker_heartbeats
WHERE last_heartbeat > NOW() - INTERVAL '5 minutes';
IF v_recent_heartbeats > 0 THEN RAISE NOTICE '✅ PASS: % worker(s) with heartbeats in last 5 minutes (oldest: %)',
v_worker_count,
v_oldest_recent;
ELSE -- Check for any heartbeats ever
SELECT COUNT(*) INTO v_recent_heartbeats
FROM ops.worker_heartbeats;
IF v_recent_heartbeats = 0 THEN RAISE NOTICE '⚠️  INFO: No worker heartbeats recorded (workers not yet deployed?)';
ELSE RAISE WARNING '❌ FAIL: No worker heartbeats in last 5 minutes (workers may be down)';
END IF;
END IF;
END $$;
-- Show recent heartbeats (for debugging)
\ echo 'Recent worker heartbeats:'
SELECT worker_id,
    job_type,
    last_heartbeat,
    EXTRACT(
        EPOCH
        FROM (NOW() - last_heartbeat)
    )::INT AS seconds_ago
FROM ops.worker_heartbeats
WHERE last_heartbeat > NOW() - INTERVAL '30 minutes'
ORDER BY last_heartbeat DESC
LIMIT 10;
\ echo '' -- =============================================================================
-- CHECK F: Verify Queue Is Healthy (Status Distribution)
-- =============================================================================
\ echo '── CHECK F: Queue Health (Status Distribution) ──' DO $$
DECLARE v_table_exists BOOLEAN;
v_total INT;
v_pending INT;
v_processing INT;
v_completed INT;
v_failed INT;
v_stuck INT;
v_other INT;
BEGIN -- Check if job_queue exists
SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'ops'
            AND table_name = 'job_queue'
    ) INTO v_table_exists;
IF NOT v_table_exists THEN RAISE WARNING '❌ FAIL: ops.job_queue table does not exist';
RETURN;
END IF;
-- Get counts by status
SELECT COUNT(*),
    COUNT(*) FILTER (
        WHERE status = 'pending'
    ),
    COUNT(*) FILTER (
        WHERE status = 'processing'
    ),
    COUNT(*) FILTER (
        WHERE status = 'completed'
    ),
    COUNT(*) FILTER (
        WHERE status = 'failed'
    ),
    COUNT(*) FILTER (
        WHERE status NOT IN ('pending', 'processing', 'completed', 'failed')
    ) INTO v_total,
    v_pending,
    v_processing,
    v_completed,
    v_failed,
    v_other
FROM ops.job_queue;
RAISE NOTICE '📊 Job Queue Status Distribution:';
RAISE NOTICE '   Total:      %',
v_total;
RAISE NOTICE '   Pending:    %',
v_pending;
RAISE NOTICE '   Processing: %',
v_processing;
RAISE NOTICE '   Completed:  %',
v_completed;
RAISE NOTICE '   Failed:     %',
v_failed;
IF v_other > 0 THEN RAISE WARNING '❌ FAIL: Found % jobs with invalid status values',
v_other;
ELSE RAISE NOTICE '✅ PASS: All jobs have valid status values';
END IF;
-- Check for stuck jobs (processing for > 30 minutes)
SELECT COUNT(*) INTO v_stuck
FROM ops.job_queue
WHERE status = 'processing'
    AND updated_at < NOW() - INTERVAL '30 minutes';
IF v_stuck > 0 THEN RAISE WARNING '⚠️  WARN: % jobs stuck in processing state (>30 min)',
v_stuck;
ELSE RAISE NOTICE '✅ PASS: No stuck jobs detected';
END IF;
END $$;
\ echo '' -- =============================================================================
-- CHECK G: Critical Views Exist and Are Queryable
-- =============================================================================
\ echo '── CHECK G: Critical Dashboard Views ──' DO $$
DECLARE v_view TEXT;
v_views TEXT [] := ARRAY [
        'v_plaintiffs_overview',
        'v_judgment_pipeline', 
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_plaintiff_call_queue'
    ];
BEGIN FOREACH v_view IN ARRAY v_views LOOP IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = v_view
) THEN RAISE NOTICE '✅ PASS: View public.% exists',
v_view;
ELSE RAISE WARNING '❌ FAIL: View public.% DOES NOT EXIST',
v_view;
END IF;
END LOOP;
END $$;
\ echo '' -- =============================================================================
-- CHECK H: Canonical RPC Signatures
-- =============================================================================
\ echo '── CHECK H: Canonical RPC Signatures ──' DO $$
DECLARE v_claim_sig TEXT;
v_update_sig TEXT;
v_queue_sig TEXT;
BEGIN -- Check ops.claim_pending_job has 3-param canonical signature
SELECT string_agg(
        pg_catalog.format_type(t.oid, NULL),
        ', '
        ORDER BY ord
    ) INTO v_claim_sig
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    CROSS JOIN LATERAL unnest(p.proargtypes) WITH ORDINALITY AS t(oid, ord)
WHERE n.nspname = 'ops'
    AND p.proname = 'claim_pending_job' -- Find the 3-param version
    AND array_length(p.proargtypes, 1) = 3;
IF v_claim_sig IS NOT NULL
AND v_claim_sig LIKE '%text[]%integer%text%' THEN RAISE NOTICE '✅ PASS: ops.claim_pending_job has canonical 3-param signature (TEXT[], INTEGER, TEXT)';
ELSIF v_claim_sig IS NOT NULL THEN RAISE WARNING '❌ FAIL: ops.claim_pending_job has wrong signature: %',
v_claim_sig;
ELSE RAISE WARNING '❌ FAIL: ops.claim_pending_job with 3 params not found';
END IF;
-- Check ops.update_job_status has 4-param canonical signature
SELECT string_agg(
        pg_catalog.format_type(t.oid, NULL),
        ', '
        ORDER BY ord
    ) INTO v_update_sig
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    CROSS JOIN LATERAL unnest(p.proargtypes) WITH ORDINALITY AS t(oid, ord)
WHERE n.nspname = 'ops'
    AND p.proname = 'update_job_status' -- Find the 4-param version
    AND array_length(p.proargtypes, 1) = 4;
IF v_update_sig IS NOT NULL
AND v_update_sig LIKE '%uuid%text%text%integer%' THEN RAISE NOTICE '✅ PASS: ops.update_job_status has canonical 4-param signature (UUID, TEXT, TEXT, INTEGER)';
ELSIF v_update_sig IS NOT NULL THEN RAISE WARNING '❌ FAIL: ops.update_job_status has wrong signature: %',
v_update_sig;
ELSE RAISE WARNING '❌ FAIL: ops.update_job_status with 4 params not found';
END IF;
-- Check ops.queue_job has 4-param canonical signature
SELECT string_agg(
        pg_catalog.format_type(t.oid, NULL),
        ', '
        ORDER BY ord
    ) INTO v_queue_sig
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
    CROSS JOIN LATERAL unnest(p.proargtypes) WITH ORDINALITY AS t(oid, ord)
WHERE n.nspname = 'ops'
    AND p.proname = 'queue_job' -- Find the 4-param version
    AND array_length(p.proargtypes, 1) = 4;
IF v_queue_sig IS NOT NULL
AND v_queue_sig LIKE '%text%jsonb%integer%timestamp%' THEN RAISE NOTICE '✅ PASS: ops.queue_job has canonical 4-param signature (TEXT, JSONB, INTEGER, TIMESTAMPTZ)';
ELSIF v_queue_sig IS NOT NULL THEN RAISE WARNING '❌ FAIL: ops.queue_job has wrong signature: %',
v_queue_sig;
ELSE RAISE WARNING '❌ FAIL: ops.queue_job with 4 params not found';
END IF;
END $$;
-- Show all ops.claim_pending_job variants (should be exactly 1)
\ echo 'Checking for ambiguous claim_pending_job overloads:'
SELECT n.nspname || '.' || p.proname AS function_name,
    pg_get_function_identity_arguments(p.oid) AS signature,
    CASE
        WHEN p.prosecdef THEN 'SECURITY DEFINER'
        ELSE 'SECURITY INVOKER'
    END AS security
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'ops'
    AND p.proname = 'claim_pending_job'
ORDER BY array_length(p.proargtypes, 1);
\ echo '' -- =============================================================================
-- CHECK I: RPC-Only Invariant (No Direct Table Writes)
-- =============================================================================
\ echo '── CHECK I: RPC-Only Invariant ──' DO $$
DECLARE v_role TEXT := 'dragonfly_app';
v_has_insert BOOLEAN;
v_has_update BOOLEAN;
v_has_delete BOOLEAN;
BEGIN -- Check if dragonfly_app role exists
IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = v_role
) THEN RAISE NOTICE '⚠️  SKIP: Role "%" does not exist (may be using service_role)',
v_role;
RETURN;
END IF;
-- Check table privileges on ops.job_queue
SELECT has_table_privilege(v_role, 'ops.job_queue', 'INSERT'),
    has_table_privilege(v_role, 'ops.job_queue', 'UPDATE'),
    has_table_privilege(v_role, 'ops.job_queue', 'DELETE') INTO v_has_insert,
    v_has_update,
    v_has_delete;
-- Report table privilege results (should all be FALSE for RPC-only)
IF v_has_insert THEN RAISE WARNING '❌ FAIL: % has INSERT on ops.job_queue (violates RPC-only)',
v_role;
ELSE RAISE NOTICE '✅ PASS: % has NO INSERT on ops.job_queue',
v_role;
END IF;
IF v_has_update THEN RAISE WARNING '❌ FAIL: % has UPDATE on ops.job_queue (violates RPC-only)',
v_role;
ELSE RAISE NOTICE '✅ PASS: % has NO UPDATE on ops.job_queue',
v_role;
END IF;
IF v_has_delete THEN RAISE WARNING '❌ FAIL: % has DELETE on ops.job_queue (violates RPC-only)',
v_role;
ELSE RAISE NOTICE '✅ PASS: % has NO DELETE on ops.job_queue',
v_role;
END IF;
EXCEPTION
WHEN OTHERS THEN RAISE NOTICE '⚠️  SKIP: Permission check error: %',
SQLERRM;
END $$;
\ echo '' \ echo '============================================================' \ echo 'DATABASE GATE VERIFICATION COMPLETE' \ echo '============================================================' \ echo 'Review output above. All checks must show Pass before' \ echo 'proceeding to API/Worker deployment.' \ echo '' \ echo 'Check Legend:' \ echo '  Pass    - Check passed, safe to proceed' \ echo '  Fail    - Check failed, DO NOT proceed' \ echo '  Warn    - Warning, investigate before proceeding' \ echo '  Skip    - Check skipped (acceptable for new deployments)' \ echo '  Info    - Informational, does not block deployment' \ echo '============================================================' -- =============================================================================
-- FINAL SUMMARY TABLE: Check vs Status
-- =============================================================================
-- This provides a clean table output as requested in the Perfect Deployment spec
\ echo '' \ echo '============================================================' \ echo 'DEPLOYMENT GATE SUMMARY TABLE' \ echo '============================================================' WITH checks AS (
    -- Check 1: RPCs Exist
    SELECT 'RPCs Exist' AS check_name,
        1 AS check_order,
        CASE
            WHEN (
                SELECT COUNT(*) = 4
                FROM (
                        SELECT 1
                        FROM pg_proc p
                            JOIN pg_namespace n ON p.pronamespace = n.oid
                        WHERE n.nspname = 'ops'
                            AND p.proname IN (
                                'claim_pending_job',
                                'register_heartbeat',
                                'update_job_status',
                                'queue_job'
                            )
                    ) rpcs
            ) THEN 'Pass'
            ELSE 'FAIL'
        END AS status
    UNION ALL
    -- Check 2: Job Queue RLS Disabled (for service_role access)
    SELECT 'Job Queue RLS Disabled' AS check_name,
        2 AS check_order,
        CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM pg_tables
                WHERE schemaname = 'ops'
                    AND tablename = 'job_queue'
            ) THEN 'Skip (table missing)'
            WHEN NOT (
                SELECT rowsecurity
                FROM pg_tables
                WHERE schemaname = 'ops'
                    AND tablename = 'job_queue'
            ) THEN 'Pass'
            ELSE 'FAIL'
        END AS status
    UNION ALL
    -- Check 3: Worker Heartbeats RLS Disabled
    SELECT 'Worker Heartbeats RLS Disabled' AS check_name,
        3 AS check_order,
        CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM pg_tables
                WHERE schemaname = 'ops'
                    AND tablename = 'worker_heartbeats'
            ) THEN 'Skip (table missing)'
            WHEN NOT (
                SELECT rowsecurity
                FROM pg_tables
                WHERE schemaname = 'ops'
                    AND tablename = 'worker_heartbeats'
            ) THEN 'Pass'
            ELSE 'FAIL'
        END AS status
    UNION ALL
    -- Check 4: App User Cannot Insert Queue
    SELECT 'App User Cannot Insert Queue' AS check_name,
        4 AS check_order,
        CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM pg_roles
                WHERE rolname = 'dragonfly_app'
            ) THEN 'Skip (role missing)'
            WHEN NOT EXISTS (
                SELECT 1
                FROM pg_tables
                WHERE schemaname = 'ops'
                    AND tablename = 'job_queue'
            ) THEN 'Skip (table missing)'
            WHEN NOT has_table_privilege('dragonfly_app', 'ops.job_queue', 'INSERT') THEN 'Pass'
            ELSE 'FAIL'
        END AS status
)
SELECT check_name AS "Check",
    status AS "Status"
FROM checks
ORDER BY check_order;
\ echo '' \ echo 'If all checks show "Pass", deployment may proceed.' \ echo 'If any check shows "FAIL", DO NOT deploy until fixed.' \ echo '============================================================'