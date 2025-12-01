-- 0109_queue_case_copilot.sql
-- Add case_copilot queue support to dequeue_job.
-- migrate:up
BEGIN;
DO $$ BEGIN IF to_regclass('pgmq.q_case_copilot') IS NULL THEN PERFORM pgmq.create('case_copilot');
END IF;
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'pgmq.create missing; ensure queue % exists manually',
'case_copilot';
END;
$$;
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE msg record;
BEGIN IF kind IS NULL
OR length(trim(kind)) = 0 THEN RAISE EXCEPTION 'dequeue_job: missing kind';
END IF;
IF kind NOT IN ('enrich', 'outreach', 'enforce', 'case_copilot') THEN RAISE EXCEPTION 'dequeue_job: unsupported kind %',
kind;
END IF;
SELECT * INTO msg
FROM pgmq.read(kind, 1, 30);
IF msg IS NULL THEN RETURN NULL;
END IF;
RETURN jsonb_build_object(
    'msg_id',
    msg.msg_id,
    'vt',
    msg.vt,
    'read_ct',
    msg.read_ct,
    'enqueued_at',
    msg.enqueued_at,
    'payload',
    msg.message,
    'body',
    msg.message
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
COMMIT;
-- migrate:down
BEGIN;
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE msg record;
BEGIN IF kind IS NULL
OR length(trim(kind)) = 0 THEN RAISE EXCEPTION 'dequeue_job: missing kind';
END IF;
IF kind NOT IN ('enrich', 'outreach', 'enforce') THEN RAISE EXCEPTION 'dequeue_job: unsupported kind %',
kind;
END IF;
SELECT * INTO msg
FROM pgmq.read(kind, 1, 30);
IF msg IS NULL THEN RETURN NULL;
END IF;
RETURN jsonb_build_object(
    'msg_id',
    msg.msg_id,
    'vt',
    msg.vt,
    'read_ct',
    msg.read_ct,
    'enqueued_at',
    msg.enqueued_at,
    'payload',
    msg.message,
    'body',
    msg.message
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
COMMIT;