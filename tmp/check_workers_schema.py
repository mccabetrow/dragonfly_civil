"""Quick check for workers schema tables."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url())
cur = conn.execute(
    """
    SELECT table_name 
    FROM information_schema.tables 
    WHERE table_schema = 'workers' 
    ORDER BY table_name
"""
)
tables = [r[0] for r in cur.fetchall()]
print(f"Workers schema tables: {tables}")

# Check heartbeats
cur = conn.execute("SELECT COUNT(*) FROM workers.heartbeats")
count = cur.fetchone()[0]
print(f"Heartbeat records: {count}")

conn.close()
