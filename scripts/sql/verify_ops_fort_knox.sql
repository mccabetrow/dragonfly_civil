-- =============================================================================
-- verify_ops_fort_knox.sql
-- Verification Query Pack for ops Schema Fort Knox Security
-- =============================================================================
--
-- Run this after applying 20260116120000_ops_fort_knox.sql to verify lockdown
-- All queries should return expected results as noted in comments
--
-- =============================================================================
-- =============================================================================
-- CHECK 1: Schema Privileges (CRITICAL)
-- Expected: anon_usage=FALSE, auth_usage=FALSE, service_usage=TRUE
-- =============================================================================
SELECT '1. Schema Privileges' AS check_name,
    nspname AS schema,
    has_schema_privilege('anon', nspname, 'USAGE') AS anon_usage,
    has_schema_privilege('authenticated', nspname, 'USAGE') AS auth_usage,
    has_schema_privilege('service_role', nspname, 'USAGE') AS service_usage,
    CASE
        WHEN has_schema_privilege('anon', nspname, 'USAGE') THEN '❌ FAIL: anon has access'
        WHEN has_schema_privilege('authenticated', nspname, 'USAGE') THEN '❌ FAIL: authenticated has access'
        WHEN NOT has_schema_privilege('service_role', nspname, 'USAGE') THEN '❌ FAIL: service_role lost access'
        ELSE '✅ PASS'
    END AS result
FROM pg_namespace
WHERE nspname = 'ops';
-- =============================================================================
-- CHECK 2: Table Grants to anon/authenticated (CRITICAL)
-- Expected: No rows
-- =============================================================================
SELECT '2. Table Grants' AS check_name,
    schemaname || '.' || tablename AS table_name,
    privilege_type,
    grantee,
    '❌ FAIL: Unauthorized grant' AS result
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
    AND grantee IN ('anon', 'authenticated', 'PUBLIC')
ORDER BY tablename,
    grantee;
-- =============================================================================
-- CHECK 3: View Grants to anon/authenticated
-- Expected: No rows
-- =============================================================================
SELECT '3. View Grants' AS check_name,
    table_schema || '.' || table_name AS view_name,
    privilege_type,
    grantee,
    '❌ FAIL: Unauthorized grant' AS result
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
    AND grantee IN ('anon', 'authenticated', 'PUBLIC')
    AND table_name IN (
        SELECT viewname
        FROM pg_views
        WHERE schemaname = 'ops'
    )
ORDER BY table_name,
    grantee;
-- =============================================================================
-- CHECK 4: Function Grants to anon/authenticated (CRITICAL)
-- Expected: No rows (except explicitly allowed functions)
-- =============================================================================
SELECT '4. Function Grants' AS check_name,
    n.nspname || '.' || p.proname AS function_name,
    r.rolname AS grantee,
    '❌ FAIL: Unauthorized execute' AS result
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    JOIN pg_roles r ON has_function_privilege(r.oid, p.oid, 'EXECUTE')
WHERE n.nspname = 'ops'
    AND r.rolname IN ('anon', 'authenticated') -- Exclude explicitly allowed public functions (if any)
    AND p.proname NOT IN ('get_system_contract_hash') -- Example: contract hash is public
ORDER BY p.proname,
    r.rolname;
-- =============================================================================
-- CHECK 5: SECURITY DEFINER Functions Without search_path (CRITICAL)
-- Expected: No rows
-- =============================================================================
SELECT '5. SECURITY DEFINER search_path' AS check_name,
    n.nspname || '.' || p.proname AS function_name,
    'SECURITY DEFINER' AS security_type,
    CASE
        WHEN p.proconfig IS NULL THEN 'MISSING'
        ELSE array_to_string(p.proconfig, ', ')
    END AS config,
    CASE
        WHEN p.proconfig IS NULL THEN '❌ FAIL: No search_path'
        WHEN NOT EXISTS (
            SELECT 1
            FROM unnest(p.proconfig) cfg
            WHERE cfg LIKE 'search_path=%'
        ) THEN '❌ FAIL: search_path not set'
        ELSE '✅ PASS'
    END AS result
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'ops'
    AND p.prosecdef = TRUE
ORDER BY p.proname;
-- =============================================================================
-- CHECK 6: Sequence Grants to anon/authenticated
-- Expected: No rows
-- =============================================================================
SELECT '6. Sequence Grants' AS check_name,
    schemaname || '.' || sequencename AS sequence_name,
    has_sequence_privilege(
        'anon',
        schemaname || '.' || sequencename,
        'USAGE'
    ) AS anon_usage,
    has_sequence_privilege(
        'authenticated',
        schemaname || '.' || sequencename,
        'USAGE'
    ) AS auth_usage,
    CASE
        WHEN has_sequence_privilege(
            'anon',
            schemaname || '.' || sequencename,
            'USAGE'
        ) THEN '❌ FAIL'
        WHEN has_sequence_privilege(
            'authenticated',
            schemaname || '.' || sequencename,
            'USAGE'
        ) THEN '❌ FAIL'
        ELSE '✅ PASS'
    END AS result
FROM pg_sequences
WHERE schemaname = 'ops'
ORDER BY sequencename;
-- =============================================================================
-- CHECK 7: Cross-Schema SECURITY DEFINER Functions Referencing ops
-- Expected: All should have search_path set
-- =============================================================================
SELECT '7. Cross-Schema SECURITY DEFINER' AS check_name,
    n.nspname || '.' || p.proname AS function_name,
    CASE
        WHEN p.proconfig IS NULL THEN 'MISSING'
        ELSE array_to_string(p.proconfig, ', ')
    END AS config,
    CASE
        WHEN p.proconfig IS NULL THEN '⚠️ WARNING: No config'
        WHEN NOT EXISTS (
            SELECT 1
            FROM unnest(p.proconfig) cfg
            WHERE cfg LIKE 'search_path=%'
        ) THEN '⚠️ WARNING: search_path not set'
        ELSE '✅ PASS'
    END AS result
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname IN ('public', 'ingest', 'intake', 'enforcement')
    AND p.prosecdef = TRUE
    AND pg_get_functiondef(p.oid) ILIKE '%ops.%'
ORDER BY n.nspname,
    p.proname;
-- =============================================================================
-- CHECK 8: PostgREST Exposure Check
-- Expected: ops schema should NOT be in exposed_schemas
-- =============================================================================
SELECT '8. PostgREST Exposure' AS check_name,
    'ops' AS schema,
    CASE
        WHEN EXISTS (
            SELECT 1
            FROM pg_settings
            WHERE name = 'pgrst.db_schemas'
                AND setting LIKE '%ops%'
        ) THEN '⚠️ WARNING: ops in pgrst.db_schemas'
        ELSE '✅ PASS: ops not in pgrst.db_schemas (default)'
    END AS result;
-- =============================================================================
-- CHECK 9: Summary Statistics
-- =============================================================================
SELECT '9. Summary' AS check_name,
    (
        SELECT COUNT(*)
        FROM pg_tables
        WHERE schemaname = 'ops'
    ) AS table_count,
    (
        SELECT COUNT(*)
        FROM pg_views
        WHERE schemaname = 'ops'
    ) AS view_count,
    (
        SELECT COUNT(*)
        FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'ops'
    ) AS function_count,
    (
        SELECT COUNT(*)
        FROM pg_sequences
        WHERE schemaname = 'ops'
    ) AS sequence_count,
    (
        SELECT COUNT(*)
        FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
        WHERE n.nspname = 'ops'
            AND p.prosecdef = TRUE
    ) AS security_definer_count;
-- =============================================================================
-- CHECK 10: Full Audit Report
-- =============================================================================
WITH security_summary AS (
    SELECT 'anon' AS role_name,
        has_schema_privilege('anon', 'ops', 'USAGE') AS has_usage
    UNION ALL
    SELECT 'authenticated',
        has_schema_privilege('authenticated', 'ops', 'USAGE')
    UNION ALL
    SELECT 'service_role',
        has_schema_privilege('service_role', 'ops', 'USAGE')
),
definer_summary AS (
    SELECT COUNT(*) FILTER (
            WHERE p.prosecdef = TRUE
        ) AS total_definer,
        COUNT(*) FILTER (
            WHERE p.prosecdef = TRUE
                AND p.proconfig IS NOT NULL
                AND EXISTS (
                    SELECT 1
                    FROM unnest(p.proconfig) cfg
                    WHERE cfg LIKE 'search_path=%'
                )
        ) AS locked_definer
    FROM pg_proc p
        JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'ops'
)
SELECT '10. FORT KNOX AUDIT REPORT' AS check_name,
    CASE
        WHEN (
            SELECT bool_and(NOT has_usage)
            FROM security_summary
            WHERE role_name IN ('anon', 'authenticated')
        )
        AND (
            SELECT has_usage
            FROM security_summary
            WHERE role_name = 'service_role'
        )
        AND (
            SELECT total_definer = locked_definer
            FROM definer_summary
        ) THEN '✅ FORT KNOX SECURITY: VERIFIED'
        ELSE '❌ SECURITY GAPS DETECTED - Review above checks'
    END AS overall_result,
    now() AS verified_at;
-- =============================================================================
-- CURL TEST PLAN (Public Internet)
-- =============================================================================
/*
 Execute these curl commands from outside your network to verify public API is blocked:
 
 # Test 1: Direct table access via anon key
 curl -s -o /dev/null -w "%{http_code}" \
 -X GET "https://<PROJECT_REF>.supabase.co/rest/v1/job_queue?select=id&limit=1" \
 -H "apikey: <ANON_KEY>" \
 -H "Accept-Profile: ops"
 # Expected: 400 or 406 (schema not exposed)
 
 # Test 2: RPC access via anon key  
 curl -s -o /dev/null -w "%{http_code}" \
 -X POST "https://<PROJECT_REF>.supabase.co/rest/v1/rpc/get_system_health" \
 -H "apikey: <ANON_KEY>" \
 -H "Content-Type: application/json" \
 -H "Accept-Profile: ops"
 # Expected: 400 or 401 (unauthorized)
 
 # Test 3: Table access via authenticated (fake JWT)
 curl -s -o /dev/null -w "%{http_code}" \
 -X GET "https://<PROJECT_REF>.supabase.co/rest/v1/system_health?select=*" \
 -H "apikey: <ANON_KEY>" \
 -H "Authorization: Bearer <FAKE_USER_JWT>" \
 -H "Accept-Profile: ops"  
 # Expected: 400 or 403 (forbidden)
 
 # Test 4: service_role access (should work)
 curl -s -w "%{http_code}" \
 -X POST "https://<PROJECT_REF>.supabase.co/rest/v1/rpc/get_system_health" \
 -H "apikey: <SERVICE_ROLE_KEY>" \
 -H "Authorization: Bearer <SERVICE_ROLE_KEY>" \
 -H "Content-Type: application/json" \
 -H "Accept-Profile: ops"
 # Expected: 200 with JSON response
 */