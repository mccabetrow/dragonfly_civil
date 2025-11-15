-- migrate:up

create table if not exists public.runs (
  id uuid primary key,
  kind text not null,
  status text not null,
  started_at timestamptz,
  finished_at timestamptz,
  details jsonb,
  error jsonb
);

create table if not exists public.events (
  id uuid primary key,
  run_id uuid not null,
  kind text not null,
  event text not null,
  status text not null,
  details jsonb,
  error jsonb,
  created_at timestamptz not null
);

grant usage on schema public to service_role;
grant all on table public.runs to service_role;
grant all on table public.events to service_role;

-- migrate:down

drop table if exists public.events;
drop table if exists public.runs;
