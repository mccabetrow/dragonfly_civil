"""Check heartbeat details."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import psycopg
from psycopg.rows import dict_row

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url(), row_factory=dict_row)
cur = conn.execute(
    """
    SELECT 
        worker_id,
        queue_name,
        hostname,
        version,
        pid,
        status,
        last_heartbeat_at,
        jobs_processed,
        jobs_failed
    FROM workers.heartbeats
    ORDER BY last_heartbeat_at DESC
    LIMIT 5
"""
)

print("Workers Heartbeats:")
print("-" * 80)
for row in cur.fetchall():
    print(f"  Worker ID:   {row['worker_id']}")
    print(f"  Queue:       {row['queue_name']}")
    print(f"  Hostname:    {row['hostname']}")
    print(f"  Version:     {row['version']}")
    print(f"  PID:         {row['pid']}")
    print(f"  Status:      {row['status']}")
    print(f"  Last HB:     {row['last_heartbeat_at']}")
    print(f"  Processed:   {row['jobs_processed']}")
    print(f"  Failed:      {row['jobs_failed']}")
    print("-" * 80)

conn.close()
