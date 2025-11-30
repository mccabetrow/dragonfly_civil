-- 0066_rls_hardening.sql
-- Harden row-level security for public-facing tables and views.

-- migrate:up

-- public.judgments: allow frontend reads, restrict writes to service_role.
alter table public.judgments enable row level security;

drop policy if exists "Allow public read-only access" on public.judgments;
drop policy if exists judgments_select_public on public.judgments;
drop policy if exists judgments_insert_service on public.judgments;
drop policy if exists judgments_update_service on public.judgments;
drop policy if exists judgments_delete_service on public.judgments;

-- Allow anon/authenticated dashboards (and service_role) to read projected judgment rows.
create policy judgments_select_public on public.judgments
for select
using (auth.role() in ('anon', 'authenticated', 'service_role'));

-- Limit API inserts to the service worker role.
create policy judgments_insert_service on public.judgments
for insert
with check (auth.role() = 'service_role');

-- Limit updates to the service worker role.
create policy judgments_update_service on public.judgments
for update
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');

-- Limit deletes to the service worker role.
create policy judgments_delete_service on public.judgments
for delete
using (auth.role() = 'service_role');

-- judgments.enrichment_runs: only service_role can access the raw queue audit trail.
alter table judgments.enrichment_runs enable row level security;

drop policy if exists service_enrichment_runs_rw on judgments.enrichment_runs;
drop policy if exists enrichment_runs_service_select on judgments.enrichment_runs;
drop policy if exists enrichment_runs_service_insert on judgments.enrichment_runs;
drop policy if exists enrichment_runs_service_update on judgments.enrichment_runs;
drop policy if exists enrichment_runs_service_delete on judgments.enrichment_runs;

-- Restrict reads of individual enrichment runs to the service worker role.
create policy enrichment_runs_service_select on judgments.enrichment_runs
for select
using (auth.role() = 'service_role');

-- Restrict inserts to the service worker role.
create policy enrichment_runs_service_insert on judgments.enrichment_runs
for insert
with check (auth.role() = 'service_role');

-- Restrict updates to the service worker role.
create policy enrichment_runs_service_update on judgments.enrichment_runs
for update
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');

-- Restrict deletes to the service worker role.
create policy enrichment_runs_service_delete on judgments.enrichment_runs
for delete
using (auth.role() = 'service_role');

-- judgments.foil_responses: only service_role should see or mutate raw agency payloads.
alter table judgments.foil_responses enable row level security;

drop policy if exists service_foil_responses_rw on judgments.foil_responses;
drop policy if exists foil_responses_service_select on judgments.foil_responses;
drop policy if exists foil_responses_service_insert on judgments.foil_responses;
drop policy if exists foil_responses_service_update on judgments.foil_responses;
drop policy if exists foil_responses_service_delete on judgments.foil_responses;

-- Restrict reads to the service worker role.
create policy foil_responses_service_select on judgments.foil_responses
for select
using (auth.role() = 'service_role');

-- Restrict inserts to the service worker role.
create policy foil_responses_service_insert on judgments.foil_responses
for insert
with check (auth.role() = 'service_role');

-- Restrict updates to the service worker role.
create policy foil_responses_service_update on judgments.foil_responses
for update
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');

-- Restrict deletes to the service worker role.
create policy foil_responses_service_delete on judgments.foil_responses
for delete
using (auth.role() = 'service_role');

-- Ensure public views execute with caller rights so RLS still applies downstream.
alter view public.foil_responses set (security_invoker = true);
alter view public.v_collectability_snapshot set (security_invoker = true);

-- migrate:down

alter view public.foil_responses set (security_invoker = false);
alter view public.v_collectability_snapshot set (security_invoker = false);

-- Restore legacy judgments policies.
drop policy if exists judgments_select_public on public.judgments;
drop policy if exists judgments_insert_service on public.judgments;
drop policy if exists judgments_update_service on public.judgments;
drop policy if exists judgments_delete_service on public.judgments;

create policy "Allow public read-only access" on public.judgments
for select
using (true);

drop policy if exists enrichment_runs_service_select on judgments.enrichment_runs;
drop policy if exists enrichment_runs_service_insert on judgments.enrichment_runs;
drop policy if exists enrichment_runs_service_update on judgments.enrichment_runs;
drop policy if exists enrichment_runs_service_delete on judgments.enrichment_runs;

create policy service_enrichment_runs_rw on judgments.enrichment_runs
for all
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');

drop policy if exists foil_responses_service_select on judgments.foil_responses;
drop policy if exists foil_responses_service_insert on judgments.foil_responses;
drop policy if exists foil_responses_service_update on judgments.foil_responses;
drop policy if exists foil_responses_service_delete on judgments.foil_responses;

create policy service_foil_responses_rw on judgments.foil_responses
for all
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');
