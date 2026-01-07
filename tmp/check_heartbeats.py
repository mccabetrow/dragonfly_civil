#!/usr/bin/env python3
"""Quick script to check workers.heartbeats schema."""
import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url(), row_factory=dict_row)
cur = conn.cursor()

cur.execute(
    "SELECT column_name, data_type FROM information_schema.columns "
    "WHERE table_schema = 'workers' AND table_name = 'heartbeats' "
    "ORDER BY ordinal_position"
)
print("workers.heartbeats columns:")
for r in cur.fetchall():
    print(f"  {r['column_name']}: {r['data_type']}")

conn.close()
