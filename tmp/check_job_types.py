"""Check available job types."""

import os

import psycopg

url = os.environ.get("SUPABASE_DB_URL_DEV", "") or os.environ.get("SUPABASE_DB_URL", "")

with psycopg.connect(url) as conn:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'ops.job_type_enum'::regtype ORDER BY enumsortorder"
        )
        job_types = [r[0] for r in cur.fetchall()]
        print(f"Available job types: {job_types}")
