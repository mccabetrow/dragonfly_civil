-- migrate:up

create schema if not exists enforcement;

create table if not exists enforcement.task_templates (
    template_code text primary key,
    label text not null,
    steps jsonb not null default '[]'::jsonb,
    constraint task_templates_steps_array check (jsonb_typeof(steps) = 'array')
);

create table if not exists enforcement.tasks (
    task_id uuid primary key default gen_random_uuid(),
    case_number text not null,
    template_code text not null references enforcement.task_templates (
        template_code
    ),
    step_type text not null,
    label text not null,
    status text not null default 'open',
    due_at timestamptz,
    created_at timestamptz not null default timezone('utc', now())
);

insert into enforcement.task_templates (template_code, label, steps)
values
(
    'INFO_SUBPOENA_FLOW',
    'Information Subpoena Flow',
    '[
            {"type": "prepare_packet", "label": "Prepare subpoena packet", "sla_days": 2},
            {"type": "mail_packet", "label": "Mail subpoena packet", "sla_days": 5},
            {"type": "await_response", "label": "Await debtor response", "sla_days": 30}
        ]'::jsonb
),
(
    'BANK_LEVY_FLOW',
    'Bank Levy Flow',
    '[
            {"type": "draft_writ", "label": "Draft writ of execution", "sla_days": 3},
            {"type": "deliver_sheriff", "label": "Deliver writ to sheriff", "sla_days": 7},
            {"type": "confirm_levy", "label": "Confirm levy with bank", "sla_days": 21}
        ]'::jsonb
),
(
    'WAGE_GARNISH_FLOW',
    'Wage Garnishment Flow',
    '[
            {"type": "prepare_application", "label": "Prepare garnishment application", "sla_days": 3},
            {"type": "notify_employer", "label": "Send employer notice", "sla_days": 5},
            {"type": "follow_up", "label": "Follow up on garnishment", "sla_days": 14}
        ]'::jsonb
)
on conflict (template_code) do update
set label = excluded.label,
steps = excluded.steps;

create or replace function public.spawn_enforcement_flow(
    p_case_number text, p_template_code text
)
returns uuid []
language plpgsql
security definer
set search_path = public, enforcement, pg_temp
as
$$
declare
    v_template enforcement.task_templates;
    v_created_ids uuid[] := array[]::uuid[];
    v_step jsonb;
    v_task_id uuid;
    v_sla integer;
    v_template_code text := coalesce(nullif(p_template_code, ''), 'INFO_SUBPOENA_FLOW');
begin
    select *
    into v_template
    from enforcement.task_templates
    where template_code = v_template_code;

    if not found then
        raise exception 'Enforcement template % not found', v_template_code;
    end if;

    if jsonb_array_length(v_template.steps) = 0 then
        return v_created_ids;
    end if;

    for v_step in
        select value from jsonb_array_elements(v_template.steps) as t(value)
    loop
        v_sla := coalesce((v_step->>'sla_days')::int, 0);

        insert into enforcement.tasks (
            case_number,
            template_code,
            step_type,
            label,
            due_at
        )
        values (
            p_case_number,
            v_template.template_code,
            v_step->>'type',
            coalesce(v_step->>'label', v_step->>'type'),
            timezone('utc', now()) + make_interval(days => v_sla)
        )
        returning task_id into v_task_id;

        v_created_ids := array_append(v_created_ids, v_task_id);
    end loop;

    return v_created_ids;
end;
$$;

grant execute on function public.spawn_enforcement_flow(
    text, text
) to service_role;

-- migrate:down

revoke execute on function public.spawn_enforcement_flow(
    text, text
) from service_role;
drop function if exists public.spawn_enforcement_flow (text, text);

drop table if exists enforcement.tasks;
drop table if exists enforcement.task_templates;
drop schema if exists enforcement;

