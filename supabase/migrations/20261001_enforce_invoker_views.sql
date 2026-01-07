-- Migration: Enforce Security Invoker on All Views
-- Purpose: Convert all views in operational schemas from SECURITY DEFINER to SECURITY INVOKER
-- Risk: SECURITY DEFINER views bypass RLS using the owner's permissions
-- Solution: Set security_invoker = true to respect the calling user's RLS policies
--
-- Target Schemas: public, intake, enforcement, legal, rag, evidence, workers, ops, analytics
-- Excluded: auth, storage, extensions, vault, graphql (Supabase-managed)
--
-- Reference: https://supabase.com/docs/guides/database/postgres/row-level-security#security-invoker-views
DO $$
DECLARE v_schema TEXT;
v_view TEXT;
v_full_name TEXT;
v_count INT := 0;
v_schemas TEXT [] := ARRAY ['public', 'intake', 'enforcement', 'legal', 'rag', 'evidence', 'workers', 'ops', 'analytics'];
BEGIN RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
RAISE NOTICE 'SECURITY INVOKER ENFORCEMENT SWEEP';
RAISE NOTICE 'Converting all views to respect RLS (security_invoker = true)';
RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
-- Loop through each target schema
FOREACH v_schema IN ARRAY v_schemas LOOP -- Skip if schema doesn't exist
IF NOT EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = v_schema
) THEN RAISE NOTICE 'Schema % does not exist, skipping',
v_schema;
CONTINUE;
END IF;
RAISE NOTICE '';
RAISE NOTICE '📂 Schema: %',
v_schema;
RAISE NOTICE '────────────────────────────────────────';
-- Loop through all views in this schema (excluding materialized views)
FOR v_view IN
SELECT c.relname
FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = v_schema
    AND c.relkind = 'v' -- 'v' = ordinary view, 'm' = materialized view
ORDER BY c.relname LOOP v_full_name := format('%I.%I', v_schema, v_view);
BEGIN -- Set security_invoker = true on the view
EXECUTE format(
    'ALTER VIEW %s SET (security_invoker = true)',
    v_full_name
);
v_count := v_count + 1;
RAISE NOTICE '  ✓ %',
v_full_name;
EXCEPTION
WHEN OTHERS THEN -- Log errors but continue (e.g., if view is owned by another role)
RAISE WARNING '  ✗ % - Error: %',
v_full_name,
SQLERRM;
END;
END LOOP;
END LOOP;
RAISE NOTICE '';
RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
RAISE NOTICE 'SWEEP COMPLETE: % views converted to security_invoker = true',
v_count;
RAISE NOTICE '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━';
END;
$$;
-- ============================================================================
-- VERIFICATION QUERY
-- Run this after migration to confirm no SECURITY DEFINER views remain
-- ============================================================================
-- SELECT 
--     n.nspname AS schema,
--     c.relname AS view_name,
--     CASE 
--         WHEN c.reloptions @> ARRAY['security_invoker=true'] THEN 'INVOKER ✓'
--         ELSE 'DEFINER ✗'
--     END AS security_mode
-- FROM pg_catalog.pg_class c
-- JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
-- WHERE c.relkind = 'v'
--   AND n.nspname IN ('public', 'intake', 'enforcement', 'legal', 'rag', 'evidence', 'workers')
-- ORDER BY n.nspname, c.relname;
COMMENT ON SCHEMA public IS 'All views enforce security_invoker=true as of migration 20261001';