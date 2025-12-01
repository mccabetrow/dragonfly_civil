-- This rollup re-applies grants and queue RPC definitions to avoid conflicts with the retired 0010 migration.
-- migrate:up

create extension if not exists pgmq;

do $$
declare
  queue_name text;
begin
  for queue_name in select unnest(array['enrich', 'outreach', 'enforce'])
  loop
    begin
      perform pgmq.create_queue(queue_name);
    exception
      when undefined_function then
        raise notice 'pgmq.create_queue not available; queue % not created', queue_name;
      when others then
        if sqlstate = '42710' then
          null;
        else
          raise;
        end if;
    end;
  end loop;
end;
$$;

grant usage on schema public to service_role;
grant all on table public.judgments to service_role;

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
    'payload', msg.msg
  );
end;
$$;
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

drop function if exists public.dequeue_job (text);
drop function if exists public.ack_job (text, bigint);
