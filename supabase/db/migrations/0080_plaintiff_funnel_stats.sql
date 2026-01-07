-- 0080_plaintiff_funnel_stats.sql
-- Adds an aggregated funnel view for plaintiffs by status.

-- migrate:up

create or replace view public.v_plaintiff_funnel_stats as
select
    COUNT(*)::bigint as plaintiff_count,
    COALESCE(SUM(o.total_judgment_amount), 0)::numeric as total_judgment_amount,
    COALESCE(p.status, 'unknown') as status
from public.plaintiffs as p
left join public.v_plaintiffs_overview as o
    on p.id = o.plaintiff_id
group by COALESCE(p.status, 'unknown')
order by status;

grant select on public.v_plaintiff_funnel_stats to anon,
authenticated,
service_role;

-- migrate:down

revoke select on public.v_plaintiff_funnel_stats from anon,
authenticated,
service_role;
drop view if exists public.v_plaintiff_funnel_stats;

-- Purpose: summarize plaintiff funnel volume and value for dashboards.
