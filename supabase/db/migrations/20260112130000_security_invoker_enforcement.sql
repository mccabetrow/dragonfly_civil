-- =============================================================================
-- 20260112_security_invoker_enforcement.sql
-- Canonical security_invoker enforcement - FULLY IDEMPOTENT
-- =============================================================================
--
-- DESIGN PRINCIPLES:
-- 1. Every statement is rerunnable without errors
-- 2. All RAISE NOTICE and pg_notify wrapped in DO blocks
-- 3. Forces SECURITY INVOKER on public schema functions
-- 4. Creates audit log function for compliance
-- 5. Sets search_path restrictions on existing functions
--
-- This migration enforces Supabase best practices:
-- - SECURITY INVOKER is the safe default for public functions
-- - Explicit search_path prevents privilege escalation
-- - Audit trail for function security changes
--
-- Safe to run on fresh database OR existing database with partial state.
--
-- =============================================================================
begin;
-- ===========================================================================
-- STEP 1: Create security audit tracking table
-- ===========================================================================
create table if not exists public.function_security_audit (
    id uuid primary key default gen_random_uuid(),
    function_schema text not null,
    function_name text not null,
    old_security text,
    new_security text,
    old_search_path text,
    new_search_path text,
    changed_at timestamptz not null default now(),
    changed_by text default current_user
);
create index if not exists idx_function_security_audit_time on public.function_security_audit (changed_at desc);
comment on table public.function_security_audit is 'Audit trail for function security attribute changes during migrations.';
-- Enable RLS
alter table public.function_security_audit enable row level security;
alter table public.function_security_audit force row level security;
-- Service role only
drop policy if exists function_security_audit_service_role on public.function_security_audit;
create policy function_security_audit_service_role on public.function_security_audit for all to service_role using (true) with check (true);
do $$ BEGIN RAISE NOTICE '✓ Created function_security_audit table';
END $$;
-- ===========================================================================
-- STEP 2: Function to enforce SECURITY INVOKER on a function
-- ===========================================================================
create or replace function public.enforce_security_invoker(
    p_schema_name text,
    p_function_name text,
    p_arg_types text default ''
) returns boolean language plpgsql security definer
set search_path = public as $$
DECLARE v_full_name text;
v_current_security text;
v_current_path text;
BEGIN -- Build fully qualified name
IF p_arg_types = '' THEN v_full_name := format('%I.%I()', p_schema_name, p_function_name);
ELSE v_full_name := format(
    '%I.%I(%s)',
    p_schema_name,
    p_function_name,
    p_arg_types
);
END IF;
-- Get current security type
SELECT CASE
        WHEN p.prosecdef THEN 'DEFINER'
        ELSE 'INVOKER'
    END,
    COALESCE(p.proconfig, ARRAY []::text [])::text INTO v_current_security,
    v_current_path
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = p_schema_name
    AND p.proname = p_function_name
LIMIT 1;
IF NOT FOUND THEN RAISE WARNING 'Function % not found',
v_full_name;
RETURN false;
END IF;
-- Skip if already SECURITY INVOKER
IF v_current_security = 'INVOKER' THEN RETURN true;
END IF;
-- Log the change
INSERT INTO public.function_security_audit (
        function_schema,
        function_name,
        old_security,
        new_security,
        old_search_path,
        new_search_path
    )
VALUES (
        p_schema_name,
        p_function_name,
        v_current_security,
        'INVOKER',
        v_current_path,
        'search_path=public'
    );
-- Alter to SECURITY INVOKER
EXECUTE format(
    'ALTER FUNCTION %s SECURITY INVOKER',
    v_full_name
);
EXECUTE format(
    'ALTER FUNCTION %s SET search_path = public',
    v_full_name
);
RAISE NOTICE '✓ Enforced SECURITY INVOKER on %',
v_full_name;
RETURN true;
END;
$$;
revoke all on function public.enforce_security_invoker(text, text, text)
from public;
grant execute on function public.enforce_security_invoker(text, text, text) to service_role;
comment on function public.enforce_security_invoker is 'Enforce SECURITY INVOKER and explicit search_path on a function. Logs changes to audit table.';
-- ===========================================================================
-- STEP 3: Function to bulk-enforce on all public schema functions
-- ===========================================================================
create or replace function public.enforce_security_invoker_all() returns table (
    function_name text,
    was_definer boolean,
    status text
) language plpgsql security definer
set search_path = public as $$
DECLARE v_rec record;
v_success boolean;
BEGIN FOR v_rec IN
SELECT n.nspname AS schema_name,
    p.proname AS func_name,
    p.prosecdef AS is_definer,
    pg_get_function_identity_arguments(p.oid) AS arg_types
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
    AND p.prokind = 'f'
    AND p.prosecdef = true -- Only SECURITY DEFINER functions
    -- Exclude system functions
    AND p.proname NOT LIKE 'pg_%'
    AND p.proname NOT LIKE '_pg_%' LOOP function_name := v_rec.func_name;
was_definer := v_rec.is_definer;
BEGIN v_success := public.enforce_security_invoker(
    v_rec.schema_name,
    v_rec.func_name,
    v_rec.arg_types
);
status := CASE
    WHEN v_success THEN 'converted'
    ELSE 'skipped'
END;
EXCEPTION
WHEN OTHERS THEN status := 'error: ' || SQLERRM;
END;
RETURN NEXT;
END LOOP;
END;
$$;
revoke all on function public.enforce_security_invoker_all()
from public;
grant execute on function public.enforce_security_invoker_all() to service_role;
comment on function public.enforce_security_invoker_all is 'Bulk-convert all SECURITY DEFINER functions in public schema to SECURITY INVOKER.';
-- ===========================================================================
-- STEP 4: Whitelist of functions that MUST remain SECURITY DEFINER
-- ===========================================================================
-- These are approved exceptions that require elevated privileges:
-- 1. Functions that cross schema boundaries safely
-- 2. Functions with explicit audit logging
-- 3. Functions used by RLS policies
create table if not exists public.security_definer_whitelist (
    id uuid primary key default gen_random_uuid(),
    function_schema text not null,
    function_name text not null,
    reason text not null,
    approved_by text not null,
    approved_at timestamptz not null default now(),
    constraint unique_whitelist_entry unique (function_schema, function_name)
);
comment on table public.security_definer_whitelist is 'Approved exceptions for SECURITY DEFINER functions. Requires documented reason.';
-- Seed with known required exceptions
insert into public.security_definer_whitelist (
    function_schema,
    function_name,
    reason,
    approved_by
)
values (
    'ops',
    'get_system_health',
    'Dashboard RPC - reads from locked ops schema',
    'migration'
),
(
    'ops',
    'get_worker_status',
    'Dashboard RPC - reads from locked ops schema',
    'migration'
),
(
    'ops',
    'get_dashboard_stats_json',
    'Dashboard RPC - aggregates from ops + public',
    'migration'
),
(
    'ops',
    'get_recent_audit_events',
    'Dashboard RPC - reads audit log',
    'migration'
),
(
    'ingest',
    'claim_stale_job',
    'Worker RPC - updates locked ingest schema',
    'migration'
),
(
    'public',
    'enforce_security_invoker',
    'Meta-function for security enforcement',
    'migration'
),
(
    'public',
    'enforce_security_invoker_all',
    'Meta-function for bulk enforcement',
    'migration'
) on conflict (function_schema, function_name) do nothing;
do $$ BEGIN RAISE NOTICE '✓ Seeded security_definer_whitelist with approved exceptions';
END $$;
-- ===========================================================================
-- STEP 5: Verification function - check for unwhitelisted SECURITY DEFINER
-- ===========================================================================
create or replace function public.check_security_definer_compliance() returns table (
    schema_name text,
    function_name text,
    is_definer boolean,
    is_whitelisted boolean,
    search_path text,
    compliance_status text
) language plpgsql security invoker
set search_path = public as $$ BEGIN RETURN QUERY
SELECT n.nspname::text AS schema_name,
    p.proname::text AS function_name,
    p.prosecdef AS is_definer,
    (w.id IS NOT NULL) AS is_whitelisted,
    COALESCE(
        (
            SELECT string_agg(c, ', ')
            FROM unnest(p.proconfig) AS c
            WHERE c LIKE 'search_path=%'
        ),
        'not set'
    ) AS search_path,
    CASE
        WHEN NOT p.prosecdef THEN 'compliant'
        WHEN w.id IS NOT NULL THEN 'whitelisted'
        ELSE 'VIOLATION'
    END AS compliance_status
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    LEFT JOIN public.security_definer_whitelist w ON w.function_schema = n.nspname
    AND w.function_name = p.proname
WHERE n.nspname IN ('public', 'ops', 'ingest')
    AND p.prokind = 'f'
    AND p.proname NOT LIKE 'pg_%'
ORDER BY CASE
        WHEN p.prosecdef
        AND w.id IS NULL THEN 0
        ELSE 1
    END,
    n.nspname,
    p.proname;
END;
$$;
grant execute on function public.check_security_definer_compliance() to service_role;
grant execute on function public.check_security_definer_compliance() to authenticated;
comment on function public.check_security_definer_compliance is 'Audit function to check for SECURITY DEFINER violations.';
-- ===========================================================================
-- STEP 6: Set search_path on existing public functions (idempotent)
-- ===========================================================================
do $$
DECLARE v_func record;
v_full_name text;
BEGIN FOR v_func IN
SELECT n.nspname AS schema_name,
    p.proname AS func_name,
    pg_get_function_identity_arguments(p.oid) AS arg_types
FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE n.nspname = 'public'
    AND p.prokind = 'f'
    AND p.proname NOT LIKE 'pg_%'
    AND NOT EXISTS (
        SELECT 1
        FROM unnest(p.proconfig) AS c
        WHERE c LIKE 'search_path=%'
    ) LOOP IF v_func.arg_types = '' THEN v_full_name := format('%I.%I()', v_func.schema_name, v_func.func_name);
ELSE v_full_name := format(
    '%I.%I(%s)',
    v_func.schema_name,
    v_func.func_name,
    v_func.arg_types
);
END IF;
BEGIN EXECUTE format(
    'ALTER FUNCTION %s SET search_path = public',
    v_full_name
);
RAISE NOTICE '✓ Set search_path on %',
v_full_name;
EXCEPTION
WHEN OTHERS THEN RAISE WARNING '⚠ Could not set search_path on %: %',
v_full_name,
SQLERRM;
END;
END LOOP;
END $$;
-- ===========================================================================
-- STEP 7: Reload PostgREST schema cache
-- ===========================================================================
do $$ BEGIN PERFORM pg_notify('pgrst', 'reload schema');
RAISE NOTICE '✓ Notified PostgREST to reload schema cache';
END $$;
do $$ BEGIN RAISE NOTICE '✓ security_invoker enforcement complete';
RAISE NOTICE '  - Audit table: public.function_security_audit';
RAISE NOTICE '  - Whitelist table: public.security_definer_whitelist';
RAISE NOTICE '  - Compliance check: SELECT * FROM check_security_definer_compliance()';
END $$;
commit;
-- ===========================================================================
-- VERIFICATION QUERIES (run after migration)
-- ===========================================================================
/*
 -- Check for SECURITY DEFINER violations
 SELECT * FROM public.check_security_definer_compliance()
 WHERE compliance_status = 'VIOLATION';

 -- View whitelist
 SELECT * FROM public.security_definer_whitelist;

 -- View audit log
 SELECT * FROM public.function_security_audit ORDER BY changed_at DESC;

 -- Check search_path on functions
 SELECT
 n.nspname,
 p.proname,
 p.prosecdef,
 array_to_string(p.proconfig, ', ') AS config
 FROM pg_proc p
 JOIN pg_namespace n ON n.oid = p.pronamespace
 WHERE n.nspname IN ('public', 'ops', 'ingest')
 AND p.prokind = 'f'
 ORDER BY n.nspname, p.proname;
 */
-- ===========================================================================
