"""Quick schema check for dev environment."""

import os

os.environ.setdefault("SUPABASE_MODE", "dev")

import psycopg

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url())
cur = conn.cursor()

print("=== Job Type Enum Values ===")
cur.execute("SELECT enumlabel FROM pg_enum WHERE enumtypid = 'ops.job_type_enum'::regtype")
for row in cur.fetchall():
    print(f"  - {row[0]}")

print("\n=== ops.intake_logs columns ===")
cur.execute(
    """
    SELECT column_name FROM information_schema.columns
    WHERE table_schema = 'ops' AND table_name = 'intake_logs'
"""
)
for row in cur.fetchall():
    print(f"  - {row[0]}")

print("\n=== analytics.v_enforcement_activity exists? ===")
cur.execute(
    """
    SELECT COUNT(*) FROM information_schema.views
    WHERE table_schema = 'analytics' AND table_name = 'v_enforcement_activity'
"""
)
print(f"  count: {cur.fetchone()[0]}")

print("\n=== public.enforcement_activity_metrics exists? ===")
cur.execute(
    """
    SELECT COUNT(*) FROM information_schema.routines
    WHERE routine_schema = 'public' AND routine_name = 'enforcement_activity_metrics'
"""
)
print(f"  count: {cur.fetchone()[0]}")

conn.close()
