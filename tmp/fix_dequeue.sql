CREATE OR REPLACE FUNCTION public.dequeue_job(kind text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    msg record;
BEGIN
    IF kind IS NULL OR length(trim(kind)) = 0 THEN
        RAISE EXCEPTION 'dequeue_job: missing kind';
    END IF;

    IF kind NOT IN ('enrich', 'outreach', 'enforce', 'case_copilot', 'collectability', 'judgment_enrich') THEN
        RAISE EXCEPTION 'dequeue_job: unsupported kind %', kind;
    END IF;

    SELECT * INTO msg FROM pgmq.read(kind, 1, 30);

    IF msg IS NULL THEN
        RETURN NULL;
    END IF;

    RETURN jsonb_build_object(
        'msg_id', msg.msg_id,
        'vt', msg.vt,
        'read_ct', msg.read_ct,
        'enqueued_at', msg.enqueued_at,
        'payload', msg.message,
        'body', msg.message
    );
END;
$$;
