-- 0061_foil_responses_perms.sql
-- Broaden read access to FOIL responses for internal dashboard roles.

-- migrate:up

grant select on public.foil_responses to anon;
grant select on public.foil_responses to authenticated;
grant select on public.foil_responses to service_role;

-- migrate:down

revoke select on public.foil_responses from anon;
revoke select on public.foil_responses from authenticated;
