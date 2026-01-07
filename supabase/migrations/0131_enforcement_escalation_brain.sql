-- 0131_enforcement_escalation_brain.sql
-- Introduce the escalation queue, RPC, and supporting functions for Enforcement Brain v1.
BEGIN;
-- Ensure the escalation queue exists alongside existing worker queues.
DO $$
DECLARE queue_name text := 'escalation';
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
-- Allow queue_job/dequeue_job to operate on the new escalation queue.
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
    'collectability',
    'escalation'
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
        timezone('utc', now())
    )
);
END;
$$;
REVOKE ALL ON FUNCTION public.queue_job(jsonb)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO anon;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO service_role;
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
    'collectability',
    'escalation'
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
REVOKE ALL ON FUNCTION public.dequeue_job(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
-- RPC to surface enforcement signals for a case.
CREATE OR REPLACE FUNCTION public.evaluate_enforcement_path(p_case_id uuid) RETURNS TABLE (
        case_id uuid,
        judgment_id bigint,
        collectability_score numeric,
        attempts_last_30 integer,
        days_since_last_activity integer,
        evidence_items integer,
        judgment_age_days integer,
        last_activity_at timestamptz,
        last_activity_kind text
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_case record;
v_attempts integer := 0;
v_last_activity timestamptz;
v_last_kind text;
v_days_since integer;
v_evidence_count integer := 0;
v_collectability numeric := 0;
v_age_days integer;
BEGIN
SELECT ec.id AS case_id,
    ec.judgment_id,
    j.case_number,
    jc.collectability_score,
    jc.judgment_date INTO v_case
FROM public.enforcement_cases ec
    JOIN public.judgments j ON j.id = ec.judgment_id
    LEFT JOIN judgments.cases jc ON jc.case_number = j.case_number
WHERE ec.id = p_case_id
LIMIT 1;
IF v_case.case_id IS NULL THEN RAISE EXCEPTION 'enforcement case % not found',
p_case_id USING ERRCODE = 'P0002';
END IF;
v_collectability := COALESCE(v_case.collectability_score, 0);
IF v_case.judgment_date IS NOT NULL THEN v_age_days := GREATEST((CURRENT_DATE - v_case.judgment_date), 0);
END IF;
SELECT COUNT(*) INTO v_attempts
FROM public.enforcement_events e
WHERE e.case_id = v_case.case_id
    AND e.event_date >= timezone('utc', now()) - INTERVAL '30 days'
    AND (
        e.event_type ILIKE 'call%%'
        OR e.event_type ILIKE '%%attempt%%'
        OR e.event_type ILIKE '%%contact%%'
    );
SELECT t.item_kind,
    t.occurred_at INTO v_last_kind,
    v_last_activity
FROM public.v_enforcement_timeline t
WHERE t.case_id = v_case.case_id
ORDER BY t.occurred_at DESC
LIMIT 1;
IF v_last_activity IS NOT NULL THEN v_days_since := GREATEST(
    FLOOR(
        EXTRACT(
            EPOCH
            FROM (timezone('utc', now()) - v_last_activity)
        ) / 86400
    )::integer,
    0
);
END IF;
SELECT COUNT(*) INTO v_evidence_count
FROM public.enforcement_evidence
WHERE case_id = v_case.case_id;
IF v_evidence_count = 0
AND to_regclass('public.evidence_files') IS NOT NULL THEN
SELECT COUNT(*) INTO v_evidence_count
FROM public.evidence_files
WHERE case_id = v_case.case_id;
END IF;
RETURN QUERY
SELECT v_case.case_id,
    v_case.judgment_id,
    v_collectability,
    COALESCE(v_attempts, 0),
    v_days_since,
    COALESCE(v_evidence_count, 0),
    v_age_days,
    v_last_activity,
    v_last_kind;
END;
$$;
REVOKE ALL ON FUNCTION public.evaluate_enforcement_path(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.evaluate_enforcement_path(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.evaluate_enforcement_path(uuid) TO service_role;
COMMIT;
