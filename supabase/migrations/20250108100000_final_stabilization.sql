-- ============================================================================
-- 20250108_final_stabilization.sql
-- Final Production Stabilization: Permissions, Search Paths, Cache Hardening
-- ============================================================================
-- Purpose:
--   1. Fix view permissions for v_enrichment_health and v_live_feed_events
--   2. Harden function search_path to fix Security Advisor warnings
--   3. Ensure PostgREST can expose views correctly
--
-- Idempotent: Yes - all operations are safe to re-run
-- ============================================================================
BEGIN;
-- ============================================================================
-- SECTION 1: Schema Usage Grants
-- ============================================================================
-- Ensure anon and authenticated can access the public and ops schemas
GRANT USAGE ON SCHEMA public TO anon,
    authenticated;
GRANT USAGE ON SCHEMA ops TO anon,
    authenticated;
-- ============================================================================
-- SECTION 2: View Permissions - Public Schema
-- ============================================================================
-- Grant SELECT on critical views that were returning 503
-- Core dashboard views
GRANT SELECT ON public.v_enrichment_health TO anon,
    authenticated;
GRANT SELECT ON public.v_live_feed_events TO anon,
    authenticated;
GRANT SELECT ON public.v_plaintiffs_overview TO anon,
    authenticated;
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated;
GRANT SELECT ON public.v_enforcement_overview TO anon,
    authenticated;
-- Also grant on ops schema view if it exists
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'ops'
        AND table_name = 'v_enrichment_health'
) THEN EXECUTE 'GRANT SELECT ON ops.v_enrichment_health TO anon, authenticated';
END IF;
END $$;
-- ============================================================================
-- SECTION 3: Function Search Path Hardening
-- ============================================================================
-- Fix "Function Search Path Mutable" Security Advisor warnings
-- Setting search_path prevents search path injection attacks
-- normalize_party_name: Used in judgment deduplication
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
        AND p.proname = 'normalize_party_name'
) THEN ALTER FUNCTION public.normalize_party_name(text)
SET search_path = public,
    pg_temp;
RAISE NOTICE 'Hardened: public.normalize_party_name';
END IF;
END $$;
-- compute_judgment_dedupe_key: Used in judgment deduplication
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
        AND p.proname = 'compute_judgment_dedupe_key'
) THEN ALTER FUNCTION public.compute_judgment_dedupe_key(text, text)
SET search_path = public,
    pg_temp;
RAISE NOTICE 'Hardened: public.compute_judgment_dedupe_key';
END IF;
END $$;
-- upsert_plaintiff: Critical plaintiff management function
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
        AND p.proname = 'upsert_plaintiff'
) THEN -- Check current config
IF NOT EXISTS (
    SELECT 1
    FROM pg_proc p
        JOIN pg_namespace n ON p.pronamespace = n.oid
    WHERE n.nspname = 'public'
        AND p.proname = 'upsert_plaintiff'
        AND p.proconfig IS NOT NULL
        AND 'search_path=public, pg_temp' = ANY(p.proconfig)
) THEN ALTER FUNCTION public.upsert_plaintiff(jsonb)
SET search_path = public,
    pg_temp;
RAISE NOTICE 'Hardened: public.upsert_plaintiff';
END IF;
END IF;
END $$;
-- ============================================================================
-- SECTION 4: Additional Security Hardening
-- ============================================================================
-- Ensure service_role has full access (for backend operations)
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO service_role;
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA ops TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO service_role;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA ops TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO service_role;
-- ============================================================================
-- SECTION 5: PostgREST Schema Cache Notification
-- ============================================================================
-- Force PostgREST to reload its schema cache after permission changes
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- Verification Queries (run manually to confirm)
-- ============================================================================
-- SELECT n.nspname, p.proname, p.proconfig
-- FROM pg_proc p
-- JOIN pg_namespace n ON p.pronamespace = n.oid
-- WHERE p.proname IN ('normalize_party_name', 'compute_judgment_dedupe_key', 'upsert_plaintiff')
-- ORDER BY n.nspname, p.proname;
--
-- SELECT grantee, privilege_type, table_schema, table_name
-- FROM information_schema.table_privileges
-- WHERE table_name IN ('v_enrichment_health', 'v_live_feed_events')
-- ORDER BY table_name, grantee;
