
create extension if not exists pgmq;

-- Best-effort queue bootstrap; tolerate missing pgmq functions
DO $$
DECLARE
  queue_name text;
BEGIN
  FOR queue_name IN SELECT unnest(ARRAY['enrich', 'outreach', 'enforce'])
  LOOP
    BEGIN
      PERFORM pgmq.create_queue(queue_name);
    EXCEPTION
      WHEN undefined_function THEN
        RAISE NOTICE 'pgmq.create_queue not available; queue % not created', queue_name;
      WHEN others THEN
        IF SQLSTATE = '42710' THEN
          -- queue already exists
          NULL;
        ELSE
          RAISE;
        RAISE;
    END;
  END LOOP;
END;
$$;

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
