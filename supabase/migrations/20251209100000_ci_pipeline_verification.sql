-- =============================================================================
-- CI Pipeline Verification Migration
-- =============================================================================
-- Purpose: Harmless no-op to verify GitHub Actions workflow is working
-- This migration does nothing but confirm CI can connect and apply migrations
-- =============================================================================
DO $$ BEGIN -- This is a no-op migration to verify CI pipeline connectivity
-- It performs a simple SELECT and logs success
PERFORM 1;
RAISE NOTICE 'CI pipeline verification: SUCCESS at %',
now();
END $$;
-- Add a comment to the v_migration_status view to mark this test
COMMENT ON VIEW public.v_migration_status IS 'Unified migration status from both legacy (dragonfly_migrations) and Supabase CLI (schema_migrations) trackers. Query via REST: GET /rest/v1/v_migration_status. CI verified: 2024-12-04';