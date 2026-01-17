-- =============================================================================
-- Migration: 20260114_create_app_user.sql
-- Purpose: Create dedicated dragonfly_app role for runtime applications
-- Author: Principal Database Reliability Engineer
-- Date: 2026-01-14
-- =============================================================================
--
-- SECURITY MODEL:
--   - dragonfly_app is a dedicated runtime user (not superuser)
--   - LOGIN enabled, NOINHERIT to prevent privilege escalation
--   - Explicit grants on public, ingest, intake, judgments, audit schemas
--   - Explicit REVOKE on ops schema (service_role only)
--   - Password set manually outside git (see RUNBOOK)
--
-- SUPABASE POOLER COMPATIBILITY:
--   This role is compatible with ALL Supabase pooler modes:
--
--   SHARED POOLER (aws-*.pooler.supabase.com:6543):
--     Username format: dragonfly_app.<project_ref>
--     Example DSN: postgresql://dragonfly_app.iaketsyhmqbwaabgykux:PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
--
--   DEDICATED POOLER (db.<ref>.supabase.co:6543):
--     Username format: dragonfly_app (plain)
--     Example DSN: postgresql://dragonfly_app:PASSWORD@db.iaketsyhmqbwaabgykux.supabase.co:6543/postgres?sslmode=require
--
--   DIRECT CONNECTION (port 5432):
--     FORBIDDEN in production - bypasses pooler and exhausts connections.
--
-- POST-MIGRATION STEPS:
--   1. Connect as postgres superuser
--   2. Run: ALTER ROLE dragonfly_app WITH PASSWORD 'your-strong-password';
--   3. Test: python -m tools.probe_db --env prod
--   4. Update DATABASE_URL in Railway with the new role
--
-- ROLLBACK:
--   DROP ROLE IF EXISTS dragonfly_app;
--
-- =============================================================================
BEGIN;
-- =============================================================================
-- STEP 1: Create the dragonfly_app role (idempotent)
-- =============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN CREATE ROLE dragonfly_app WITH LOGIN NOINHERIT;
RAISE NOTICE '✓ Created role dragonfly_app';
ELSE RAISE NOTICE '✓ Role dragonfly_app already exists';
END IF;
END $$;
-- Ensure LOGIN and NOINHERIT are set (idempotent)
ALTER ROLE dragonfly_app WITH LOGIN NOINHERIT;
-- Grant CONNECT on the postgres database (required for direct connections)
GRANT CONNECT ON DATABASE postgres TO dragonfly_app;
-- =============================================================================
-- STEP 2: Grant USAGE on application schemas
-- =============================================================================
-- These are the schemas dragonfly_app needs for runtime operations
-- public schema (core tables: plaintiffs, judgments, etc.)
GRANT USAGE ON SCHEMA public TO dragonfly_app;
-- ingest schema (import_runs, batch tracking)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'ingest'
) THEN
GRANT USAGE ON SCHEMA ingest TO dragonfly_app;
RAISE NOTICE '✓ Granted USAGE on ingest schema';
END IF;
END $$;
-- intake schema (plaintiff intake pipeline)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'intake'
) THEN
GRANT USAGE ON SCHEMA intake TO dragonfly_app;
RAISE NOTICE '✓ Granted USAGE on intake schema';
END IF;
END $$;
-- judgments schema (judgment-specific tables if separate)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'judgments'
) THEN
GRANT USAGE ON SCHEMA judgments TO dragonfly_app;
RAISE NOTICE '✓ Granted USAGE on judgments schema';
END IF;
END $$;
-- audit schema (audit trails for compliance)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'audit'
) THEN
GRANT USAGE ON SCHEMA audit TO dragonfly_app;
RAISE NOTICE '✓ Granted USAGE on audit schema';
END IF;
END $$;
-- =============================================================================
-- STEP 3: Grant table-level permissions on each schema
-- =============================================================================
-- 3a. PUBLIC schema - full CRUD on all tables
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ALL TABLES IN SCHEMA public TO dragonfly_app;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA public TO dragonfly_app;
-- 3b. INGEST schema - full CRUD
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'ingest'
) THEN EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA ingest TO dragonfly_app';
EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA ingest TO dragonfly_app';
RAISE NOTICE '✓ Granted table permissions on ingest schema';
END IF;
END $$;
-- 3c. INTAKE schema - full CRUD
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'intake'
) THEN EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA intake TO dragonfly_app';
EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA intake TO dragonfly_app';
RAISE NOTICE '✓ Granted table permissions on intake schema';
END IF;
END $$;
-- 3d. JUDGMENTS schema - full CRUD
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'judgments'
) THEN EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA judgments TO dragonfly_app';
EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA judgments TO dragonfly_app';
RAISE NOTICE '✓ Granted table permissions on judgments schema';
END IF;
END $$;
-- 3e. AUDIT schema - full CRUD (app writes audit logs)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'audit'
) THEN EXECUTE 'GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA audit TO dragonfly_app';
EXECUTE 'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA audit TO dragonfly_app';
RAISE NOTICE '✓ Granted table permissions on audit schema';
END IF;
END $$;
-- =============================================================================
-- STEP 4: Set default privileges for future tables
-- =============================================================================
-- This ensures new tables automatically get the right grants
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE,
    SELECT ON SEQUENCES TO dragonfly_app;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'ingest'
) THEN EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA ingest GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dragonfly_app';
EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA ingest GRANT USAGE, SELECT ON SEQUENCES TO dragonfly_app';
END IF;
END $$;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'intake'
) THEN EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA intake GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dragonfly_app';
EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA intake GRANT USAGE, SELECT ON SEQUENCES TO dragonfly_app';
END IF;
END $$;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'judgments'
) THEN EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA judgments GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dragonfly_app';
EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA judgments GRANT USAGE, SELECT ON SEQUENCES TO dragonfly_app';
END IF;
END $$;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'audit'
) THEN EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO dragonfly_app';
EXECUTE 'ALTER DEFAULT PRIVILEGES IN SCHEMA audit GRANT USAGE, SELECT ON SEQUENCES TO dragonfly_app';
END IF;
END $$;
-- =============================================================================
-- STEP 5: EXPLICITLY REVOKE access to ops schema (security constraint)
-- =============================================================================
-- ops schema is for service_role ONLY (internal system health, audit internals)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = 'ops'
) THEN EXECUTE 'REVOKE ALL ON SCHEMA ops FROM dragonfly_app';
EXECUTE 'REVOKE ALL ON ALL TABLES IN SCHEMA ops FROM dragonfly_app';
EXECUTE 'REVOKE ALL ON ALL SEQUENCES IN SCHEMA ops FROM dragonfly_app';
EXECUTE 'REVOKE ALL ON ALL FUNCTIONS IN SCHEMA ops FROM dragonfly_app';
RAISE NOTICE '✓ REVOKED all access to ops schema from dragonfly_app';
END IF;
END $$;
-- =============================================================================
-- STEP 6: Grant EXECUTE on application RPC functions (if needed)
-- =============================================================================
-- dragonfly_app may need to call certain RPC functions
-- Grant execute on public schema functions (if any are used by app)
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO dragonfly_app;
-- =============================================================================
-- VERIFICATION
-- =============================================================================
DO $$
DECLARE v_has_ops_usage boolean;
BEGIN -- Verify dragonfly_app cannot access ops schema
SELECT has_schema_privilege('dragonfly_app', 'ops', 'USAGE') INTO v_has_ops_usage;
IF v_has_ops_usage THEN RAISE EXCEPTION 'SECURITY VIOLATION: dragonfly_app has USAGE on ops schema';
END IF;
RAISE NOTICE '✅ VERIFIED: dragonfly_app has NO access to ops schema';
RAISE NOTICE '✅ dragonfly_app role configured successfully';
RAISE NOTICE '';
RAISE NOTICE 'NEXT STEP: Set password manually:';
RAISE NOTICE '  ALTER ROLE dragonfly_app WITH PASSWORD ''your-strong-password'';';
END $$;
COMMIT;
-- =============================================================================
-- POST-MIGRATION VERIFICATION QUERIES
-- =============================================================================
/*
 -- Check role exists and attributes
 SELECT rolname, rolcanlogin, rolinherit, rolsuper
 FROM pg_roles
 WHERE rolname = 'dragonfly_app';
 
 -- Check schema privileges
 SELECT nspname, has_schema_privilege('dragonfly_app', nspname, 'USAGE') as has_usage
 FROM pg_namespace
 WHERE nspname IN ('public', 'ingest', 'intake', 'judgments', 'audit', 'ops');
 
 -- Check table privileges on a sample table
 SELECT grantee, table_schema, table_name, privilege_type
 FROM information_schema.table_privileges
 WHERE grantee = 'dragonfly_app'
 ORDER BY table_schema, table_name;
 */