"""Queue a test simplicity_ingest job using direct DB connection."""

import json
import os
import re

import psycopg

# Use direct URL to bypass pooler issues
url = os.environ.get("SUPABASE_DB_URL_DEV", "") or os.environ.get("SUPABASE_DB_URL", "")
match = re.search(r"postgres\.(\w+):([^@]+)@", url)
if match:
    url = f"postgresql://postgres:{match.group(2)}@db.{match.group(1)}.supabase.co:5432/postgres"
    print(f"Using direct URL to db.{match.group(1)}.supabase.co")

print("Queueing test simplicity_ingest job...")

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        # Queue a test job via the RPC
        cur.execute(
            """
            SELECT ops.queue_job(
                'simplicity_ingest',
                %s::jsonb
            )
        """,
            (
                json.dumps(
                    {
                        "file_path": "data_in/simplicity_sample.csv",
                        "batch_name": "smoke-test",
                        "source_reference": "smoke-test",
                    }
                ),
            ),
        )
        result = cur.fetchone()
        conn.commit()
        print(f"✅ Job queued with ID: {result[0]}")
