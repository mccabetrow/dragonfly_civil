-- 0058_collectability_public_view.sql
-- Expose collectability snapshot via public schema for dashboards.

-- migrate:up

drop view if exists public.v_collectability;
drop view if exists public.v_collectability_snapshot;

create or replace view public.v_collectability_snapshot as
select *
from judgments.v_collectability_snapshot;

revoke all on public.v_collectability_snapshot from public;
revoke all on public.v_collectability_snapshot from anon;
revoke all on public.v_collectability_snapshot from authenticated;

grant select on public.v_collectability_snapshot to anon;
grant select on public.v_collectability_snapshot to authenticated;
grant select on public.v_collectability_snapshot to service_role;

-- migrate:down

drop view if exists public.v_collectability;
drop view if exists public.v_collectability_snapshot;

