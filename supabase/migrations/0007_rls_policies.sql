create or replace function public.current_app_role()
returns text
language sql
stable
as $$
  select coalesce(current_setting('request.jwt.claims', true)::jsonb->>'role', 'anonymous');
$$;

-- reinforce row level policies by restricting write access
-- judgments.cases
alter table judgments.cases enable row level security;
drop policy if exists insert_cases_service on judgments.cases;
drop policy if exists update_cases_service on judgments.cases;
drop policy if exists delete_cases_service on judgments.cases;
create policy insert_cases_service on judgments.cases
for insert
with check (auth.role() = 'service_role');
create policy update_cases_service on judgments.cases
for update
using (auth.role() = 'service_role')
with check (auth.role() = 'service_role');
create policy delete_cases_service on judgments.cases
for delete
using (auth.role() = 'service_role');

-- parties.entities
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'parties' and table_name = 'entities'
  ) then
    alter table parties.entities enable row level security;
    drop policy if exists insert_entities_service on parties.entities;
    drop policy if exists update_entities_service on parties.entities;
    drop policy if exists delete_entities_service on parties.entities;
    create policy insert_entities_service on parties.entities
      for insert
      with check (auth.role() = 'service_role');
    create policy update_entities_service on parties.entities
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_entities_service on parties.entities
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- parties.roles
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'parties' and table_name = 'roles'
  ) then
    alter table parties.roles enable row level security;
    drop policy if exists insert_roles_service on parties.roles;
    drop policy if exists update_roles_service on parties.roles;
    drop policy if exists delete_roles_service on parties.roles;
    create policy insert_roles_service on parties.roles
      for insert
      with check (auth.role() = 'service_role');
    create policy update_roles_service on parties.roles
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_roles_service on parties.roles
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- enrichment.contacts
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'enrichment' and table_name = 'contacts'
  ) then
    alter table enrichment.contacts enable row level security;
    drop policy if exists insert_contacts_service on enrichment.contacts;
    drop policy if exists update_contacts_service on enrichment.contacts;
    drop policy if exists delete_contacts_service on enrichment.contacts;
    create policy insert_contacts_service on enrichment.contacts
      for insert
      with check (auth.role() = 'service_role');
    create policy update_contacts_service on enrichment.contacts
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_contacts_service on enrichment.contacts
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- enrichment.assets
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'enrichment' and table_name = 'assets'
  ) then
    alter table enrichment.assets enable row level security;
    drop policy if exists insert_assets_service on enrichment.assets;
    drop policy if exists update_assets_service on enrichment.assets;
    drop policy if exists delete_assets_service on enrichment.assets;
    create policy insert_assets_service on enrichment.assets
      for insert
      with check (auth.role() = 'service_role');
    create policy update_assets_service on enrichment.assets
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_assets_service on enrichment.assets
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- enrichment.collectability
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'enrichment' and table_name = 'collectability'
  ) then
    alter table enrichment.collectability enable row level security;
    drop policy if exists insert_collectability_service on enrichment.collectability;
    drop policy if exists update_collectability_service on enrichment.collectability;
    drop policy if exists delete_collectability_service on enrichment.collectability;
    create policy insert_collectability_service on enrichment.collectability
      for insert
      with check (auth.role() = 'service_role');
    create policy update_collectability_service on enrichment.collectability
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_collectability_service on enrichment.collectability
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- outreach.cadences
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'outreach' and table_name = 'cadences'
  ) then
    alter table outreach.cadences enable row level security;
    drop policy if exists insert_cadences_service on outreach.cadences;
    drop policy if exists update_cadences_service on outreach.cadences;
    drop policy if exists delete_cadences_service on outreach.cadences;
    create policy insert_cadences_service on outreach.cadences
      for insert
      with check (auth.role() = 'service_role');
    create policy update_cadences_service on outreach.cadences
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_cadences_service on outreach.cadences
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- outreach.attempts
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'outreach' and table_name = 'attempts'
  ) then
    alter table outreach.attempts enable row level security;
    drop policy if exists insert_attempts_service on outreach.attempts;
    drop policy if exists update_attempts_service on outreach.attempts;
    drop policy if exists delete_attempts_service on outreach.attempts;
    create policy insert_attempts_service on outreach.attempts
      for insert
      with check (auth.role() = 'service_role');
    create policy update_attempts_service on outreach.attempts
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_attempts_service on outreach.attempts
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- intake.esign
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'intake' and table_name = 'esign'
  ) then
    alter table intake.esign enable row level security;
    drop policy if exists insert_esign_service on intake.esign;
    drop policy if exists update_esign_service on intake.esign;
    drop policy if exists delete_esign_service on intake.esign;
    create policy insert_esign_service on intake.esign
      for insert
      with check (auth.role() = 'service_role');
    create policy update_esign_service on intake.esign
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_esign_service on intake.esign
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- enforcement.actions
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'enforcement' and table_name = 'actions'
  ) then
    alter table enforcement.actions enable row level security;
    drop policy if exists insert_actions_service on enforcement.actions;
    drop policy if exists update_actions_service on enforcement.actions;
    drop policy if exists delete_actions_service on enforcement.actions;
    create policy insert_actions_roles on enforcement.actions
      for insert
      with check (public.current_app_role() in ('enforcer', 'finance', 'service_role'));
    create policy update_actions_roles on enforcement.actions
      for update
      using (public.current_app_role() in ('enforcer', 'finance', 'service_role'))
      with check (public.current_app_role() in ('enforcer', 'finance', 'service_role'));
    create policy delete_actions_service on enforcement.actions
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- finance.trust_txns
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'finance' and table_name = 'trust_txns'
  ) then
    alter table finance.trust_txns enable row level security;
    drop policy if exists insert_trust_txns_service on finance.trust_txns;
    drop policy if exists update_trust_txns_service on finance.trust_txns;
    drop policy if exists delete_trust_txns_service on finance.trust_txns;
    create policy insert_trust_txns_roles on finance.trust_txns
      for insert
      with check (public.current_app_role() in ('enforcer', 'finance', 'service_role'));
    create policy update_trust_txns_roles on finance.trust_txns
      for update
      using (public.current_app_role() in ('enforcer', 'finance', 'service_role'))
      with check (public.current_app_role() in ('enforcer', 'finance', 'service_role'));
    create policy delete_trust_txns_service on finance.trust_txns
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

-- ops.runs
do $$
begin
  if exists (
    select 1 from information_schema.tables
    where table_schema = 'ops' and table_name = 'runs'
  ) then
    alter table ops.runs enable row level security;
    drop policy if exists insert_runs_service on ops.runs;
    drop policy if exists update_runs_service on ops.runs;
    drop policy if exists delete_runs_service on ops.runs;
    create policy insert_runs_service on ops.runs
      for insert
      with check (auth.role() = 'service_role');
    create policy update_runs_service on ops.runs
      for update
      using (auth.role() = 'service_role')
      with check (auth.role() = 'service_role');
    create policy delete_runs_service on ops.runs
      for delete
      using (auth.role() = 'service_role');
  end if;
end $$;

do $$
begin
  if exists (
    select 1 from pg_proc p
    join pg_namespace n on n.oid = p.pronamespace
    where n.nspname = 'enrichment'
      and p.proname = 'upsert_enrichment_bundle'
      and pg_get_function_identity_arguments(p.oid) = 'jsonb'
  ) then
    grant execute on function enrichment.upsert_enrichment_bundle(jsonb) to anon, authenticated, service_role;
  end if;
end $$;
