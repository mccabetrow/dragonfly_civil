-- =============================================================================
-- Migration: Security Hardening - Table Grants Lockdown
-- Purpose: Reduce overly-broad grants on core tables to service_role only writes
-- =============================================================================
-- This migration addresses Supabase Security Advisor warnings about:
-- 1. anon/authenticated having write access to core tables
-- 2. Restricted tables (enforcement_*, import_runs) exposed to public roles
--
-- ROLLBACK: See bottom of file for rollback statements
-- VERIFICATION: Run `python -m tools.security_audit --env dev` after applying
-- =============================================================================
BEGIN;
-- =============================================================================
-- 1. JUDGMENTS TABLE - Remove write access from anon/authenticated
-- =============================================================================
-- Violation: judgments: unexpected write privileges for roles ['anon', 'authenticated']
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.judgments
FROM anon;
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.judgments
FROM authenticated;
-- Keep SELECT for dashboard read access (RLS controls visibility)
-- service_role retains full access for workers
-- =============================================================================
-- 2. ENFORCEMENT_CASES TABLE - Lockdown to service_role only
-- =============================================================================
-- Violations:
--   - enforcement_cases: unexpected write privileges for roles ['authenticated']
--   - enforcement_cases: role 'anon' must not have privileges
--   - enforcement_cases: role 'authenticated' must not have privileges
REVOKE ALL ON public.enforcement_cases
FROM anon;
REVOKE ALL ON public.enforcement_cases
FROM authenticated;
-- Grant read-only to authenticated for dashboard (RLS enforces row visibility)
GRANT SELECT ON public.enforcement_cases TO authenticated;
-- =============================================================================
-- 3. ENFORCEMENT_EVENTS TABLE - Lockdown to service_role only
-- =============================================================================
-- Violations:
--   - enforcement_events: role 'anon' must not have privileges
--   - enforcement_events: role 'authenticated' must not have privileges
REVOKE ALL ON public.enforcement_events
FROM anon;
REVOKE ALL ON public.enforcement_events
FROM authenticated;
-- Grant read-only to authenticated for timeline views
GRANT SELECT ON public.enforcement_events TO authenticated;
-- =============================================================================
-- 4. ENFORCEMENT_EVIDENCE TABLE - Lockdown to service_role only
-- =============================================================================
-- Violation: enforcement_evidence: role 'authenticated' must not have privileges
REVOKE ALL ON public.enforcement_evidence
FROM anon;
REVOKE ALL ON public.enforcement_evidence
FROM authenticated;
-- Evidence should be service_role only, no dashboard direct access
-- Views can expose sanitized data via SECURITY DEFINER functions
-- =============================================================================
-- 5. IMPORT_RUNS TABLE - Lockdown to service_role only
-- =============================================================================
-- Violation: import_runs: role 'authenticated' must not have privileges
REVOKE ALL ON public.import_runs
FROM anon;
REVOKE ALL ON public.import_runs
FROM authenticated;
-- Ops metadata - service_role only, dashboard uses views
-- =============================================================================
-- 6. PLAINTIFF_CALL_ATTEMPTS TABLE - Remove write from authenticated
-- =============================================================================
-- Violation: plaintiff_call_attempts: unexpected write privileges for roles ['authenticated']
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.plaintiff_call_attempts
FROM authenticated;
-- Keep SELECT for dashboard visibility
-- =============================================================================
-- 7. PLAINTIFF_TASKS TABLE - Remove write from authenticated
-- =============================================================================
-- Violation: plaintiff_tasks: unexpected write privileges for roles ['authenticated']
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.plaintiff_tasks
FROM authenticated;
-- Keep SELECT for task queue views
-- =============================================================================
-- 8. PLAINTIFFS TABLE - Remove write from authenticated
-- =============================================================================
-- Violation: plaintiffs: unexpected write privileges for roles ['authenticated']
REVOKE
INSERT,
    DELETE ON public.plaintiffs
FROM authenticated;
-- NOTE: Keeping UPDATE for dashboard status changes via RPC wrappers
-- If dashboard should not update plaintiffs directly, also REVOKE UPDATE
COMMIT;
-- =============================================================================
-- ROLLBACK STATEMENTS (run manually if needed)
-- =============================================================================
-- WARNING: Only use these if you need to revert. This reopens security holes.
--
-- GRANT INSERT, UPDATE, DELETE ON public.judgments TO anon;
-- GRANT INSERT, UPDATE, DELETE ON public.judgments TO authenticated;
-- GRANT ALL ON public.enforcement_cases TO anon;
-- GRANT ALL ON public.enforcement_cases TO authenticated;
-- GRANT ALL ON public.enforcement_events TO anon;
-- GRANT ALL ON public.enforcement_events TO authenticated;
-- GRANT ALL ON public.enforcement_evidence TO authenticated;
-- GRANT ALL ON public.import_runs TO authenticated;
-- GRANT INSERT, UPDATE, DELETE ON public.plaintiff_call_attempts TO authenticated;
-- GRANT INSERT, UPDATE, DELETE ON public.plaintiff_tasks TO authenticated;
-- GRANT INSERT, DELETE ON public.plaintiffs TO authenticated;
-- =============================================================================
-- =============================================================================
-- VERIFICATION QUERY - Check grants after migration
-- =============================================================================
-- Run this to verify the changes:
/*
 SELECT 
 table_name,
 grantee,
 string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
 FROM information_schema.table_privileges
 WHERE table_schema = 'public'
 AND table_name IN (
 'judgments', 'enforcement_cases', 'enforcement_events',
 'enforcement_evidence', 'import_runs', 'plaintiff_call_attempts',
 'plaintiff_tasks', 'plaintiffs'
 )
 AND grantee IN ('anon', 'authenticated')
 GROUP BY table_name, grantee
 ORDER BY table_name, grantee;
 */
