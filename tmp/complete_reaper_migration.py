"""Complete the reaper heartbeat migration - final steps."""

import os

import psycopg
from psycopg.rows import dict_row

dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
if not dsn:
    print("❌ SUPABASE_MIGRATE_DB_URL not set")
    exit(1)

conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

# Drop and recreate the view
print("Dropping old v_reaper_status view...")
conn.execute("DROP VIEW IF EXISTS ops.v_reaper_status")
print("✅ Old view dropped")

print("Creating ops.v_reaper_status view...")
conn.execute(
    """
    CREATE OR REPLACE VIEW ops.v_reaper_status AS
    SELECT
        last_run_at,
        jobs_reaped,
        run_count,
        status,
        error_message,
        EXTRACT(EPOCH FROM (NOW() - last_run_at)) / 60 AS minutes_since_last_run,
        CASE
            WHEN last_run_at > NOW() - INTERVAL '10 minutes' THEN 'healthy'
            WHEN last_run_at > NOW() - INTERVAL '20 minutes' THEN 'warning'
            ELSE 'critical'
        END AS health_status,
        updated_at
    FROM ops.reaper_heartbeat
    WHERE id = 1
"""
)
print("✅ v_reaper_status view created")

# Grant permissions
print("Granting permissions...")
conn.execute("GRANT SELECT ON ops.reaper_heartbeat TO service_role")
conn.execute("GRANT SELECT ON ops.v_reaper_status TO service_role")
conn.execute("GRANT EXECUTE ON FUNCTION ops.record_reaper_heartbeat TO postgres")
conn.execute("GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTERVAL) TO postgres")
print("✅ Permissions granted")

# Mark migration as applied
print("Marking migration as applied...")
conn.execute(
    """
    INSERT INTO supabase_migrations.schema_migrations (version, name, statements)
    VALUES ('20251231200000', '20251231200000_reaper_heartbeat.sql', 8)
    ON CONFLICT (version) DO NOTHING
"""
)
print("✅ Migration marked as applied")

# Verify
print("\n=== Verification ===")
result = conn.execute("SELECT * FROM ops.reaper_heartbeat")
row = result.fetchone()
print(f"ops.reaper_heartbeat: {row}")

result = conn.execute("SELECT * FROM ops.v_reaper_status")
row = result.fetchone()
print(f"ops.v_reaper_status: {dict(row) if row else 'empty'}")

conn.close()
print("\n✅ All done!")
