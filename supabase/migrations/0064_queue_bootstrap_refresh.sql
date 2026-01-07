-- 0064_queue_bootstrap_refresh.sql
-- Refresh queue bootstrap logic to support newer pgmq function names.

-- migrate:up

create extension if not exists pgmq;

do $$
declare
    queue_name text;
    queue_regclass text;
begin
    for queue_name in select unnest(array['enrich', 'outreach', 'enforce']) loop
        queue_regclass := format('pgmq.q_%I', queue_name);
        if to_regclass(queue_regclass) is not null then
            continue;
        end if;

        begin
            perform pgmq.create(queue_name);
        exception
            when undefined_function then
                begin
                    perform pgmq.create_queue(queue_name);
                exception
                    when undefined_function then
                        raise notice 'pgmq.create and pgmq.create_queue unavailable; queue % not created', queue_name;
                        continue;
                end;
            when others then
                if sqlstate in ('42710', '42P07') then
                    continue;
                else
                    raise;
                end if;
        end;

        if to_regclass(queue_regclass) is null then
            raise notice 'Queue % still missing after create attempt', queue_name;
        end if;
    end loop;
end;
$$;

-- migrate:down

-- No-op: queues are durable and safe to keep in place.

