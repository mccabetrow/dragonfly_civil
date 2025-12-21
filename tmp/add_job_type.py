"""Apply migrations via direct database connection (bypasses pooler issues)."""

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

# Add simplicity_ingest job type
add_enum_sql = """
DO $$ BEGIN
    ALTER TYPE ops.job_type_enum ADD VALUE IF NOT EXISTS 'simplicity_ingest';
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
"""

with psycopg.connect(direct_url) as conn:
    conn.autocommit = True  # Required for ALTER TYPE
    with conn.cursor() as cur:
        cur.execute(add_enum_sql)
        print("✅ Added 'simplicity_ingest' to ops.job_type_enum")

        # Verify it was added
        cur.execute(
            "SELECT enumlabel FROM pg_enum WHERE enumtypid = 'ops.job_type_enum'::regtype ORDER BY enumsortorder"
        )
        job_types = [r[0] for r in cur.fetchall()]
        print(f"   Job types now: {job_types}")
