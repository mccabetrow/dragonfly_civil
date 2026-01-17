-- =============================================================================
-- 20260112_002_security_invoker_views.sql
-- Enforce security_invoker=true on all ordinary views in specified schemas
-- =============================================================================
--
-- DESIGN PRINCIPLES:
-- 1. Fully idempotent - uses pg_catalog checks before any ALTER
-- 2. Only modifies views that don't already have security_invoker=true
-- 3. Handles views in public, ingest schemas
-- 4. Creates audit trail for compliance
-- 5. No assumptions about specific view names
--
-- PostgreSQL 15+ supports security_invoker on views (Supabase default)
--
-- =============================================================================
BEGIN;
-- ===========================================================================
-- STEP 1: Create tracking table for view security changes
-- ===========================================================================
CREATE TABLE IF NOT EXISTS public.view_security_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    view_schema text NOT NULL,
    view_name text NOT NULL,
    old_security_invoker boolean,
    new_security_invoker boolean,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text DEFAULT current_user
);
CREATE INDEX IF NOT EXISTS idx_view_security_audit_time ON public.view_security_audit (changed_at DESC);
COMMENT ON TABLE public.view_security_audit IS 'Audit trail for view security_invoker changes during migrations.';
-- RLS on audit table
ALTER TABLE public.view_security_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.view_security_audit FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS view_security_audit_service_role ON public.view_security_audit;
CREATE POLICY view_security_audit_service_role ON public.view_security_audit FOR ALL TO service_role USING (true) WITH CHECK (true);
DO $$ BEGIN RAISE NOTICE '✓ Created view_security_audit table';
END $$;
-- ===========================================================================
-- STEP 2: Function to check if security_invoker is already true
-- ===========================================================================
-- Note: pg_class.relowner and reloptions contain security_invoker setting
-- In PG15+, views have security_invoker option
CREATE OR REPLACE FUNCTION public.get_view_security_invoker(p_schema text, p_view text) RETURNS boolean LANGUAGE plpgsql SECURITY INVOKER
SET search_path = pg_catalog,
    public AS $$
DECLARE v_reloptions text [];
v_option text;
BEGIN
SELECT c.reloptions INTO v_reloptions
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = p_schema
    AND c.relname = p_view
    AND c.relkind = 'v';
IF v_reloptions IS NULL THEN -- No options set, security_invoker defaults to false
RETURN false;
END IF;
FOREACH v_option IN ARRAY v_reloptions LOOP IF v_option = 'security_invoker=true'
OR v_option = 'security_invoker=1' THEN RETURN true;
END IF;
END LOOP;
RETURN false;
END;
$$;
COMMENT ON FUNCTION public.get_view_security_invoker IS 'Check if a view has security_invoker=true set.';
-- ===========================================================================
-- STEP 3: Function to enforce security_invoker on a single view
-- ===========================================================================
CREATE OR REPLACE FUNCTION public.enforce_view_security_invoker(p_schema text, p_view text) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_catalog AS $$
DECLARE v_current_setting boolean;
v_full_name text;
BEGIN v_full_name := format('%I.%I', p_schema, p_view);
-- Check if view exists
IF NOT EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = p_schema
        AND c.relname = p_view
        AND c.relkind = 'v'
) THEN RAISE WARNING 'View % does not exist',
v_full_name;
RETURN false;
END IF;
-- Check current setting
v_current_setting := public.get_view_security_invoker(p_schema, p_view);
IF v_current_setting THEN -- Already set, skip
RAISE NOTICE '  View % already has security_invoker=true',
v_full_name;
RETURN true;
END IF;
-- Log the change
INSERT INTO public.view_security_audit (
        view_schema,
        view_name,
        old_security_invoker,
        new_security_invoker
    )
VALUES (
        p_schema,
        p_view,
        false,
        true
    );
-- Apply the change
EXECUTE format(
    'ALTER VIEW %s SET (security_invoker = true)',
    v_full_name
);
RAISE NOTICE '✓ Set security_invoker=true on %',
v_full_name;
RETURN true;
EXCEPTION
WHEN OTHERS THEN RAISE WARNING '⚠ Could not set security_invoker on %: %',
v_full_name,
SQLERRM;
RETURN false;
END;
$$;
REVOKE ALL ON FUNCTION public.enforce_view_security_invoker(text, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enforce_view_security_invoker(text, text) TO service_role;
COMMENT ON FUNCTION public.enforce_view_security_invoker IS 'Set security_invoker=true on a view. Logs change to audit table.';
-- ===========================================================================
-- STEP 4: Function to bulk-enforce on all views in specified schemas
-- ===========================================================================
CREATE OR REPLACE FUNCTION public.enforce_view_security_invoker_all(
        p_schemas text [] DEFAULT ARRAY ['public', 'ingest']
    ) RETURNS TABLE (
        schema_name text,
        view_name text,
        was_secure boolean,
        status text
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_catalog AS $$
DECLARE v_rec record;
v_success boolean;
v_schema text;
BEGIN FOREACH v_schema IN ARRAY p_schemas LOOP FOR v_rec IN
SELECT n.nspname AS schema_name,
    c.relname AS view_name,
    public.get_view_security_invoker(n.nspname, c.relname) AS current_setting
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = v_schema
    AND c.relkind = 'v' -- Exclude system views
    AND c.relname NOT LIKE 'pg_%'
    AND c.relname NOT LIKE 'information_schema%'
ORDER BY c.relname LOOP schema_name := v_rec.schema_name;
view_name := v_rec.view_name;
was_secure := v_rec.current_setting;
IF v_rec.current_setting THEN status := 'already_secure';
ELSE BEGIN v_success := public.enforce_view_security_invoker(
    v_rec.schema_name,
    v_rec.view_name
);
status := CASE
    WHEN v_success THEN 'secured'
    ELSE 'failed'
END;
EXCEPTION
WHEN OTHERS THEN status := 'error: ' || SQLERRM;
END;
END IF;
RETURN NEXT;
END LOOP;
END LOOP;
END;
$$;
REVOKE ALL ON FUNCTION public.enforce_view_security_invoker_all(text [])
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.enforce_view_security_invoker_all(text []) TO service_role;
COMMENT ON FUNCTION public.enforce_view_security_invoker_all IS 'Bulk-enforce security_invoker=true on all views in specified schemas.';
-- ===========================================================================
-- STEP 5: Apply to all views in public and ingest schemas
-- ===========================================================================
DO $$
DECLARE v_result record;
v_total integer := 0;
v_secured integer := 0;
BEGIN RAISE NOTICE 'Enforcing security_invoker on views in public and ingest schemas...';
FOR v_result IN
SELECT *
FROM public.enforce_view_security_invoker_all(ARRAY ['public', 'ingest']) LOOP v_total := v_total + 1;
IF v_result.status IN ('secured', 'already_secure') THEN v_secured := v_secured + 1;
END IF;
END LOOP;
RAISE NOTICE '✓ Processed % views, % are now security_invoker=true',
v_total,
v_secured;
END $$;
-- ===========================================================================
-- STEP 6: Create compliance check function
-- ===========================================================================
CREATE OR REPLACE FUNCTION public.check_view_security_compliance(
        p_schemas text [] DEFAULT ARRAY ['public', 'ingest']
    ) RETURNS TABLE (
        schema_name text,
        view_name text,
        has_security_invoker boolean,
        compliance_status text
    ) LANGUAGE plpgsql SECURITY INVOKER
SET search_path = public,
    pg_catalog AS $$
DECLARE v_schema text;
BEGIN FOREACH v_schema IN ARRAY p_schemas LOOP RETURN QUERY
SELECT n.nspname::text AS schema_name,
    c.relname::text AS view_name,
    public.get_view_security_invoker(n.nspname, c.relname) AS has_security_invoker,
    CASE
        WHEN public.get_view_security_invoker(n.nspname, c.relname) THEN 'compliant'
        ELSE 'VIOLATION'
    END AS compliance_status
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = v_schema
    AND c.relkind = 'v'
    AND c.relname NOT LIKE 'pg_%'
ORDER BY CASE
        WHEN public.get_view_security_invoker(n.nspname, c.relname) THEN 1
        ELSE 0
    END,
    c.relname;
END LOOP;
END;
$$;
GRANT EXECUTE ON FUNCTION public.check_view_security_compliance(text []) TO service_role;
GRANT EXECUTE ON FUNCTION public.check_view_security_compliance(text []) TO authenticated;
COMMENT ON FUNCTION public.check_view_security_compliance IS 'Audit function to check for views without security_invoker=true.';
-- ===========================================================================
-- STEP 7: Summary
-- ===========================================================================
DO $$ BEGIN RAISE NOTICE '✓ security_invoker enforcement on views complete';
RAISE NOTICE '  - Audit table: public.view_security_audit';
RAISE NOTICE '  - Compliance check: SELECT * FROM check_view_security_compliance()';
RAISE NOTICE '  - Views without security_invoker may leak row-level security';
END $$;
-- ===========================================================================
-- STEP 8: Reload PostgREST schema cache
-- ===========================================================================
DO $$ BEGIN PERFORM pg_notify('pgrst', 'reload schema');
RAISE NOTICE '✓ Notified PostgREST to reload schema cache';
END $$;
COMMIT;
-- ===========================================================================
-- VERIFICATION (run after migration)
-- ===========================================================================
/*
 -- Check for violations
 SELECT * FROM public.check_view_security_compliance()
 WHERE compliance_status = 'VIOLATION';
 
 -- View audit log
 SELECT * FROM public.view_security_audit ORDER BY changed_at DESC;
 
 -- Check specific view
 SELECT public.get_view_security_invoker('public', 'v_plaintiffs_overview');
 */