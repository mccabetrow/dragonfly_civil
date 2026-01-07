-- 0055_enrichment_runs_finalize.sql
-- Ensure enrichment logging lives in judgments schema with writable view.

-- migrate:up

create schema if not exists judgments;

create table if not exists judgments.enrichment_runs (
    id bigserial primary key,
    case_id uuid not null references judgments.cases (
        case_id
    ) on delete cascade,
    status text not null,
    summary text,
    raw jsonb,
    created_at timestamptz not null default now()
);

do $$
begin
    if exists (
        select 1
        from information_schema.tables
        where table_schema = 'public'
          and table_name = 'enrichment_runs'
    ) then
        if not exists (select 1 from judgments.enrichment_runs) then
            insert into judgments.enrichment_runs (case_id, status, summary, raw, created_at)
            select
                case_id,
                coalesce(nullif(status, ''), 'success') as status,
                error,
                payload,
                created_at
            from public.enrichment_runs;
        end if;
        drop table public.enrichment_runs;
    end if;
end;
$$;

drop view if exists public.enrichment_runs;

create index if not exists idx_judgments_enrichment_runs_case_id on judgments.enrichment_runs (
    case_id
);
create index if not exists idx_judgments_enrichment_runs_status on judgments.enrichment_runs (
    status
);

alter table judgments.enrichment_runs enable row level security;

do $$
begin
    if not exists (
        select 1
        from pg_policies
        where schemaname = 'judgments'
          and tablename = 'enrichment_runs'
          and policyname = 'service_enrichment_runs_rw'
    ) then
        create policy service_enrichment_runs_rw on judgments.enrichment_runs
            for all
            using (auth.role() = 'service_role')
            with check (auth.role() = 'service_role');
    end if;
end;
$$;

revoke all on judgments.enrichment_runs from public;
revoke all on judgments.enrichment_runs from anon;
revoke all on judgments.enrichment_runs from authenticated;
grant select,
insert,
update,
delete on judgments.enrichment_runs to service_role;
grant usage,
select on sequence judgments.enrichment_runs_id_seq to service_role;

create or replace view public.enrichment_runs as
select
    id,
    case_id,
    status,
    summary,
    raw,
    created_at
from judgments.enrichment_runs;

revoke all on public.enrichment_runs from public;
revoke all on public.enrichment_runs from anon;
revoke all on public.enrichment_runs from authenticated;
grant select, insert, update, delete on public.enrichment_runs to service_role;

-- migrate:down

drop view if exists public.enrichment_runs;
drop table if exists judgments.enrichment_runs;

