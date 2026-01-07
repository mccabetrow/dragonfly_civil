-- 0059_foil_responses.sql
-- Store FOIL responses and expose read-only view for internal tooling.

-- migrate:up

do $$
begin
    if exists (
        select 1
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where n.nspname = 'judgments'
          and c.relname = 'foil_responses'
          and c.relkind in ('v', 'm')
    ) then
        execute 'drop view if exists judgments.foil_responses cascade';
    end if;
end;
$$;

create table if not exists judgments.foil_responses (
    id bigserial primary key,
    case_id uuid not null references judgments.cases (
        case_id
    ) on delete cascade,
    created_at timestamptz not null default timezone('utc', now()),
    received_date date,
    agency text,
    payload jsonb not null
);

create index if not exists idx_judgments_foil_responses_case_id on judgments.foil_responses (
    case_id
);

alter table judgments.foil_responses enable row level security;

do $$
begin
    if not exists (
        select 1
        from pg_policies
        where schemaname = 'judgments'
          and tablename = 'foil_responses'
          and policyname = 'service_foil_responses_rw'
    ) then
        create policy service_foil_responses_rw on judgments.foil_responses
            for all
            using (auth.role() = 'service_role')
            with check (auth.role() = 'service_role');
    end if;
end;
$$;

revoke all on judgments.foil_responses from public;
revoke all on judgments.foil_responses from anon;
revoke all on judgments.foil_responses from authenticated;

grant select,
insert,
update,
delete on judgments.foil_responses to service_role;

do $$
begin
    if exists (
        select 1
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'S'
          and n.nspname = 'judgments'
          and c.relname = 'foil_responses_id_seq'
    ) then
        execute 'grant usage, select on sequence judgments.foil_responses_id_seq to service_role';
    end if;
end;
$$;

-- migrate:down

drop view if exists public.foil_responses;
drop table if exists judgments.foil_responses cascade;

