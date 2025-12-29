-- ═══════════════════════════════════════════════════════════════════════════
-- Dragonfly Civil - Database Password Reset
-- ═══════════════════════════════════════════════════════════════════════════
--
-- Purpose: Reset the dragonfly_app role password to fix authentication failures.
--
-- Usage:
--   1. Run scripts/generate_db_strings.ps1 to generate a new password
--   2. Copy the ALTER ROLE command from the script output
--   3. Run it in Supabase SQL Editor (Dashboard -> SQL Editor -> New Query)
--   4. Update Railway env var SUPABASE_DB_URL with the new connection string
--   5. Redeploy Railway
--
-- ⚠️  SECURITY: Never commit this file with the actual password filled in.
-- ═══════════════════════════════════════════════════════════════════════════
-- Step 1: Check if the role exists
SELECT rolname,
    rolcanlogin,
    rolcreatedb,
    rolsuper
FROM pg_roles
WHERE rolname = 'dragonfly_app';
-- Step 2: Reset the password (REPLACE WITH GENERATED PASSWORD)
-- Run scripts/generate_db_strings.ps1 to get the actual command
ALTER ROLE dragonfly_app WITH PASSWORD '<NEW_PASSWORD_HERE>';
-- Step 3: Verify the role has login privileges
ALTER ROLE dragonfly_app WITH LOGIN;
-- Step 4: Grant necessary permissions (if not already granted)
GRANT USAGE ON SCHEMA public TO dragonfly_app;
GRANT USAGE ON SCHEMA intake TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ALL TABLES IN SCHEMA public TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ALL TABLES IN SCHEMA intake TO dragonfly_app;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA public TO dragonfly_app;
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO dragonfly_app;
-- Step 5: Set default privileges for future tables
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA intake
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLES TO dragonfly_app;