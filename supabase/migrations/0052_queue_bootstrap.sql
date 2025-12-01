-- migrate:up

create extension if not exists pgmq;

do $$
DECLARE
    v_queue_name text;
BEGIN
    FOR v_queue_name IN SELECT unnest(ARRAY['enrich', 'outreach', 'enforce'])
    LOOP
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pgmq.list_queues() lq
                WHERE lq.queue_name = v_queue_name
            ) THEN
                PERFORM pgmq.create(queue_name => v_queue_name);
            END IF;
        EXCEPTION
            WHEN undefined_function THEN
                RAISE NOTICE 'pgmq.create or pgmq.list_queues not available; queue % not created', v_queue_name;
            WHEN others THEN
                IF SQLSTATE IN ('42710', 'P0001') THEN
                    -- queue already exists or pgmq raised a benign notice
                    NULL;
                ELSE
                    RAISE;
                END IF;
        END;
    END LOOP;
END;
$$;

-- migrate:down

do $$
DECLARE
    v_queue_name text;
BEGIN
    FOR v_queue_name IN SELECT unnest(ARRAY['enrich', 'outreach', 'enforce'])
    LOOP
        BEGIN
            PERFORM pgmq.drop_queue(v_queue_name);
        EXCEPTION
            WHEN undefined_function THEN
                RAISE NOTICE 'pgmq.drop_queue not available; queue % not dropped', v_queue_name;
            WHEN others THEN
                IF SQLSTATE IN ('42P01', '42704', 'P0001') THEN
                    NULL;
                ELSE
                    RAISE;
                END IF;
        END;
    END LOOP;
END;
$$;
