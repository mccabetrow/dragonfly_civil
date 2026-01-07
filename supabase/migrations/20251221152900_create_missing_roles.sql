-- ============================================================================
-- Migration: Create missing dragonfly roles for prod
-- Created: 2025-12-26
-- ============================================================================
--
-- PURPOSE:
-- Creates dragonfly_worker and dragonfly_readonly roles that were skipped
-- in the original 20251219180000 migration. These roles are required by
-- subsequent migrations like 20251221152903_zero_trust_hardening.sql.
--
-- ============================================================================
-- dragonfly_worker: Background worker role
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN CREATE ROLE dragonfly_worker WITH LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
RAISE NOTICE 'Created role: dragonfly_worker';
ELSE RAISE NOTICE 'Role dragonfly_worker already exists';
END IF;
END $$;
-- dragonfly_readonly: Dashboard analytics role
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_readonly'
) THEN CREATE ROLE dragonfly_readonly WITH LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
RAISE NOTICE 'Created role: dragonfly_readonly';
ELSE RAISE NOTICE 'Role dragonfly_readonly already exists';
END IF;
END $$;
-- Grant schema usage (wrapped in DO block to handle potential errors)
DO $$ BEGIN EXECUTE 'GRANT USAGE ON SCHEMA public TO dragonfly_worker, dragonfly_readonly';
EXECUTE 'GRANT USAGE ON SCHEMA ops TO dragonfly_worker, dragonfly_readonly';
RAISE NOTICE '[OK] Missing dragonfly roles created/verified';
END $$;
