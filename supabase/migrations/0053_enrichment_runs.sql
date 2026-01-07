begin
drop trigger if exists trg_enrichment_runs_updated_at on public.enrichment_runs;
alter table public.enrichment_runs enable row level security;
do $$
begin
-- 0053_enrichment_runs.sql
-- Create logging table for enrichment worker executions in judgments schema.

drop table if exists public.enrichment_runs cascade;

create table if not exists judgments.enrichment_runs (
    id bigserial primary key,
    -- The spec refers to judgments.cases(id); cases table exposes case_id as the primary key.
    case_id uuid not null references judgments.cases(case_id) on delete cascade,
    status text not null,
    summary text,
    raw jsonb,
    created_at timestamptz not null default now()
);

create index if not exists idx_judgments_enrichment_runs_case_id on judgments.enrichment_runs (case_id);
create index if not exists idx_judgments_enrichment_runs_status on judgments.enrichment_runs (status);

alter table judgments.enrichment_runs enable row level security;

do $$

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
grant select, insert, update, delete on judgments.enrichment_runs to service_role;

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
            for all

