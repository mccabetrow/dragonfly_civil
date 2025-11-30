-- migrate:up

create table if not exists public.outreach_log (
    id bigserial primary key,
    case_number text not null,
    channel text not null default 'stub',
    template text not null default 'welcome_v0',
    status text not null default 'pending_provider',
    created_at timestamptz not null default timezone('utc', now()),
    metadata jsonb
);

create index if not exists outreach_log_case_number_idx on public.outreach_log (
    case_number
);

-- migrate:down

drop index if exists outreach_log_case_number_idx;
drop table if exists public.outreach_log;
