-- Daily judgment funnel grouped by current status.
-- Intended for visualizing throughput of cases across major lifecycle stages.

with daily_status as (
    select
        date_trunc('day', coalesce(j.updated_at, j.created_at)) as day,
        j.status,
        count(*) as case_count
    from public.judgments as j
    group by 1, 2
)
select
    day,
    status,
    case_count
from daily_status
order by day desc, status;
