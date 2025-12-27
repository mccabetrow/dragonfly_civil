"""Temporary script to fix the reaper_heartbeat migration."""

import os

import psycopg

dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
if not dsn:
    print("❌ SUPABASE_MIGRATE_DB_URL not set")
    exit(1)

conn = psycopg.connect(dsn)

# Apply the COMMENT statement
conn.execute(
    """
    COMMENT ON FUNCTION ops.reap_stuck_jobs(INTERVAL) IS 
    'Reaps stuck jobs and records heartbeat. Monitored by watchdog for staleness.'
"""
)
conn.commit()
print("✅ COMMENT applied")

# Mark the migration as applied in supabase_migrations
conn.execute(
    """
    INSERT INTO supabase_migrations.schema_migrations (version, name, statements)
    VALUES ('20251231200000', '20251231200000_reaper_heartbeat.sql', 1)
    ON CONFLICT (version) DO NOTHING
"""
)
conn.commit()
print("✅ Migration marked as applied")

# Verify the reaper_heartbeat table exists
result = conn.execute("SELECT * FROM ops.reaper_heartbeat")
row = result.fetchone()
print(f"✅ ops.reaper_heartbeat exists: {row}")

# Verify the v_reaper_status view
result = conn.execute("SELECT * FROM ops.v_reaper_status")
row = result.fetchone()
print(f"✅ ops.v_reaper_status: {row}")

conn.close()
print("✅ All done!")
