"""Mark migration as applied."""

import os

import psycopg
from psycopg.rows import dict_row

dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

conn.execute(
    """
    INSERT INTO supabase_migrations.schema_migrations (version, name)
    VALUES ('20251231200000', '20251231200000_reaper_heartbeat.sql')
    ON CONFLICT (version) DO NOTHING
"""
)
print("✅ Migration marked as applied")

# Verify
result = conn.execute("SELECT * FROM ops.reaper_heartbeat")
row = result.fetchone()
print(f"ops.reaper_heartbeat: {row}")

result = conn.execute("SELECT * FROM ops.v_reaper_status")
row = result.fetchone()
print(f"ops.v_reaper_status: {dict(row) if row else 'empty'}")

conn.close()
