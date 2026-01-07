-- 0093_case_copilot_dashboard.sql
-- Surface Case Copilot insights in dashboards and allow operators to queue reruns.
-- migrate:up
BEGIN;
-- Expand queue RPCs to allow case_copilot jobs.
CREATE OR REPLACE FUNCTION public.queue_job(
    payload jsonb
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_body jsonb;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_body := coalesce(payload->'payload', '{}'::jsonb);
IF v_kind IS NULL THEN RAISE EXCEPTION 'queue_job: missing kind in payload';
END IF;
IF v_kind NOT IN ('enrich', 'outreach', 'enforce', 'case_copilot') THEN RAISE EXCEPTION 'queue_job: unsupported kind %',
v_kind;
END IF;
IF v_idempotency_key IS NULL
OR length(v_idempotency_key) = 0 THEN RAISE EXCEPTION 'queue_job: missing idempotency_key';
END IF;
RETURN pgmq.send(
    v_kind,
    jsonb_build_object(
        'payload',
        v_body,
        'idempotency_key',
        v_idempotency_key,
        'kind',
        v_kind,
        'enqueued_at',
        now()
    )
);
END;
$$;
CREATE OR REPLACE FUNCTION public.dequeue_job(
    kind text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
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
-- Latest Case Copilot output per enforcement case.
CREATE OR REPLACE VIEW public.v_case_copilot_latest AS WITH ranked AS (
    SELECT
        l.id,
        l.case_id,
        l.model,
        l.metadata,
        l.created_at,
        row_number() OVER (
            PARTITION BY l.case_id
            ORDER BY
                l.created_at DESC,
                l.id DESC
        ) AS row_num
    FROM public.case_copilot_logs AS l
)

SELECT
    ec.id AS case_id,
    ec.judgment_id,
    ec.current_stage,
    ec.status AS case_status,
    ec.assigned_to,
    r.model,
    r.created_at AS generated_at,
    r.id AS log_id,
    coalesce(ec.case_number, j.case_number) AS case_number,
    r.metadata ->> 'summary' AS summary,
    r.metadata ->> 'risk_comment' AS risk_comment,
    coalesce(actions.actions_array, ARRAY[]::text []) AS recommended_actions,
    r.metadata ->> 'status' AS invocation_status,
    r.metadata ->> 'error' AS error_message,
    r.metadata ->> 'env' AS env,
    r.metadata ->> 'duration_ms' AS duration_ms
FROM ranked AS r
INNER JOIN public.enforcement_cases AS ec ON r.case_id = ec.id
LEFT JOIN public.judgments AS j ON ec.judgment_id = j.id
LEFT JOIN LATERAL (
    SELECT array_agg(elem) AS actions_array
    FROM jsonb_array_elements_text(r.metadata -> 'recommended_actions')
) AS actions ON (r.metadata ? 'recommended_actions')
WHERE r.row_num = 1;
GRANT SELECT ON public.v_case_copilot_latest TO anon,
authenticated,
service_role;
-- RPC to queue a fresh Case Copilot summary for a case.
DROP FUNCTION IF EXISTS public.request_case_copilot (uuid, text);
CREATE OR REPLACE FUNCTION public.request_case_copilot(
    p_case_id uuid, requested_by text DEFAULT NULL
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
pg_temp AS $$
DECLARE v_case record;
v_payload jsonb;
v_key text;
BEGIN IF p_case_id IS NULL THEN RAISE EXCEPTION 'request_case_copilot: case_id is required';
END IF;
SELECT ec.id,
    COALESCE(ec.case_number, j.case_number) AS case_number INTO v_case
FROM public.enforcement_cases ec
    JOIN public.judgments j ON j.id = ec.judgment_id
WHERE ec.id = p_case_id
LIMIT 1;
IF v_case.id IS NULL THEN RAISE EXCEPTION 'request_case_copilot: case % not found',
p_case_id;
END IF;
v_payload := jsonb_build_object(
    'case_id',
    v_case.id::text,
    'case_number',
    v_case.case_number,
    'requested_by',
    NULLIF(trim(coalesce(requested_by, '')), ''),
    'requested_at',
    timezone('utc', now())
);
v_key := format(
    'case_copilot:%s:%s',
    v_case.id,
    encode(extensions.gen_random_bytes(6), 'hex')
);
RETURN public.queue_job(
    jsonb_build_object(
        'kind',
        'case_copilot',
        'idempotency_key',
        v_key,
        'payload',
        v_payload
    )
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(uuid, text) TO anon,
authenticated,
service_role;
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pgmq.list_queues()
    WHERE queue_name = 'case_copilot'
) THEN PERFORM pgmq.create(queue_name => 'case_copilot');
END IF;
END;
$$;
COMMIT;
-- migrate:down
BEGIN;
CREATE OR REPLACE FUNCTION public.queue_job(
    payload jsonb
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_body jsonb;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_body := coalesce(payload->'payload', '{}'::jsonb);
IF v_kind IS NULL THEN RAISE EXCEPTION 'queue_job: missing kind in payload';
END IF;
IF v_kind NOT IN ('enrich', 'outreach', 'enforce') THEN RAISE EXCEPTION 'queue_job: unsupported kind %',
v_kind;
END IF;
IF v_idempotency_key IS NULL
OR length(v_idempotency_key) = 0 THEN RAISE EXCEPTION 'queue_job: missing idempotency_key';
END IF;
RETURN pgmq.send(
    v_kind,
    jsonb_build_object(
        'payload',
        v_body,
        'idempotency_key',
        v_idempotency_key,
        'kind',
        v_kind,
        'enqueued_at',
        now()
    )
);
END;
$$;
CREATE OR REPLACE FUNCTION public.dequeue_job(
    kind text
) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
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
DROP VIEW IF EXISTS public.v_case_copilot_latest;
REVOKE EXECUTE ON FUNCTION public.request_case_copilot(uuid, text)
FROM anon,
authenticated,
service_role;
DROP FUNCTION IF EXISTS public.request_case_copilot (uuid, text);
DO $$ BEGIN BEGIN PERFORM pgmq.drop_queue('case_copilot');
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'pgmq.drop_queue not available; queue case_copilot not dropped';
WHEN others THEN IF SQLSTATE IN ('42P01', '42704', 'P0001') THEN NULL;
ELSE RAISE;
END IF;
END;
END;
$$;
COMMIT;

