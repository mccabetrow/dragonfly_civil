"""One-time script to add judgment_enrich to dequeue_job RPC."""

import os
import sys

os.environ["SUPABASE_MODE"] = "dev"
sys.path.insert(0, ".")

from src.supabase_client import get_supabase_db_url
import psycopg

sql = """
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $body$
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
$body$;
"""

if __name__ == "__main__":
    db_url = get_supabase_db_url("dev")
    with psycopg.connect(db_url) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()
        print("[OK] dequeue_job function updated to include judgment_enrich")
