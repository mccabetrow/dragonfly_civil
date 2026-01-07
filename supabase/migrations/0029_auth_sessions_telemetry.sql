create schema if not exists analytics;

create table if not exists analytics.auth_sessions (
    id uuid primary key default gen_random_uuid(),
    at timestamptz not null default now(),
    kind text not null,
    ok boolean not null,
    latency_ms integer not null,
    reason text,
    run_id uuid null,
    node text not null default 'collector_v2'
);

