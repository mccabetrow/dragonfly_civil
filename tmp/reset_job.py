"""Reset the test job to pending status."""

import os
import re

import psycopg

# Use direct URL to bypass pooler issues
url = os.environ.get("SUPABASE_DB_URL_DEV", "") or os.environ.get("SUPABASE_DB_URL", "")
match = re.search(r"postgres\.(\w+):([^@]+)@", url)
if match:
    url = f"postgresql://postgres:{match.group(2)}@db.{match.group(1)}.supabase.co:5432/postgres"
    print(f"Using direct URL to db.{match.group(1)}.supabase.co")

job_id = "86afda67-3c29-4ef6-a37e-53b59e29f746"

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        # Reset the job to pending
        cur.execute(
            """
            UPDATE ops.job_queue 
            SET status = 'pending', 
                locked_at = NULL, 
                attempts = 0,
                last_error = NULL
            WHERE id = %s
            RETURNING id, status
        """,
            (job_id,),
        )
        result = cur.fetchone()
        conn.commit()
        if result:
            print(f"✅ Reset job {result[0]} to status '{result[1]}'")
        else:
            print(f"❌ Job {job_id} not found")
