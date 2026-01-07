-- 0065_fix_collectability_perms.sql
-- Grant read access on public.v_collectability_snapshot to client-facing roles.

-- migrate:up

grant select on public.v_collectability_snapshot to anon;
grant select on public.v_collectability_snapshot to authenticated;
grant select on public.v_collectability_snapshot to service_role;

-- migrate:down

revoke select on public.v_collectability_snapshot from anon;
revoke select on public.v_collectability_snapshot from authenticated;
revoke select on public.v_collectability_snapshot from service_role;

