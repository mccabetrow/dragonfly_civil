-- 0062_queue_dequeue_job.sql
-- Reinstate dequeue_job RPC so worker queues can drain via PostgREST.

-- migrate:up

create extension if not exists pgmq;

create or replace function public.dequeue_job(kind text)
returns jsonb
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    msg record;
begin
    if kind is null or length(trim(kind)) = 0 then
        raise exception 'dequeue_job: missing kind';
    end if;

    if kind not in ('enrich', 'outreach', 'enforce') then
        raise exception 'dequeue_job: unsupported kind %', kind;
    end if;

    select *
      into msg
      from pgmq.read(kind, 1, 30);

    if msg is null then
        return null;
    end if;

    return jsonb_build_object(
        'msg_id', msg.msg_id,
        'vt', msg.vt,
        'read_ct', msg.read_ct,
        'payload', msg.msg,
        'body', msg.msg
    );
end;
$$;

grant execute on function public.dequeue_job(text) to service_role;

-- migrate:down

revoke execute on function public.dequeue_job(text) from service_role;
drop function if exists public.dequeue_job (text);

