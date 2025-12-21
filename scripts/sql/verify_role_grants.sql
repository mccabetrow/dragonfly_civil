-- ============================================================================
-- Verification Script: Dragonfly Least Privilege Security Model
-- ============================================================================
-- 
-- This script is READ-ONLY and produces a comprehensive audit of:
-- 1. Role existence and attributes
-- 2. Schema grants per role
-- 3. Table grants per role (with RLS state)
-- 4. Function grants per role
-- 5. Sequence grants
-- 6. Summary matrix
--
-- Run this after applying the migration to verify correct configuration.
-- ============================================================================
-- ============================================================================
-- 1. ROLE EXISTENCE CHECK
-- ============================================================================
SELECT '=== ROLE EXISTENCE CHECK ===' AS section;
SELECT rolname AS role_name,
    CASE
        WHEN rolcanlogin THEN 'YES'
        ELSE 'NO'
    END AS can_login,
    CASE
        WHEN rolinherit THEN 'YES'
        ELSE 'NO'
    END AS inherits,
    CASE
        WHEN rolcreatedb THEN 'YES'
        ELSE 'NO'
    END AS create_db,
    CASE
        WHEN rolcreaterole THEN 'YES'
        ELSE 'NO'
    END AS create_role,
    CASE
        WHEN rolreplication THEN 'YES'
        ELSE 'NO'
    END AS replication
FROM pg_roles
WHERE rolname IN (
        'dragonfly_app',
        'dragonfly_worker',
        'dragonfly_readonly',
        'postgres',
        'service_role'
    )
ORDER BY CASE
        rolname
        WHEN 'postgres' THEN 1
        WHEN 'service_role' THEN 2
        WHEN 'dragonfly_app' THEN 3
        WHEN 'dragonfly_worker' THEN 4
        WHEN 'dragonfly_readonly' THEN 5
    END;
-- ============================================================================
-- 2. SCHEMA GRANTS
-- ============================================================================
SELECT '=== SCHEMA GRANTS ===' AS section;
WITH schemas AS (
    SELECT nspname AS schema_name
    FROM pg_namespace
    WHERE nspname IN (
            'public',
            'ops',
            'enforcement',
            'intelligence',
            'analytics',
            'finance',
            'intake'
        )
),
roles AS (
    SELECT unnest(
            ARRAY ['dragonfly_app', 'dragonfly_worker', 'dragonfly_readonly']
        ) AS role_name
)
SELECT s.schema_name,
    r.role_name,
    CASE
        WHEN has_schema_privilege(r.role_name, s.schema_name, 'USAGE') THEN 'USAGE'
        ELSE '-'
    END AS usage_grant,
    CASE
        WHEN has_schema_privilege(r.role_name, s.schema_name, 'CREATE') THEN 'CREATE'
        ELSE '-'
    END AS create_grant
FROM schemas s
    CROSS JOIN roles r
ORDER BY s.schema_name,
    r.role_name;
-- ============================================================================
-- 3. TABLE GRANTS WITH RLS STATE
-- ============================================================================
SELECT '=== TABLE GRANTS (with RLS state) ===' AS section;
WITH tables AS (
    SELECT n.nspname AS schema_name,
        c.relname AS table_name,
        c.relrowsecurity AS rls_enabled,
        c.relforcerowsecurity AS rls_forced
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'r'
        AND n.nspname IN ('public', 'ops', 'enforcement', 'intake')
        AND c.relname IN (
            'judgments',
            'plaintiffs',
            'plaintiff_contacts',
            'enforcement_cases',
            'job_queue',
            'worker_heartbeats',
            'intake_logs',
            'ingest_batches'
        )
),
roles AS (
    SELECT unnest(
            ARRAY ['dragonfly_app', 'dragonfly_worker', 'dragonfly_readonly']
        ) AS role_name
)
SELECT t.schema_name || '.' || t.table_name AS "table",
    r.role_name,
    CASE
        WHEN t.rls_enabled THEN 'ENABLED'
        ELSE 'DISABLED'
    END AS rls_state,
    CASE
        WHEN has_table_privilege(
            r.role_name,
            t.schema_name || '.' || t.table_name,
            'SELECT'
        ) THEN 'S'
        ELSE '-'
    END || CASE
        WHEN has_table_privilege(
            r.role_name,
            t.schema_name || '.' || t.table_name,
            'INSERT'
        ) THEN 'I'
        ELSE '-'
    END || CASE
        WHEN has_table_privilege(
            r.role_name,
            t.schema_name || '.' || t.table_name,
            'UPDATE'
        ) THEN 'U'
        ELSE '-'
    END || CASE
        WHEN has_table_privilege(
            r.role_name,
            t.schema_name || '.' || t.table_name,
            'DELETE'
        ) THEN 'D'
        ELSE '-'
    END AS privileges
FROM tables t
    CROSS JOIN roles r
ORDER BY t.schema_name,
    t.table_name,
    r.role_name;
-- ============================================================================
-- 4. INTERNAL OPS TABLES - DETAILED RLS CHECK
-- ============================================================================
SELECT '=== INTERNAL OPS TABLES - RLS DETAIL ===' AS section;
SELECT c.relname AS table_name,
    CASE
        WHEN c.relrowsecurity THEN 'ENABLED'
        ELSE 'DISABLED'
    END AS rls_status,
    CASE
        WHEN NOT c.relrowsecurity THEN 'OK - RLS disabled for internal table'
        ELSE 'REVIEW - RLS enabled on internal table'
    END AS recommendation
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
    AND c.relkind = 'r'
    AND c.relname IN (
        'job_queue',
        'worker_heartbeats',
        'intake_logs',
        'ingest_batches'
    )
ORDER BY c.relname;
-- ============================================================================
-- 5. FUNCTION GRANTS
-- ============================================================================
SELECT '=== FUNCTION GRANTS ===' AS section;
WITH funcs AS (
    SELECT n.nspname AS schema_name,
        p.proname AS function_name,
        pg_get_function_identity_arguments(p.oid) AS args,
        CASE
            WHEN p.prosecdef THEN 'SECURITY DEFINER'
            ELSE 'INVOKER'
        END AS security_mode
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname IN ('ops', 'public')
        AND p.proname IN (
            'claim_pending_job',
            'update_job_status',
            'register_heartbeat',
            'queue_job',
            'log_intake_event',
            'upsert_judgment',
            'ceo_12_metrics',
            'intake_radar_metrics_v2'
        )
),
roles AS (
    SELECT unnest(
            ARRAY ['dragonfly_app', 'dragonfly_worker', 'dragonfly_readonly']
        ) AS role_name
)
SELECT f.schema_name || '.' || f.function_name AS "function",
    f.security_mode,
    r.role_name,
    CASE
        WHEN has_function_privilege(
            r.role_name,
            f.schema_name || '.' || f.function_name || '(' || f.args || ')',
            'EXECUTE'
        ) THEN 'EXECUTE'
        ELSE '-'
    END AS grant_status
FROM funcs f
    CROSS JOIN roles r
ORDER BY f.schema_name,
    f.function_name,
    r.role_name;
-- ============================================================================
-- 6. SEQUENCE GRANTS
-- ============================================================================
SELECT '=== SEQUENCE GRANTS ===' AS section;
WITH seqs AS (
    SELECT n.nspname AS schema_name,
        c.relname AS sequence_name
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE c.relkind = 'S'
        AND n.nspname IN ('public', 'ops')
    LIMIT 10 -- Sample only
), roles AS (
    SELECT unnest(
            ARRAY ['dragonfly_app', 'dragonfly_worker', 'dragonfly_readonly']
        ) AS role_name
)
SELECT s.schema_name || '.' || s.sequence_name AS "sequence",
    r.role_name,
    CASE
        WHEN has_sequence_privilege(
            r.role_name,
            s.schema_name || '.' || s.sequence_name,
            'USAGE'
        ) THEN 'USAGE'
        ELSE '-'
    END AS grant_status
FROM seqs s
    CROSS JOIN roles r
ORDER BY s.schema_name,
    s.sequence_name,
    r.role_name;
-- ============================================================================
-- 7. PRIVILEGE SUMMARY MATRIX
-- ============================================================================
SELECT '=== PRIVILEGE SUMMARY MATRIX ===' AS section;
SELECT 'dragonfly_app' AS role,
    'API Runtime' AS purpose,
    'SELECT on public/ops tables' AS table_access,
    'queue_job, log_intake_event' AS rpc_access,
    'Cannot claim jobs or write directly' AS restrictions
UNION ALL
SELECT 'dragonfly_worker',
    'Background Workers',
    'SELECT + INSERT/UPDATE on ops tables',
    'claim_pending_job, update_job_status, register_heartbeat, queue_job, upsert_judgment',
    'Full ops access for job processing'
UNION ALL
SELECT 'dragonfly_readonly',
    'Dashboard Analytics',
    'SELECT only on views',
    'ceo_12_metrics, intake_radar_metrics_v2',
    'No table writes, no job RPCs';
-- ============================================================================
-- 8. SECURITY RECOMMENDATIONS CHECK
-- ============================================================================
SELECT '=== SECURITY RECOMMENDATIONS CHECK ===' AS section;
-- Check for any overly broad grants
SELECT 'PUBLIC schema CREATE' AS check_item,
    CASE
        WHEN has_schema_privilege('public', 'public', 'CREATE') THEN 'WARNING: PUBLIC can CREATE in public schema'
        ELSE 'OK: CREATE revoked from PUBLIC'
    END AS status;
-- Check authenticated role access to ops (CRITICAL)
SELECT 'authenticated role ops WRITE access' AS check_item,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM information_schema.table_privileges
            WHERE grantee = 'authenticated'
                AND table_schema = 'ops'
                AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
        ) THEN '❌ CRITICAL: authenticated has WRITE access to ops - SECURITY VIOLATION'
        ELSE '✅ OK: authenticated has no write access to ops'
    END AS status;
-- Check anon role access to ops (CRITICAL)
SELECT 'anon role ops WRITE access' AS check_item,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM information_schema.table_privileges
            WHERE grantee = 'anon'
                AND table_schema = 'ops'
                AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
        ) THEN '❌ CRITICAL: anon has WRITE access to ops - SECURITY VIOLATION'
        ELSE '✅ OK: anon has no write access to ops'
    END AS status;
-- Check service_role HAS write access (should be true)
SELECT 'service_role ops WRITE access' AS check_item,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM information_schema.table_privileges
            WHERE grantee = 'service_role'
                AND table_schema = 'ops'
                AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE')
        ) THEN '✅ OK: service_role has write access to ops'
        ELSE '⚠️ WARNING: service_role missing write access to ops'
    END AS status;
-- Check SECURITY DEFINER functions have SET search_path
SELECT n.nspname || '.' || p.proname AS "function",
    CASE
        WHEN p.prosecdef
        AND p.proconfig IS NULL THEN 'WARNING: SECURITY DEFINER without SET search_path'
        WHEN p.prosecdef THEN 'OK: SECURITY DEFINER with config'
        ELSE 'N/A: Not SECURITY DEFINER'
    END AS status
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops'
    AND p.proname IN (
        'claim_pending_job',
        'update_job_status',
        'register_heartbeat',
        'queue_job'
    )
ORDER BY p.proname;
-- ============================================================================
-- 9. ROLE CONNECTION STRING REFERENCE
-- ============================================================================
SELECT '=== CONNECTION STRING REFERENCE ===' AS section;
SELECT 'dragonfly_app' AS role,
    'postgresql://dragonfly_app:<PASSWORD>@db.<PROJECT>.supabase.co:5432/postgres?sslmode=require' AS connection_template,
    'API service (Railway SUPABASE_DB_URL)' AS usage
UNION ALL
SELECT 'dragonfly_worker',
    'postgresql://dragonfly_worker:<PASSWORD>@db.<PROJECT>.supabase.co:5432/postgres?sslmode=require',
    'Worker service (Railway SUPABASE_DB_URL)'
UNION ALL
SELECT 'dragonfly_readonly',
    'postgresql://dragonfly_readonly:<PASSWORD>@db.<PROJECT>.supabase.co:5432/postgres?sslmode=require',
    'Dashboard direct queries (if needed)';
-- ============================================================================
-- END OF VERIFICATION SCRIPT
-- ============================================================================