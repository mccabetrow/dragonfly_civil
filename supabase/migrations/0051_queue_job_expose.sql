-- Recreate queue_job RPC without a down block so PostgREST retains the canonical definition.

-- migrate:up

drop function if exists public.queue_job (text, text, jsonb);
drop function if exists public.queue_job (text, jsonb, text);
drop function if exists public.queue_job (text, jsonb);
drop function if exists public.queue_job (jsonb);

create or replace function public.queue_job(payload jsonb)
returns bigint
language plpgsql
security definer
set search_path = public, pg_temp
as $$
declare
    v_kind            text;
    v_idempotency_key text;
    v_body            jsonb;
begin
    v_kind            := payload->>'kind';
    v_idempotency_key := payload->>'idempotency_key';
    v_body            := coalesce(payload->'payload', '{}'::jsonb);

    if v_kind is null then
        raise exception 'queue_job: missing kind in payload';
    end if;

    if v_kind not in ('enrich', 'outreach', 'enforce') then
        raise exception 'queue_job: unsupported kind %', v_kind;
    end if;

    if v_idempotency_key is null or length(v_idempotency_key) = 0 then
        raise exception 'queue_job: missing idempotency_key';
    end if;

    return pgmq.send(
        v_kind,
        jsonb_build_object(
            'payload',         v_body,
            'idempotency_key', v_idempotency_key,
            'kind',            v_kind,
            'enqueued_at',     now()
        )
    );
end;
$$;

grant execute on function public.queue_job(jsonb) to anon;
grant execute on function public.queue_job(jsonb) to authenticated;
grant execute on function public.queue_job(jsonb) to service_role;

-- migrate:down
-- Intentionally left blank; the RPC must remain available.

