create schema if not exists judgments;

-- View that surfaces key fields safely from judgments.cases
create or replace view public.v_cases_with_org as
select
    c.case_id,
    c.org_id,
    c.case_number,
    c.source_system,
    c.title,
    c.court_name,
    c.created_at
from judgments.cases as c;

grant select on public.v_cases_with_org to anon, authenticated, service_role;

-- Helper to reload PostgREST schema via HTTP (no psql needed)
create or replace function public.pgrst_reload()
returns void
language sql
security definer
set search_path = public
as $$
  select pg_notify('pgrst', 'reload schema');
$$;

-- Only the service role should be able to call this
revoke all on function public.pgrst_reload() from public;
grant execute on function public.pgrst_reload() to service_role;
