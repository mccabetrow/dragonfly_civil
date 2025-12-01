-- 0068_pgmq_delete_rpc.sql
-- Expose a pgmq delete helper as a PostgREST-compatible RPC.

-- migrate:up

create or replace function public.pgmq_delete(queue_name text, msg_id bigint)
returns boolean
language sql
security definer
set search_path = public, pgmq
as $$
  select pgmq.delete(queue_name, msg_id);
$$;

grant execute on function public.pgmq_delete(text, bigint) to anon;
grant execute on function public.pgmq_delete(text, bigint) to authenticated;
grant execute on function public.pgmq_delete(text, bigint) to service_role;

-- migrate:down

revoke execute on function public.pgmq_delete(text, bigint) from anon;
revoke execute on function public.pgmq_delete(text, bigint) from authenticated;
revoke execute on function public.pgmq_delete(text, bigint) from service_role;

drop function if exists public.pgmq_delete (text, bigint);
