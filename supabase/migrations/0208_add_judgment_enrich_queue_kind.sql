-- 20251201054639_add_judgment_enrich_queue_kind.sql
-- Add 'judgment_enrich' to the allowed queue kinds in queue_job and dequeue_job RPCs.
-- This enables the new enrichment pipeline that uses core_judgments instead of legacy judgments.
-- migrate:up
-- Update queue_job to accept 'judgment_enrich' kind
CREATE OR REPLACE FUNCTION public.queue_job(payload jsonb) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_inner_payload jsonb;
v_msg_id bigint;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_inner_payload := payload->'payload';
IF v_kind IS NULL
OR length(trim(v_kind)) = 0 THEN RAISE EXCEPTION 'queue_job: missing kind';
END IF;
IF v_idempotency_key IS NULL
OR length(trim(v_idempotency_key)) = 0 THEN RAISE EXCEPTION 'queue_job: missing idempotency_key';
END IF;
-- Add 'judgment_enrich' to the allowed kinds
IF v_kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability',
    'judgment_enrich'
) THEN RAISE EXCEPTION 'queue_job: unsupported kind %',
v_kind;
END IF;
SELECT pgmq.send(
        v_kind,
        jsonb_build_object(
            'kind',
            v_kind,
            'idempotency_key',
            v_idempotency_key,
            'payload',
            COALESCE(v_inner_payload, '{}'::jsonb),
            'enqueued_at',
            now()
        )
    ) INTO v_msg_id;
RETURN v_msg_id;
END;
$$;
-- Update dequeue_job to accept 'judgment_enrich' kind
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE msg record;
BEGIN IF kind IS NULL
OR length(trim(kind)) = 0 THEN RAISE EXCEPTION 'dequeue_job: missing kind';
END IF;
-- Add 'judgment_enrich' to the allowed kinds
IF kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability',
    'judgment_enrich'
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
-- Ensure grants are in place
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
-- migrate:down
-- Revert to previous version without 'judgment_enrich'
CREATE OR REPLACE FUNCTION public.queue_job(payload jsonb) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_inner_payload jsonb;
v_msg_id bigint;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_inner_payload := payload->'payload';
IF v_kind IS NULL
OR length(trim(v_kind)) = 0 THEN RAISE EXCEPTION 'queue_job: missing kind';
END IF;
IF v_idempotency_key IS NULL
OR length(trim(v_idempotency_key)) = 0 THEN RAISE EXCEPTION 'queue_job: missing idempotency_key';
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
SELECT pgmq.send(
        v_kind,
        jsonb_build_object(
            'kind',
            v_kind,
            'idempotency_key',
            v_idempotency_key,
            'payload',
            COALESCE(v_inner_payload, '{}'::jsonb),
            'enqueued_at',
            now()
        )
    ) INTO v_msg_id;
RETURN v_msg_id;
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