-- 0084_jbi_900_intake.sql
-- Track plaintiff source_system and expose aggregated stats for the JBI 900 upload.
-- migrate:up
alter table public.plaintiffs
add column if not exists source_system text;
update public.plaintiffs
set source_system = 'unknown'
where
    source_system is NULL
    or btrim(source_system) = '';
do $$ BEGIN
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET DEFAULT 'unknown';
EXCEPTION
WHEN undefined_column THEN -- Column was just added above for older environments.
NULL;
END $$;
update public.plaintiffs p
set source_system = 'simplicity'
where
    coalesce(p.source_system, 'unknown') = 'unknown'
    and exists (
        select 1
        from public.plaintiff_status_history as h
        where
            h.plaintiff_id = p.id
            and h.changed_by = 'simplicity_import'
    );
alter table public.plaintiffs
alter column source_system
set not null;
create or replace view public.v_plaintiffs_jbi_900 as
select
    p.status,
    count(*)::bigint as plaintiff_count,
    coalesce(
        sum(ov.total_judgment_amount), 0
    )::numeric as total_judgment_amount,
    case
    btrim(lower(p.status))
        when 'new' then 1
        when 'contacted' then 2
        when 'qualified' then 3
        when 'sent_agreement' then 4
        when 'signed' then 5
        when 'lost' then 6
        else 99
    end as status_priority
from public.plaintiffs as p
left join public.v_plaintiffs_overview as ov on p.id = ov.plaintiff_id
where p.source_system = 'jbi_900'
group by p.status;
grant select on public.v_plaintiffs_jbi_900 to anon,
authenticated,
service_role;
-- migrate:down
revoke
select on public.v_plaintiffs_jbi_900
from anon,
authenticated,
service_role;
drop view if exists public.v_plaintiffs_jbi_900;
alter table public.plaintiffs drop column if exists source_system;
-- Adds a source tag for plaintiffs and exposes a JBI-specific summary view for dashboards.
