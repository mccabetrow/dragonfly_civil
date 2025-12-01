-- Queue depth snapshot for enrich, outreach, and enforce queues.
-- Designed for Metabase/Grafana to show visible and inflight counts per queue.

with queue_stats as (
    select
        q.queue_name,
        q.visible_count,
        q.invisible_count as inflight_count
    from pgmq.get_queue('enrich') as q
    union all
    select
        q.queue_name,
        q.visible_count,
        q.invisible_count as inflight_count
    from pgmq.get_queue('outreach') as q
    union all
    select
        q.queue_name,
        q.visible_count,
        q.invisible_count as inflight_count
    from pgmq.get_queue('enforce') as q
)
select
    queue_name,
    visible_count,
    inflight_count,
    visible_count + inflight_count as total_count,
    now() as observed_at
from queue_stats
order by queue_name;
