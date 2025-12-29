-- Migration: Grant intake schema access to dragonfly_app
-- Description: Allow dragonfly_app role to insert demo data into intake tables
-- ============================================================================
-- Grant schema usage
GRANT USAGE ON SCHEMA intake TO dragonfly_app;
-- Grant table permissions for the ingestion pipeline
GRANT SELECT,
    INSERT,
    UPDATE ON ALL TABLES IN SCHEMA intake TO dragonfly_app;
-- Grant sequence permissions (for serial columns)
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA intake TO dragonfly_app;
-- Ensure future tables also get permissions
ALTER DEFAULT PRIVILEGES IN SCHEMA intake
GRANT SELECT,
    INSERT,
    UPDATE ON TABLES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA intake
GRANT USAGE,
    SELECT ON SEQUENCES TO dragonfly_app;