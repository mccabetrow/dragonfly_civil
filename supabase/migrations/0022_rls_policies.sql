-- 0022_rls_policies.sql
-- Lock down core tables to service role only; app clients use views/RPCs.

-- Enable row level security
alter table judgments.cases enable row level security;
alter table parties.entities enable row level security;

-- Clean up any existing permissive policies that would widen access
-- (idempotent: drop if they exist before recreating desired policies)
do $$
declare
  policy_record record;
begin
  for policy_record in
    select policyname from pg_policies
    where schemaname = 'judgments' and tablename = 'cases' and policyname like 'rls_cases_%'
  loop
    execute format('drop policy %I on judgments.cases', policy_record.policyname);
  end loop;

  for policy_record in
    select policyname from pg_policies
    where schemaname = 'parties' and tablename = 'entities' and policyname like 'rls_entities_%'
  loop
    execute format('drop policy %I on parties.entities', policy_record.policyname);
  end loop;
end $$;

-- Anon/authenticated users must consume views; no direct table access
create policy rls_cases_block_public
on judgments.cases
for all
to anon, authenticated
using (false)
with check (false);

create policy rls_entities_block_public
on parties.entities
for all
to anon, authenticated
using (false)
with check (false);

-- Service role retains full control via permissive policies
create policy rls_cases_service_role
on judgments.cases
for all
to service_role
using (true)
with check (true);

create policy rls_entities_service_role
on parties.entities
for all
to service_role
using (true)
with check (true);

comment on policy rls_cases_block_public on judgments.cases is 'App clients must read via public views; writes go through RPCs.';
comment on policy rls_entities_block_public on parties.entities is 'App clients must read via public views; writes go through RPCs.';

