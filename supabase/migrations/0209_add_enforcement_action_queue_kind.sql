-- 0209_add_enforcement_action_queue_kind.sql
-- Add 'enforcement_action' to the allowed queue kinds in queue_job and dequeue_job RPCs.
-- This enables the enforcement_action worker to process jobs after enrichment completes.
-- First, ensure the PGMQ queue exists
DO $$ BEGIN IF to_regclass('pgmq.q_enforcement_action') IS NULL THEN BEGIN PERFORM pgmq.create('enforcement_action');
EXCEPTION
WHEN undefined_function THEN BEGIN PERFORM pgmq.create_queue('enforcement_action');
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'pgmq.create and pgmq.create_queue unavailable; queue enforcement_action not created';
WHEN OTHERS THEN IF SQLSTATE IN ('42710', '42P07') THEN NULL;
-- Queue already exists
ELSE RAISE;
END IF;
END;
WHEN OTHERS THEN IF SQLSTATE IN ('42710', '42P07') THEN NULL;
-- Queue already exists
ELSE RAISE;
END IF;
END;
END IF;
END;
$$;
-- Update queue_job to accept 'enforcement_action' kind
CREATE OR REPLACE FUNCTION public.queue_job(payload jsonb) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
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
IF v_kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability',
    'judgment_enrich',
    'enforcement_action'
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
-- Update dequeue_job to accept 'enforcement_action' kind
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
    'judgment_enrich',
    'enforcement_action'
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
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO anon;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
COMMENT ON FUNCTION public.queue_job IS 'Enqueue a job to PGMQ. Supported kinds: enrich, outreach, enforce, case_copilot, collectability, judgment_enrich, enforcement_action.';
COMMENT ON FUNCTION public.dequeue_job IS 'Dequeue a job from PGMQ. Supported kinds: enrich, outreach, enforce, case_copilot, collectability, judgment_enrich, enforcement_action.';