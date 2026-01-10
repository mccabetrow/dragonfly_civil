-- 20261102_verify_view_security.sql
-- Cache Clear & Security Verification Script
-- Purpose: Force PostgREST schema reload and audit all views for security_invoker
-- Run in: Supabase SQL Editor (both dev and prod)
-- ===========================================================================
-- STEP 1: Force PostgREST Schema Cache Reload
-- ===========================================================================
-- This notifies PostgREST to refresh its schema understanding.
-- Any "stale" security warnings should clear after this.
NOTIFY pgrst,
'reload schema';
-- Give PostgREST a moment to process
SELECT pg_sleep(0.5);
DO $$ BEGIN RAISE NOTICE '🔄 PostgREST schema cache reload requested';
END $$;
-- ===========================================================================
-- STEP 2: The "Truth Serum" Audit
-- ===========================================================================
-- Inspects pg_class to find ALL views in our active schemas
-- and identifies any that are NOT marked with security_invoker=true.
DO $$
DECLARE insecure_count INTEGER;
v_record RECORD;
BEGIN RAISE NOTICE '';
RAISE NOTICE '══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  DRAGONFLY VIEW SECURITY AUDIT';
RAISE NOTICE '══════════════════════════════════════════════════════════════════';
RAISE NOTICE '';
-- Count insecure views
SELECT COUNT(*) INTO insecure_count
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v' -- Views only
    AND n.nspname IN (
        'public',
        'intake',
        'enforcement',
        'legal',
        'rag',
        'evidence',
        'workers',
        'ops',
        'ingest',
        'analytics'
    )
    AND (
        c.reloptions IS NULL
        OR NOT (
            c.reloptions::text [] @> ARRAY ['security_invoker=true']
        )
    );
IF insecure_count = 0 THEN RAISE NOTICE '✅ SUCCESS: All views are secure (security_invoker=true)';
RAISE NOTICE '   The Supabase Security Advisor warning is stale cache.';
RAISE NOTICE '';
ELSE RAISE WARNING '⚠️  FOUND % VIEW(S) WITHOUT security_invoker=true:',
insecure_count;
RAISE NOTICE '';
FOR v_record IN
SELECT n.nspname AS schema_name,
    c.relname AS view_name,
    COALESCE(c.reloptions::text, 'NULL') AS current_options
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v'
    AND n.nspname IN (
        'public',
        'intake',
        'enforcement',
        'legal',
        'rag',
        'evidence',
        'workers',
        'ops',
        'ingest',
        'analytics'
    )
    AND (
        c.reloptions IS NULL
        OR NOT (
            c.reloptions::text [] @> ARRAY ['security_invoker=true']
        )
    )
ORDER BY n.nspname,
    c.relname LOOP RAISE NOTICE '   ❌ %.% (options: %)',
    v_record.schema_name,
    v_record.view_name,
    v_record.current_options;
END LOOP;
RAISE NOTICE '';
RAISE NOTICE '   Run STEP 3 (Auto-Fixer) to remediate automatically.';
END IF;
RAISE NOTICE '';
RAISE NOTICE '══════════════════════════════════════════════════════════════════';
END;
$$;
-- ===========================================================================
-- STEP 2B: Query-based Audit (for copy-paste verification)
-- ===========================================================================
-- This SELECT returns the actual list of insecure views for inspection.
-- Useful for manual review or exporting results.
SELECT n.nspname AS schema_name,
    c.relname AS view_name,
    CASE
        WHEN c.reloptions IS NULL THEN 'NO OPTIONS SET'
        WHEN c.reloptions::text [] @> ARRAY ['security_invoker=true'] THEN '✅ SECURE'
        ELSE c.reloptions::text
    END AS security_status,
    pg_get_userbyid(c.relowner) AS owner
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v'
    AND n.nspname IN (
        'public',
        'intake',
        'enforcement',
        'legal',
        'rag',
        'evidence',
        'workers',
        'ops',
        'ingest',
        'analytics'
    )
    AND (
        c.reloptions IS NULL
        OR NOT (
            c.reloptions::text [] @> ARRAY ['security_invoker=true']
        )
    )
ORDER BY n.nspname,
    c.relname;
-- ===========================================================================
-- STEP 3: The Auto-Fixer (Safety Net)
-- ===========================================================================
-- This block automatically fixes any remaining insecure views.
-- UNCOMMENT AND RUN ONLY IF STEP 2 FOUND ISSUES.
/*
 DO $$
 DECLARE
 v_record RECORD;
 v_sql TEXT;
 v_fixed_count INTEGER := 0;
 BEGIN
 RAISE NOTICE '';
 RAISE NOTICE '══════════════════════════════════════════════════════════════════';
 RAISE NOTICE '  AUTO-FIXING INSECURE VIEWS';
 RAISE NOTICE '══════════════════════════════════════════════════════════════════';
 RAISE NOTICE '';
 
 FOR v_record IN
 SELECT
 n.nspname AS schema_name,
 c.relname AS view_name
 FROM pg_class c
 JOIN pg_namespace n ON n.oid = c.relnamespace
 WHERE c.relkind = 'v'
 AND n.nspname IN ('public', 'intake', 'enforcement', 'legal', 'rag', 'evidence', 'workers', 'ops', 'ingest', 'analytics')
 AND (
 c.reloptions IS NULL
 OR NOT (c.reloptions::text[] @> ARRAY['security_invoker=true'])
 )
 ORDER BY n.nspname, c.relname
 LOOP
 v_sql := format(
 'ALTER VIEW %I.%I SET (security_invoker = true)',
 v_record.schema_name,
 v_record.view_name
 );
 
 BEGIN
 EXECUTE v_sql;
 RAISE NOTICE '   ✅ Fixed: %.%', v_record.schema_name, v_record.view_name;
 v_fixed_count := v_fixed_count + 1;
 EXCEPTION WHEN OTHERS THEN
 RAISE WARNING '   ❌ Failed to fix %.%: %', v_record.schema_name, v_record.view_name, SQLERRM;
 END;
 END LOOP;
 
 RAISE NOTICE '';
 IF v_fixed_count > 0 THEN
 RAISE NOTICE '🔧 Fixed % view(s). Requesting PostgREST reload...', v_fixed_count;
 NOTIFY pgrst, 'reload schema';
 RAISE NOTICE '✅ Schema cache reload requested.';
 ELSE
 RAISE NOTICE '✅ No views needed fixing.';
 END IF;
 
 RAISE NOTICE '';
 RAISE NOTICE '══════════════════════════════════════════════════════════════════';
 END;
 $$;
 */
-- ===========================================================================
-- STEP 4: Verification Summary
-- ===========================================================================
-- Quick summary of all views and their security status
SELECT n.nspname AS schema_name,
    COUNT(*) FILTER (
        WHERE c.reloptions::text [] @> ARRAY ['security_invoker=true']
    ) AS secure_views,
    COUNT(*) FILTER (
        WHERE c.reloptions IS NULL
            OR NOT (
                c.reloptions::text [] @> ARRAY ['security_invoker=true']
            )
    ) AS insecure_views,
    COUNT(*) AS total_views
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v'
    AND n.nspname IN (
        'public',
        'intake',
        'enforcement',
        'legal',
        'rag',
        'evidence',
        'workers',
        'ops',
        'ingest',
        'analytics'
    )
GROUP BY n.nspname
ORDER BY n.nspname;
-- ===========================================================================
-- FINAL: Force another cache reload after any changes
-- ===========================================================================
NOTIFY pgrst,
'reload schema';
DO $$ BEGIN RAISE NOTICE '';
RAISE NOTICE '🏁 Audit complete. Check the results above.';
RAISE NOTICE '   If insecure_views = 0 for all schemas, the Security Advisor is stale.';
RAISE NOTICE '   Refresh the Supabase Dashboard to clear the cached warnings.';
END;
$$;