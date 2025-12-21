"""Apply the claim_pending_job fix via direct database connection."""

import os
import re

import psycopg

# Get and transform URL to direct connection
url = os.environ.get("SUPABASE_DB_URL_DEV", "") or os.environ.get("SUPABASE_DB_URL", "")
match = re.search(r"postgres\.(\w+):([^@]+)@", url)
if not match:
    raise RuntimeError("Could not parse DB URL")

direct_url = f"postgresql://postgres:{match.group(2)}@db.{match.group(1)}.supabase.co:5432/postgres"
print(f"Connecting via direct URL to db.{match.group(1)}.supabase.co...")

sql = """
CREATE OR REPLACE FUNCTION ops.claim_pending_job(
        p_job_types text [],
        p_lock_timeout_minutes integer DEFAULT 30
    ) RETURNS TABLE (
        job_id uuid,
        job_type text,
        payload jsonb,
        attempts integer,
        created_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops, public AS $$ BEGIN RETURN QUERY
UPDATE ops.job_queue jq
SET status = 'processing',
    locked_at = now(),
    attempts = jq.attempts + 1
WHERE jq.id = (
        SELECT inner_jq.id
        FROM ops.job_queue inner_jq
        WHERE inner_jq.job_type::text = ANY(p_job_types)
            AND inner_jq.status::text = 'pending'
            AND (
                inner_jq.locked_at IS NULL
                OR inner_jq.locked_at < now() - (p_lock_timeout_minutes || ' minutes')::interval
            )
        ORDER BY inner_jq.created_at ASC
        LIMIT 1 FOR
        UPDATE SKIP LOCKED
    )
RETURNING jq.id,
    jq.job_type::text,
    jq.payload,
    jq.attempts,
    jq.created_at;
END;
$$;
"""

with psycopg.connect(direct_url) as conn:
    with conn.cursor() as cur:
        cur.execute(sql)
        conn.commit()
        print("✅ Function ops.claim_pending_job updated successfully!")
