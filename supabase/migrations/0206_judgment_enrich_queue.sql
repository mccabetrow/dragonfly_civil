-- 0204_judgment_enrich_queue.sql
-- Add judgment_enrich queue for the new enrichment worker pipeline.
-- This queue receives jobs whenever a new judgment is inserted into core_judgments.
-- migrate:up
BEGIN;
-- ----------------------------------------------------------------------------
-- 1. Create the PGMQ queue for judgment enrichment
-- ----------------------------------------------------------------------------
DO $$
DECLARE queue_name text := 'judgment_enrich';
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
-- ----------------------------------------------------------------------------
-- 2. Update queue_job RPC to allow judgment_enrich kind
-- ----------------------------------------------------------------------------
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
    'escalation',
    'judgment_enrich'
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
-- ----------------------------------------------------------------------------
-- 3. Update dequeue_job RPC to allow judgment_enrich kind
-- ----------------------------------------------------------------------------
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
    'escalation',
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
REVOKE ALL ON FUNCTION public.dequeue_job(text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
-- ----------------------------------------------------------------------------
-- 4. Trigger function to enqueue judgment_enrich job on INSERT
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.trg_core_judgments_enqueue_enrich() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$ BEGIN -- Enqueue a judgment_enrich job with the new judgment's ID
    PERFORM pgmq.send(
        'judgment_enrich',
        jsonb_build_object(
            'payload',
            jsonb_build_object('judgment_id', NEW.id),
            'idempotency_key',
            'enrich:' || NEW.id::text,
            'kind',
            'judgment_enrich',
            'enqueued_at',
            timezone('utc', now())
        )
    );
RETURN NEW;
EXCEPTION
WHEN undefined_function THEN -- PGMQ not available; skip silently
RAISE WARNING 'pgmq.send unavailable; judgment_enrich job not queued for %',
NEW.id;
RETURN NEW;
WHEN others THEN -- Log but don't fail the insert
RAISE WARNING 'Failed to enqueue judgment_enrich job for %: %',
NEW.id,
SQLERRM;
RETURN NEW;
END;
$$;
-- ----------------------------------------------------------------------------
-- 5. Attach trigger to core_judgments table
-- ----------------------------------------------------------------------------
DROP TRIGGER IF EXISTS trg_core_judgments_enqueue_enrich ON public.core_judgments;
CREATE TRIGGER trg_core_judgments_enqueue_enrich
AFTER
INSERT ON public.core_judgments FOR EACH ROW EXECUTE FUNCTION public.trg_core_judgments_enqueue_enrich();
COMMENT ON TRIGGER trg_core_judgments_enqueue_enrich ON public.core_judgments IS 'Enqueue a judgment_enrich job for each new judgment inserted.';
COMMIT;
-- migrate:down
BEGIN;
DROP TRIGGER IF EXISTS trg_core_judgments_enqueue_enrich ON public.core_judgments;
DROP FUNCTION IF EXISTS public.trg_core_judgments_enqueue_enrich();
-- Restore previous queue_job without judgment_enrich kind
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
-- Restore previous dequeue_job without judgment_enrich kind
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
COMMIT;