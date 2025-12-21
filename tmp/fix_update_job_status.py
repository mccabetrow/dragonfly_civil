"""Fix the update_job_status RPC to properly cast status enum."""

import os
import re

import psycopg

# Use direct URL to bypass pooler issues
url = os.environ.get("SUPABASE_DB_URL_DEV", "") or os.environ.get("SUPABASE_DB_URL", "")
match = re.search(r"postgres\.(\w+):([^@]+)@", url)
if match:
    url = f"postgresql://postgres:{match.group(2)}@db.{match.group(1)}.supabase.co:5432/postgres"
    print(f"Using direct URL to db.{match.group(1)}.supabase.co")

sql = """
-- Drop and recreate to fix the return type issue
DROP FUNCTION IF EXISTS ops.update_job_status(uuid, text, text);

CREATE FUNCTION ops.update_job_status(
    p_job_id uuid,
    p_status text,
    p_error text DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ops, public
AS $$
BEGIN
    UPDATE ops.job_queue
    SET status = p_status::ops.job_status_enum,  -- Cast to enum
        locked_at = CASE
            WHEN p_status IN ('completed', 'failed') THEN NULL
            ELSE locked_at
        END,
        last_error = COALESCE(LEFT(p_error, 2000), last_error),
        updated_at = now()
    WHERE id = p_job_id;
END;
$$;

COMMENT ON FUNCTION ops.update_job_status IS 'Update job status securely via RPC. Casts status to enum.';

-- Ensure grants are in place
GRANT EXECUTE ON FUNCTION ops.update_job_status(uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION ops.update_job_status(uuid, text, text) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.update_job_status(uuid, text, text) TO dragonfly_app;
"""

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()
        print("✅ Fixed update_job_status to cast status to enum")
