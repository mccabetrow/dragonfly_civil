-- Enforcement task SLA overview for operational monitoring.
-- Highlights open tasks with days overdue relative to due_at timestamps.

select
    t.case_number,
    t.template_code,
    t.step_type,
    t.label,
    t.status,
    t.due_at,
    greatest(date_part('day', timezone('utc', now()) - t.due_at), 0) as overdue_days
from enforcement.tasks as t
where t.status = 'open'
order by overdue_days desc, t.due_at nulls last;
