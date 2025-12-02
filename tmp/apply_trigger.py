"""Apply trigger function and trigger for judgment enrichment."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["SUPABASE_MODE"] = "dev"

from src.supabase_client import get_supabase_db_url
import psycopg

conn = psycopg.connect(get_supabase_db_url("dev"))
cur = conn.cursor()

# Create the trigger function
sql_func = """
CREATE OR REPLACE FUNCTION public.trg_core_judgments_enqueue_enrich()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
BEGIN
    PERFORM pgmq.send(
        'judgment_enrich',
        jsonb_build_object(
            'payload', jsonb_build_object('judgment_id', NEW.id),
            'idempotency_key', 'enrich:' || NEW.id::text,
            'kind', 'judgment_enrich',
            'enqueued_at', timezone('utc', now())
        )
    );
    RETURN NEW;
EXCEPTION
    WHEN undefined_function THEN
        RAISE WARNING 'pgmq.send unavailable; judgment_enrich job not queued for %', NEW.id;
        RETURN NEW;
    WHEN others THEN
        RAISE WARNING 'Failed to enqueue judgment_enrich job for %: %', NEW.id, SQLERRM;
        RETURN NEW;
END;
$$;
"""
cur.execute(sql_func)
conn.commit()
print("Trigger function created")

# Create the trigger
cur.execute(
    "DROP TRIGGER IF EXISTS trg_core_judgments_enqueue_enrich ON public.core_judgments"
)
cur.execute(
    "CREATE TRIGGER trg_core_judgments_enqueue_enrich AFTER INSERT ON public.core_judgments FOR EACH ROW EXECUTE FUNCTION public.trg_core_judgments_enqueue_enrich()"
)
conn.commit()
print("Trigger created")

# Verify
cur.execute("SELECT tgname FROM pg_trigger WHERE tgname LIKE '%enrich%'")
print("Triggers:", [r[0] for r in cur.fetchall()])
