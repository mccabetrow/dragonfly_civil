"""Get spawn_enforcement_flow definition from dev."""

import os
import sys

os.environ["SUPABASE_MODE"] = "dev"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg

from src.supabase_client import get_supabase_db_url

dsn = get_supabase_db_url()
conn = psycopg.connect(dsn)
cur = conn.cursor()

# Get spawn_enforcement_flow definition
print("=== SPAWN ENFORCEMENT FLOW DEFINITION ===")
cur.execute("SELECT pg_get_functiondef('public.spawn_enforcement_flow(text, text)'::regprocedure)")
print(cur.fetchone()[0])

conn.close()
