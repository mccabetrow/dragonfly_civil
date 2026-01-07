-- 0077_plaintiff_tasks.sql
-- Introduce plaintiff task tracking and dashboard-friendly open task view.

-- migrate:up

create table if not exists public.plaintiff_tasks (
    id uuid primary key default gen_random_uuid(),
    plaintiff_id uuid not null references public.plaintiffs (
        id
    ) on delete cascade,
    kind text not null,
    status text not null default 'open',
    due_at timestamptz,
    completed_at timestamptz,
    note text,
    created_at timestamptz not null default now(),
    created_by text
);

alter table public.plaintiff_tasks
add column if not exists id uuid default gen_random_uuid(),
add column if not exists plaintiff_id uuid,
add column if not exists kind text,
add column if not exists status text not null default 'open',
add column if not exists due_at timestamptz,
add column if not exists completed_at timestamptz,
add column if not exists note text,
add column if not exists created_at timestamptz not null default now(),
add column if not exists created_by text;

alter table public.plaintiff_tasks
alter column id set default gen_random_uuid(),
alter column plaintiff_id set not null,
alter column kind set not null,
alter column status set default 'open',
alter column status set not null,
alter column created_at set default now(),
alter column created_at set not null;

do $$
BEGIN
    ALTER TABLE public.plaintiff_tasks
        ADD CONSTRAINT plaintiff_tasks_plaintiff_id_fkey
            FOREIGN KEY (plaintiff_id)
            REFERENCES public.plaintiffs(id)
            ON DELETE CASCADE;
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END
$$;

create index if not exists plaintiff_tasks_plaintiff_status_due_idx
on public.plaintiff_tasks (plaintiff_id, status, due_at);

create or replace view public.v_plaintiff_open_tasks as
select
    t.id as task_id,
    t.plaintiff_id,
    p.name as plaintiff_name,
    p.firm_name,
    t.kind,
    t.status,
    t.due_at,
    t.created_at,
    t.note
from public.plaintiff_tasks as t
inner join public.plaintiffs as p
    on t.plaintiff_id = p.id
where t.status in ('open', 'in_progress');

grant select on table public.plaintiff_tasks to anon, authenticated;
grant select on public.v_plaintiff_open_tasks to anon, authenticated;
grant select on table public.plaintiff_tasks to anon,
authenticated,
service_role;
grant select on public.v_plaintiff_open_tasks to anon,
authenticated,
service_role;

-- migrate:down

revoke select on public.v_plaintiff_open_tasks from anon,
authenticated,
service_role;
revoke select on table public.plaintiff_tasks from anon,
authenticated,
service_role;
drop view if exists public.v_plaintiff_open_tasks;
drop index if exists plaintiff_tasks_plaintiff_status_due_idx;
drop table if exists public.plaintiff_tasks;

-- Purpose: track plaintiff-facing tasks and expose open work for dashboards.
