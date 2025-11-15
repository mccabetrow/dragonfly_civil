-- migrate:up
grant usage on schema public to service_role;
grant all on table public.judgments to service_role;

-- optional read for anon/authenticated (omit if not desired)
-- grant select on table public.judgments to anon, authenticated;

-- migrate:down
revoke all on table public.judgments from service_role;
revoke usage on schema public from service_role;
