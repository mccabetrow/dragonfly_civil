"""Queue a test simplicity_ingest job."""

import json
import os

import psycopg

url = os.environ.get("SUPABASE_DB_URL_DEV", "") or os.environ.get("SUPABASE_DB_URL", "")
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
