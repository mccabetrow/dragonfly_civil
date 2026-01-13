-- =============================================================================
-- 20260112_ops_lockdown_canonical.sql
-- Canonical ops schema lockdown - FULLY IDEMPOTENT
-- =============================================================================
--
-- DESIGN PRINCIPLES:
-- 1. Every statement is rerunnable without errors
-- 2. All RAISE NOTICE wrapped in DO blocks (required by PostgreSQL)
-- 3. REVOKE ALL + SECURITY DEFINER RPC pattern
-- 4. Only service_role can access ops schema
-- 5. Dashboard reads via SECURITY DEFINER functions
--
-- Safe to run on fresh database OR existing database with partial state.
--
-- =============================================================================
begin;
-- ===========================================================================
-- STEP 1: Create schema if missing
-- ===========================================================================
create schema if not exists ops;
comment on schema ops is 'Operations schema - internal system health, audit trails, and platform metrics. Access via SECURITY DEFINER RPCs only.';
-- ===========================================================================
-- STEP 2: Core ops tables (IF NOT EXISTS for all)
-- ===========================================================================
-- 2a. System health snapshots
create table if not exists ops.health_snapshots (
    id uuid primary key default gen_random_uuid(),
    snapshot_time timestamptz not null default now(),
    component text not null,
    status text not null check (status in ('healthy', 'degraded', 'unhealthy')),
    latency_ms integer,
    error_message text,
    metadata jsonb default '{}',
    created_at timestamptz not null default now()
);
create index if not exists idx_health_snapshots_time on ops.health_snapshots (snapshot_time desc);
create index if not exists idx_health_snapshots_component on ops.health_snapshots (component, snapshot_time desc);
-- 2b. Worker heartbeats
create table if not exists ops.worker_heartbeats (
    id uuid primary key default gen_random_uuid(),
    worker_id text not null unique,
    worker_type text not null,
    last_heartbeat timestamptz not null default now(),
    status text not null default 'active',
    metadata jsonb default '{}',
    created_at timestamptz not null default now()
);
create index if not exists idx_worker_heartbeats_type on ops.worker_heartbeats (worker_type, last_heartbeat desc);
-- 2c. Audit log
create table if not exists ops.audit_log (
    id uuid primary key default gen_random_uuid(),
    event_time timestamptz not null default now(),
    event_type text not null,
    actor text,
    target_table text,
    target_id text,
    old_values jsonb,
    new_values jsonb,
    metadata jsonb default '{}',
    created_at timestamptz not null default now()
);
create index if not exists idx_audit_log_time on ops.audit_log (event_time desc);
create index if not exists idx_audit_log_type on ops.audit_log (event_type, event_time desc);
create index if not exists idx_audit_log_target on ops.audit_log (target_table, target_id);
-- 2d. Platform metrics aggregates
create table if not exists ops.platform_metrics (
    id uuid primary key default gen_random_uuid(),
    metric_time timestamptz not null default now(),
    metric_name text not null,
    metric_value numeric not null,
    dimensions jsonb default '{}',
    created_at timestamptz not null default now()
);
create index if not exists idx_platform_metrics_name_time on ops.platform_metrics (metric_name, metric_time desc);
do $$ BEGIN RAISE NOTICE '✓ ops tables verified/created';
END $$;
-- ===========================================================================
-- STEP 3: REVOKE ALL from public, anon, authenticated
-- ===========================================================================
revoke all on schema ops
from public,
anon,
authenticated;
revoke all on all tables in schema ops
from public,
anon,
authenticated;
revoke all on all sequences in schema ops
from public,
anon,
authenticated;
revoke all on all routines in schema ops
from public,
anon,
authenticated;
do $$ BEGIN RAISE NOTICE '✓ Revoked all public access to ops schema';
END $$;
-- ===========================================================================
-- STEP 4: Grant to service_role only
-- ===========================================================================
grant usage on schema ops to service_role;
grant select,
insert,
update,
delete on all tables in schema ops to service_role;
grant usage,
select on all sequences in schema ops to service_role;
grant execute on all routines in schema ops to service_role;
do $$ BEGIN RAISE NOTICE '✓ Granted full access to service_role';
END $$;
-- ===========================================================================
-- STEP 5: Set default privileges for future objects
-- ===========================================================================
alter default privileges in schema ops revoke all on tables
from public,
anon,
authenticated;
alter default privileges in schema ops revoke all on sequences
from public,
anon,
authenticated;
alter default privileges in schema ops revoke all on routines
from public,
anon,
authenticated;
alter default privileges in schema ops
grant all on tables to service_role;
alter default privileges in schema ops
grant all on sequences to service_role;
alter default privileges in schema ops
grant execute on routines to service_role;
-- ===========================================================================
-- STEP 6: SECURITY DEFINER RPC for dashboard health read
-- ===========================================================================
create or replace function ops.get_system_health(p_limit integer default 100) returns table (
    id uuid,
    snapshot_time timestamptz,
    component text,
    status text,
    latency_ms integer,
    error_message text,
    metadata jsonb
) language plpgsql security definer
set search_path = ops as $$ BEGIN RETURN QUERY
SELECT h.id,
    h.snapshot_time,
    h.component,
    h.status,
    h.latency_ms,
    h.error_message,
    h.metadata
FROM ops.health_snapshots h
ORDER BY h.snapshot_time DESC
LIMIT p_limit;
END;
$$;
-- Secure the function
revoke all on function ops.get_system_health(integer)
from public;
grant execute on function ops.get_system_health(integer) to service_role;
grant execute on function ops.get_system_health(integer) to authenticated;
comment on function ops.get_system_health is 'SECURITY DEFINER RPC - safe read-only access to health snapshots for dashboard.';
-- ===========================================================================
-- STEP 7: SECURITY DEFINER RPC for worker status
-- ===========================================================================
create or replace function ops.get_worker_status() returns table (
    worker_id text,
    worker_type text,
    last_heartbeat timestamptz,
    status text,
    is_stale boolean
) language plpgsql security definer
set search_path = ops as $$ BEGIN RETURN QUERY
SELECT w.worker_id,
    w.worker_type,
    w.last_heartbeat,
    w.status,
    (w.last_heartbeat < now() - interval '5 minutes') AS is_stale
FROM ops.worker_heartbeats w
ORDER BY w.last_heartbeat DESC;
END;
$$;
revoke all on function ops.get_worker_status()
from public;
grant execute on function ops.get_worker_status() to service_role;
grant execute on function ops.get_worker_status() to authenticated;
comment on function ops.get_worker_status is 'SECURITY DEFINER RPC - read-only worker heartbeat status for dashboard.';
-- ===========================================================================
-- STEP 8: SECURITY DEFINER RPC for dashboard stats JSON
-- ===========================================================================
create or replace function ops.get_dashboard_stats_json() returns jsonb language plpgsql security definer
set search_path = ops,
public as $$
DECLARE v_result jsonb;
v_plaintiffs_total bigint;
v_plaintiffs_active bigint;
v_judgments_total bigint;
v_judgments_value numeric;
v_workers_active bigint;
v_health_status text;
BEGIN -- Plaintiff counts (from public schema)
SELECT COUNT(*),
    COUNT(*) FILTER (
        WHERE status NOT IN ('rejected', 'closed')
    ) INTO v_plaintiffs_total,
    v_plaintiffs_active
FROM public.plaintiffs;
-- Judgment counts (from public schema)
SELECT COUNT(*),
    COALESCE(SUM(total_judgment_amount), 0) INTO v_judgments_total,
    v_judgments_value
FROM public.judgments;
-- Active workers
SELECT COUNT(*) INTO v_workers_active
FROM ops.worker_heartbeats
WHERE last_heartbeat > now() - interval '5 minutes';
-- Latest health status
SELECT h.status INTO v_health_status
FROM ops.health_snapshots h
WHERE h.component = 'system'
ORDER BY h.snapshot_time DESC
LIMIT 1;
v_result := jsonb_build_object(
    'plaintiffs_total', v_plaintiffs_total, 'plaintiffs_active', v_plaintiffs_active, 'judgments_total', v_judgments_total, 'judgments_value', v_judgments_value, 'workers_active', v_workers_active, 'system_health', COALESCE(v_health_status, 'unknown'), 'generated_at', now()
);
RETURN v_result;
END;
$$;
revoke all on function ops.get_dashboard_stats_json()
from public;
grant execute on function ops.get_dashboard_stats_json() to service_role;
grant execute on function ops.get_dashboard_stats_json() to authenticated;
comment on function ops.get_dashboard_stats_json is 'SECURITY DEFINER RPC - aggregated dashboard stats from ops + public schemas.';
-- ===========================================================================
-- STEP 9: SECURITY DEFINER RPC for recent audit events
-- ===========================================================================
create or replace function ops.get_recent_audit_events(
    p_limit integer default 50,
    p_event_type text default NULL
) returns table (
    id uuid,
    event_time timestamptz,
    event_type text,
    actor text,
    target_table text,
    target_id text,
    metadata jsonb
) language plpgsql security definer
set search_path = ops as $$ BEGIN RETURN QUERY
SELECT a.id,
    a.event_time,
    a.event_type,
    a.actor,
    a.target_table,
    a.target_id,
    a.metadata
FROM ops.audit_log a
WHERE (
        p_event_type IS NULL
        OR a.event_type = p_event_type
    )
ORDER BY a.event_time DESC
LIMIT p_limit;
END;
$$;
revoke all on function ops.get_recent_audit_events(integer, text)
from public;
grant execute on function ops.get_recent_audit_events(integer, text) to service_role;
grant execute on function ops.get_recent_audit_events(integer, text) to authenticated;
comment on function ops.get_recent_audit_events is 'SECURITY DEFINER RPC - paginated audit log access for dashboard.';
-- ===========================================================================
-- STEP 10: Enable RLS on all ops tables (belt and suspenders)
-- ===========================================================================
alter table ops.health_snapshots enable row level security;
alter table ops.worker_heartbeats enable row level security;
alter table ops.audit_log enable row level security;
alter table ops.platform_metrics enable row level security;
alter table ops.health_snapshots force row level security;
alter table ops.worker_heartbeats force row level security;
alter table ops.audit_log force row level security;
alter table ops.platform_metrics force row level security;
-- ===========================================================================
-- STEP 11: RLS policies - service_role only (drop first for idempotency)
-- ===========================================================================
drop policy if exists health_snapshots_service_role on ops.health_snapshots;
drop policy if exists worker_heartbeats_service_role on ops.worker_heartbeats;
drop policy if exists audit_log_service_role on ops.audit_log;
drop policy if exists platform_metrics_service_role on ops.platform_metrics;
create policy health_snapshots_service_role on ops.health_snapshots for all to service_role using (TRUE) with check (TRUE);
create policy worker_heartbeats_service_role on ops.worker_heartbeats for all to service_role using (TRUE) with check (TRUE);
create policy audit_log_service_role on ops.audit_log for all to service_role using (TRUE) with check (TRUE);
create policy platform_metrics_service_role on ops.platform_metrics for all to service_role using (TRUE) with check (TRUE);
-- ===========================================================================
-- STEP 12: Reload PostgREST schema cache
-- ===========================================================================
do $$ BEGIN PERFORM pg_notify('pgrst', 'reload schema');
RAISE NOTICE '✓ Notified PostgREST to reload schema cache';
END $$;
do $$ BEGIN RAISE NOTICE '✓ ops schema lockdown complete';
RAISE NOTICE '  - All tables protected with RLS + service_role-only policies';
RAISE NOTICE '  - Dashboard access via SECURITY DEFINER RPCs only';
RAISE NOTICE '  - Public/anon/authenticated revoked from schema';
END $$;
commit;
-- ===========================================================================
-- VERIFICATION QUERIES (run after migration)
-- ===========================================================================
/*
 -- Check schema grants
 SELECT nspname, nspacl FROM pg_namespace WHERE nspname = 'ops';

 -- Check table grants
 SELECT
 schemaname,
 tablename,
 tableowner,
 hasindexes,
 hasrules,
 hastriggers,
 rowsecurity
 FROM pg_tables
 WHERE schemaname = 'ops';

 -- Check RLS policies
 SELECT schemaname, tablename, policyname, permissive, roles, cmd
 FROM pg_policies
 WHERE schemaname = 'ops';

 -- Check function security
 SELECT
 routine_schema,
 routine_name,
 security_type
 FROM information_schema.routines
 WHERE routine_schema = 'ops';

 -- Test dashboard RPC (should work for authenticated)
 SELECT * FROM ops.get_system_health(5);
 SELECT ops.get_dashboard_stats_json();
 */
-- ===========================================================================
