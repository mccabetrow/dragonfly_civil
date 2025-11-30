-- Hard reset of queue RPCs (minus queue_job) to ensure ancillary RPCs exist.
drop function if exists public.dequeue_job (text);
drop function if exists public.dequeue_job ();

drop function if exists public.ack_job (text, bigint);
drop function if exists public.ack_job (text);

create or replace function public.dequeue_job(kind text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
  msg record;
begin
  if kind not in ('enrich', 'outreach', 'enforce') then
    raise exception 'unsupported kind %', kind;
  end if;

  select * into msg from pgmq.read(kind, 1, 30);
  if msg is null then
    return null;
  end if;

  return jsonb_build_object(
    'msg_id', msg.msg_id,
    'read_ct', msg.read_ct,
    'vt', msg.vt,
    'body', msg.msg
  );
end;
$$;

grant execute on function public.queue_job(text, text, jsonb) to service_role;
grant execute on function public.dequeue_job(text) to service_role;
create or replace function public.ack_job(kind text, msg_id bigint)
returns void
language plpgsql
security definer
set search_path = public, pg_temp
as $$
begin
  if kind not in ('enrich', 'outreach', 'enforce') then
    raise exception 'unsupported kind %', kind;
  end if;

  perform pgmq.ack(kind, msg_id);
end;
$$;

grant execute on function public.ack_job(text, bigint) to service_role;

-- migrate:down

revoke execute on function public.ack_job(text, bigint) from service_role;
revoke execute on function public.dequeue_job(text) from service_role;

drop function if exists public.ack_job (text, bigint);
drop function if exists public.dequeue_job (text);
