"""Check ops schema functions."""

import os

import psycopg
from psycopg.rows import dict_row

dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
if not dsn:
    print("❌ SUPABASE_MIGRATE_DB_URL not set")
    exit(1)

conn = psycopg.connect(dsn, row_factory=dict_row)

# Check existing reap functions
result = conn.execute(
    """
    SELECT 
        proname as name,
        pg_get_function_identity_arguments(oid) as args,
        prosrc as source_preview
    FROM pg_proc 
    WHERE proname LIKE '%reap%'
    AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'ops')
"""
)
for row in result:
    print(f"\n=== {row['name']}({row['args']}) ===")
    # print(row['source_preview'][:200] if row['source_preview'] else 'N/A')

# Check reaper_heartbeat table
result = conn.execute(
    """
    SELECT COUNT(*) as count FROM information_schema.tables 
    WHERE table_schema = 'ops' AND table_name = 'reaper_heartbeat'
"""
)
row = result.fetchone()
print(f"\n✅ ops.reaper_heartbeat exists: {row['count'] > 0}")

# Check v_reaper_status view
result = conn.execute(
    """
    SELECT COUNT(*) as count FROM information_schema.views 
    WHERE table_schema = 'ops' AND table_name = 'v_reaper_status'
"""
)
row = result.fetchone()
print(f"✅ ops.v_reaper_status exists: {row['count'] > 0}")

conn.close()
