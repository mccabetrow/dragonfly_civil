-- =============================================================================
-- Migration Status View (REST-friendly)
-- =============================================================================
-- Purpose: Unified view of both legacy and Supabase CLI migration trackers
--          Queryable via PostgREST without direct DB access
-- 
-- Tables unified:
--   - public.dragonfly_migrations (legacy numeric versions)
--   - supabase_migrations.schema_migrations (Supabase CLI timestamped)
--
-- Usage (REST):
--   GET /rest/v1/v_migration_status?order=executed_at.desc&limit=100
--
-- Usage (CLI):
--   python -m tools.migration_status
-- =============================================================================
-- Drop existing view if it exists (idempotent)
drop view if exists public.v_migration_status;
-- Create the unified migration status view
create view public.v_migration_status as
select 'legacy'::text as source,
    -- Extract numeric prefix from filename (e.g., "0001" from "0001_core_schema.sql")
    coalesce(
        left(dm.migration_filename, 4),
        dm.migration_filename
    ) as version,
    dm.migration_filename as name,
    dm.applied_at as executed_at,
    true as success
from public.dragonfly_migrations dm
union all
select 'supabase'::text as source,
    sm.version::text as version,
    sm.name as name,
    -- supabase_migrations.schema_migrations has no timestamp column
    -- Use version as proxy (timestamp format: YYYYMMDDHHMMSS)
    to_timestamp(sm.version::text, 'YYYYMMDDHH24MISS') as executed_at,
    true as success
from supabase_migrations.schema_migrations sm
where sm.version ~ '^\d{14}$';
-- Only include timestamp-formatted versions
-- Grant read access to authenticated users and service role
grant select on public.v_migration_status to authenticated;
grant select on public.v_migration_status to service_role;
-- Note: Views don't have RLS - they inherit from underlying tables
-- The view will only show rows the caller has access to in the base tables
comment on view public.v_migration_status is 'Unified migration status from both legacy (dragonfly_migrations) and Supabase CLI (schema_migrations) trackers. Query via REST: GET /rest/v1/v_migration_status';