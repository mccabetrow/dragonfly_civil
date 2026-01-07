-- Migration: 20260802_ops_lockdown.sql
-- Purpose: Lock down ops schema - deny all public access, grant only to service_role
-- Author: Access Control Engineer
-- Date: 2026-01-07
--
-- Context:
-- The ops schema contains internal dashboards, sensitive metrics, and operational
-- functions (outbox pattern, contract snapshots, system hashes). Supabase Advisor
-- flagged potential exposure to anon/authenticated roles.
--
-- This migration implements a "Deny All" policy:
-- 1. Revokes ALL privileges from anon and authenticated roles
-- 2. Grants full access only to service_role (backend workers, internal APIs)
-- 3. Ensures ops schema is NOT exposed via PostgREST public API
--
-- ┌─────────────────────────────────────────────────────────────────────────────┐
-- │  POSTGREST CONFIGURATION CHECK                                              │
-- │                                                                             │
-- │  After applying this migration, verify your PostgREST/Supabase config:      │
-- │                                                                             │
-- │  1. Supabase Dashboard → Project Settings → API → Schema Settings           │
-- │     Ensure "ops" is NOT in the exposed schemas list.                        │
-- │                                                                             │
-- │  2. If using Railway or self-hosted PostgREST, check PGRST_DB_SCHEMAS:      │
-- │     PGRST_DB_SCHEMAS=public,api  (NOT: public,api,ops)                      │
-- │                                                                             │
-- │  3. For internal-only API instance (ops access via service_role):           │
-- │     - Deploy a separate PostgREST instance with:                            │
-- │       PGRST_DB_SCHEMAS=ops                                                  │
-- │       PGRST_JWT_SECRET=<internal-only-secret>                               │
-- │     - Bind only to internal network (not public internet)                   │
-- │                                                                             │
-- │  The ops schema should NEVER be accessible from client-side applications.   │
-- └─────────────────────────────────────────────────────────────────────────────┘
BEGIN;
DO $banner$ BEGIN RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  OPS SCHEMA LOCKDOWN: Revoking public access';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
END $banner$;
-- =============================================================================
-- PART 1: REVOKE ALL ACCESS FROM PUBLIC ROLES
-- =============================================================================
-- These roles should NEVER have access to operational internals
DO $lockdown$ BEGIN -- -------------------------------------------------------------------------
-- 1.1 Revoke schema-level access
-- -------------------------------------------------------------------------
-- Without USAGE on the schema, roles cannot see or access any objects
REVOKE ALL ON SCHEMA ops
FROM anon,
    authenticated;
RAISE NOTICE '✓ Revoked SCHEMA ops access from anon, authenticated';
-- -------------------------------------------------------------------------
-- 1.2 Revoke table-level access (defense in depth)
-- -------------------------------------------------------------------------
-- Even if schema access were somehow granted, tables remain locked
REVOKE ALL ON ALL TABLES IN SCHEMA ops
FROM anon,
    authenticated;
RAISE NOTICE '✓ Revoked ALL TABLES in ops from anon, authenticated';
-- -------------------------------------------------------------------------
-- 1.3 Revoke function execution (prevents RPC abuse)
-- -------------------------------------------------------------------------
-- Critical: ops functions like claim_outbox_messages must not be callable
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ops
FROM anon,
    authenticated;
RAISE NOTICE '✓ Revoked ALL FUNCTIONS in ops from anon, authenticated';
-- -------------------------------------------------------------------------
-- 1.4 Revoke sequence access (completeness)
-- -------------------------------------------------------------------------
REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops
FROM anon,
    authenticated;
RAISE NOTICE '✓ Revoked ALL SEQUENCES in ops from anon, authenticated';
END $lockdown$;
-- =============================================================================
-- PART 2: GRANT SERVICE ROLE ACCESS
-- =============================================================================
-- service_role is used by backend workers and internal APIs only
DO $service$ BEGIN RAISE NOTICE '';
RAISE NOTICE '───────────────────────────────────────────────────────────────────';
RAISE NOTICE '  Granting service_role access to ops schema';
RAISE NOTICE '───────────────────────────────────────────────────────────────────';
-- -------------------------------------------------------------------------
-- 2.1 Grant schema usage
-- -------------------------------------------------------------------------
GRANT USAGE ON SCHEMA ops TO service_role;
RAISE NOTICE '✓ Granted USAGE on SCHEMA ops to service_role';
-- -------------------------------------------------------------------------
-- 2.2 Grant full table access
-- -------------------------------------------------------------------------
GRANT ALL ON ALL TABLES IN SCHEMA ops TO service_role;
RAISE NOTICE '✓ Granted ALL on ALL TABLES in ops to service_role';
-- -------------------------------------------------------------------------
-- 2.3 Grant function execution
-- -------------------------------------------------------------------------
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO service_role;
RAISE NOTICE '✓ Granted EXECUTE on ALL FUNCTIONS in ops to service_role';
-- -------------------------------------------------------------------------
-- 2.4 Grant sequence access (for INSERTs with serial/identity columns)
-- -------------------------------------------------------------------------
GRANT ALL ON ALL SEQUENCES IN SCHEMA ops TO service_role;
RAISE NOTICE '✓ Granted ALL on ALL SEQUENCES in ops to service_role';
END $service$;
-- =============================================================================
-- PART 3: SET DEFAULT PRIVILEGES FOR FUTURE OBJECTS
-- =============================================================================
-- Ensures new tables/functions in ops schema inherit the lockdown
DO $defaults$ BEGIN RAISE NOTICE '';
RAISE NOTICE '───────────────────────────────────────────────────────────────────';
RAISE NOTICE '  Setting default privileges for future ops objects';
RAISE NOTICE '───────────────────────────────────────────────────────────────────';
-- Future tables: only service_role gets access
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON TABLES
FROM anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON TABLES TO service_role;
RAISE NOTICE '✓ Default privileges set for future TABLES';
-- Future functions: only service_role can execute
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON FUNCTIONS
FROM anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT EXECUTE ON FUNCTIONS TO service_role;
RAISE NOTICE '✓ Default privileges set for future FUNCTIONS';
-- Future sequences: only service_role gets access
ALTER DEFAULT PRIVILEGES IN SCHEMA ops REVOKE ALL ON SEQUENCES
FROM anon,
    authenticated;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT ALL ON SEQUENCES TO service_role;
RAISE NOTICE '✓ Default privileges set for future SEQUENCES';
END $defaults$;
-- =============================================================================
-- PART 4: VERIFICATION
-- =============================================================================
DO $verify$
DECLARE v_anon_tables INT;
v_auth_tables INT;
v_service_tables INT;
v_exposed_schemas TEXT;
BEGIN RAISE NOTICE '';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  VERIFICATION: Checking ops schema access control';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
-- Count tables accessible to anon (should be 0)
SELECT COUNT(*) INTO v_anon_tables
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
    AND grantee = 'anon';
-- Count tables accessible to authenticated (should be 0)
SELECT COUNT(*) INTO v_auth_tables
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
    AND grantee = 'authenticated';
-- Count tables accessible to service_role (should be > 0 if tables exist)
SELECT COUNT(*) INTO v_service_tables
FROM information_schema.table_privileges
WHERE table_schema = 'ops'
    AND grantee = 'service_role';
-- Report results
IF v_anon_tables = 0 THEN RAISE NOTICE '✓ anon role: 0 table privileges in ops (LOCKED)';
ELSE RAISE WARNING '⚠ anon role: % table privileges in ops (LEAK!)',
v_anon_tables;
END IF;
IF v_auth_tables = 0 THEN RAISE NOTICE '✓ authenticated role: 0 table privileges in ops (LOCKED)';
ELSE RAISE WARNING '⚠ authenticated role: % table privileges in ops (LEAK!)',
v_auth_tables;
END IF;
RAISE NOTICE '✓ service_role: % table privileges in ops',
v_service_tables;
-- Remind about PostgREST config
RAISE NOTICE '';
RAISE NOTICE '───────────────────────────────────────────────────────────────────';
RAISE NOTICE '  ACTION REQUIRED: Verify PostgREST schema configuration';
RAISE NOTICE '  Ensure ops is NOT in PGRST_DB_SCHEMAS or Supabase exposed schemas';
RAISE NOTICE '───────────────────────────────────────────────────────────────────';
END $verify$;
DO $banner$ BEGIN RAISE NOTICE '';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE '  OPS SCHEMA LOCKDOWN COMPLETE';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
END $banner$;
COMMIT;
-- =============================================================================
-- DOCUMENTATION
-- =============================================================================
COMMENT ON SCHEMA ops IS 'Internal operations schema - LOCKED DOWN 2026-01-07. Access restricted to service_role only. NOT exposed via PostgREST public API.';