-- 0128_collectability_score.sql
-- Launch the Collector Intelligence Engine and expose collectability scores on cases.
-- migrate:up
BEGIN;
ALTER TABLE IF EXISTS public.cases
ADD COLUMN IF NOT EXISTS collectability_score numeric(5, 2);
ALTER TABLE IF EXISTS judgments.cases
ADD COLUMN IF NOT EXISTS collectability_score numeric(5, 2);
DO $$ BEGIN IF to_regclass('public.cases') IS NOT NULL THEN EXECUTE 'UPDATE public.cases SET collectability_score = COALESCE(collectability_score, 0)';
EXECUTE 'ALTER TABLE public.cases ALTER COLUMN collectability_score SET DEFAULT 0';
END IF;
IF to_regclass('judgments.cases') IS NOT NULL THEN
UPDATE judgments.cases
SET collectability_score = COALESCE(collectability_score, 0);
ALTER TABLE judgments.cases
ALTER COLUMN collectability_score
SET DEFAULT 0;
END IF;
END;
$$;
DO $$
DECLARE queue_name text := 'collectability';
queue_regclass text;
BEGIN queue_regclass := format('pgmq.q_%I', queue_name);
IF to_regclass(queue_regclass) IS NULL THEN BEGIN PERFORM pgmq.create(queue_name);
EXCEPTION
WHEN undefined_function THEN BEGIN PERFORM pgmq.create_queue(queue_name);
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'pgmq create functions unavailable; queue % not created',
queue_name;
RETURN;
END;
WHEN others THEN IF SQLSTATE NOT IN ('42710', '42P07') THEN RAISE;
END IF;
END;
END IF;
END;
$$;
CREATE OR REPLACE FUNCTION public.queue_job(payload jsonb) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_body jsonb;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_body := COALESCE(payload->'payload', '{}'::jsonb);
IF v_kind IS NULL THEN RAISE EXCEPTION 'queue_job: missing kind in payload';
END IF;
IF v_kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability'
) THEN RAISE EXCEPTION 'queue_job: unsupported kind %',
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
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE msg record;
BEGIN IF kind IS NULL
OR length(trim(kind)) = 0 THEN RAISE EXCEPTION 'dequeue_job: missing kind';
END IF;
IF kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability'
) THEN RAISE EXCEPTION 'dequeue_job: unsupported kind %',
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
CREATE OR REPLACE FUNCTION public.score_case_collectability(
        p_case_id uuid,
        p_force boolean DEFAULT false,
        p_requested_by text DEFAULT NULL
    ) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_case record;
v_key text;
v_payload jsonb;
BEGIN IF p_case_id IS NULL THEN RAISE EXCEPTION 'score_case_collectability: case_id is required';
END IF;
IF to_regclass('public.cases') IS NOT NULL THEN
SELECT c.id AS case_id,
    COALESCE(c.case_number, j.case_number) AS case_number,
    COALESCE(c.plaintiff_id, j.plaintiff_id) AS plaintiff_id INTO v_case
FROM public.cases c
    LEFT JOIN public.judgments j ON (j.case_number = c.case_number)
WHERE c.id = p_case_id
LIMIT 1;
END IF;
IF v_case.case_id IS NULL THEN
SELECT ec.id AS case_id,
    COALESCE(ec.case_number, j.case_number) AS case_number,
    j.plaintiff_id INTO v_case
FROM public.enforcement_cases ec
    LEFT JOIN public.judgments j ON j.id = ec.judgment_id
WHERE ec.id = p_case_id
LIMIT 1;
END IF;
IF v_case.case_id IS NULL THEN
SELECT c.case_id AS case_id,
    COALESCE(c.case_number, j.case_number) AS case_number,
    j.plaintiff_id INTO v_case
FROM judgments.cases c
    LEFT JOIN public.judgments j ON j.case_number = c.case_number
WHERE c.case_id = p_case_id
LIMIT 1;
END IF;
IF v_case.case_id IS NULL THEN RAISE EXCEPTION 'score_case_collectability: case % not found',
p_case_id USING ERRCODE = 'P0002';
END IF;
IF v_case.plaintiff_id IS NULL THEN RAISE EXCEPTION 'score_case_collectability: plaintiff missing for case %',
v_case.case_id USING ERRCODE = '23502';
END IF;
v_key := format(
    'collectability:%s:%s',
    v_case.case_id,
    encode(extensions.gen_random_bytes(6), 'hex')
);
v_payload := jsonb_build_object(
    'case_id',
    v_case.case_id,
    'case_number',
    v_case.case_number,
    'plaintiff_id',
    v_case.plaintiff_id,
    'force',
    COALESCE(p_force, false),
    'requested_at',
    timezone('utc', now()),
    'requested_by',
    NULLIF(btrim(COALESCE(p_requested_by, '')), '')
);
RETURN public.queue_job(
    jsonb_build_object(
        'kind',
        'collectability',
        'idempotency_key',
        v_key,
        'payload',
        v_payload
    )
);
END;
$$;
REVOKE ALL ON FUNCTION public.score_case_collectability(uuid, boolean, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.score_case_collectability(uuid, boolean, text) TO authenticated,
    service_role;
COMMIT;
