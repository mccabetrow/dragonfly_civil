-- 20251205102000_enforcement_radar_repair.sql
-- Ensure enforcement radar infrastructure exists in all environments.
-- This migration is deliberately idempotent to repair any drift.
-- Ensure schemas exist
create schema if not exists ops;
create schema if not exists enforcement;
-- Ensure radar columns exist on public.judgments
alter table public.judgments
add column if not exists court text,
    add column if not exists county text,
    add column if not exists judgment_date date,
    add column if not exists collectability_score integer;
-- Enrichment health view
create or replace view ops.v_enrichment_health as
select count(*) filter (
        where status = 'pending'
    ) as pending_jobs,
    count(*) filter (
        where status = 'processing'
    ) as processing_jobs,
    count(*) filter (
        where status = 'failed'
    ) as failed_jobs,
    count(*) filter (
        where status = 'completed'
    ) as completed_jobs,
    max(created_at) as last_job_created_at,
    max(updated_at) as last_job_updated_at,
    now() - max(updated_at) as time_since_last_activity
from ops.job_queue;
-- Enforcement radar view
create or replace view enforcement.v_radar as
select j.id,
    j.case_number,
    j.plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.court,
    j.county,
    j.judgment_date,
    j.collectability_score,
    j.status,
    case
        when j.collectability_score >= 70
        and j.judgment_amount >= 10000 then 'BUY_CANDIDATE'
        when j.collectability_score >= 40 then 'CONTINGENCY'
        when j.collectability_score is null then 'ENRICHMENT_PENDING'
        else 'LOW_PRIORITY'
    end as offer_strategy,
    j.created_at
from public.judgments j
where coalesce(j.status, '') not in ('SATISFIED', 'EXPIRED')
order by j.collectability_score desc nulls last,
    j.judgment_amount desc;
-- Permissions
grant usage on schema ops,
    enforcement to authenticated,
    service_role;
grant select on ops.v_enrichment_health to authenticated,
    service_role;
grant select on enforcement.v_radar to authenticated,
    service_role;
