"""Simulate stale worker."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url())
conn.execute(
    """
    UPDATE workers.heartbeats 
    SET status = 'healthy', 
        last_heartbeat_at = now() - INTERVAL '10 minutes'
"""
)
conn.commit()
print("✅ Set worker to STALE (heartbeat 10 minutes ago, status = healthy)")
conn.close()
