"""Apply enforcement engine migration objects and check schema."""

import os

os.environ.setdefault("SUPABASE_MODE", "dev")

import psycopg

from src.supabase_client import get_supabase_db_url

conn = psycopg.connect(get_supabase_db_url())
conn.autocommit = True
cur = conn.cursor()

# Add job_id, level, message, raw_payload to ops.intake_logs if missing
print("=== Adding missing columns to ops.intake_logs ===")
for col, coltype in [
    ("job_id", "UUID"),
    ("level", "TEXT"),
    ("message", "TEXT"),
    ("raw_payload", "JSONB"),
]:
    try:
        cur.execute(f"ALTER TABLE ops.intake_logs ADD COLUMN IF NOT EXISTS {col} {coltype}")
        print(f"  Added {col}")
    except Exception as e:
        print(f"  {col}: {e}")

# Create index on job_id if not exists
try:
    cur.execute("CREATE INDEX IF NOT EXISTS idx_intake_logs_job_id ON ops.intake_logs(job_id)")
    print("  Created index on job_id")
except Exception as e:
    print(f"  Index: {e}")

# Create analytics schema if not exists
print("\n=== Creating analytics schema ===")
cur.execute("CREATE SCHEMA IF NOT EXISTS analytics")
cur.execute("GRANT USAGE ON SCHEMA analytics TO authenticated, service_role")

# Create v_enforcement_activity view
print("\n=== Creating analytics.v_enforcement_activity view ===")
cur.execute("DROP VIEW IF EXISTS analytics.v_enforcement_activity CASCADE")
cur.execute(
    """
CREATE VIEW analytics.v_enforcement_activity AS
WITH plan_stats AS (
    SELECT 
        COALESCE(COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours'), 0) AS plans_created_24h,
        COALESCE(COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days'), 0) AS plans_created_7d,
        COUNT(*) AS total_plans
    FROM enforcement.enforcement_plans
),
packet_stats AS (
    SELECT 
        COALESCE(COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '24 hours'), 0) AS packets_generated_24h,
        COALESCE(COUNT(*) FILTER (WHERE created_at >= NOW() - INTERVAL '7 days'), 0) AS packets_generated_7d,
        COUNT(*) AS total_packets
    FROM enforcement.draft_packets
),
worker_stats AS (
    SELECT 
        COALESCE(COUNT(*) FILTER (WHERE status::text = 'processing' AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting')), 0) AS active_workers,
        COALESCE(COUNT(*) FILTER (WHERE status::text = 'pending' AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting')), 0) AS pending_jobs,
        COALESCE(COUNT(*) FILTER (WHERE status::text = 'completed' AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting') AND updated_at >= NOW() - INTERVAL '24 hours'), 0) AS completed_24h,
        COALESCE(COUNT(*) FILTER (WHERE status::text = 'failed' AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting') AND updated_at >= NOW() - INTERVAL '24 hours'), 0) AS failed_24h
    FROM ops.job_queue
)
SELECT 
    ps.plans_created_24h::INTEGER,
    ps.plans_created_7d::INTEGER,
    ps.total_plans::INTEGER,
    pk.packets_generated_24h::INTEGER,
    pk.packets_generated_7d::INTEGER,
    pk.total_packets::INTEGER,
    ws.active_workers::INTEGER,
    ws.pending_jobs::INTEGER,
    ws.completed_24h::INTEGER,
    ws.failed_24h::INTEGER,
    NOW() AS generated_at
FROM plan_stats ps
CROSS JOIN packet_stats pk
CROSS JOIN worker_stats ws
"""
)
print("  Created view")

cur.execute("GRANT SELECT ON analytics.v_enforcement_activity TO authenticated, service_role")

# Create RPC function
print("\n=== Creating public.enforcement_activity_metrics RPC ===")
cur.execute("DROP FUNCTION IF EXISTS public.enforcement_activity_metrics() CASCADE")
cur.execute(
    """
CREATE FUNCTION public.enforcement_activity_metrics()
RETURNS TABLE (
    plans_created_24h INTEGER,
    plans_created_7d INTEGER,
    total_plans INTEGER,
    packets_generated_24h INTEGER,
    packets_generated_7d INTEGER,
    total_packets INTEGER,
    active_workers INTEGER,
    pending_jobs INTEGER,
    completed_24h INTEGER,
    failed_24h INTEGER,
    generated_at TIMESTAMPTZ
)
LANGUAGE SQL STABLE SECURITY DEFINER
AS $$
SELECT * FROM analytics.v_enforcement_activity LIMIT 1;
$$
"""
)
print("  Created function")

cur.execute(
    "GRANT EXECUTE ON FUNCTION public.enforcement_activity_metrics() TO authenticated, service_role"
)

# Verify
print("\n=== Verification ===")
cur.execute("SELECT enumlabel FROM pg_enum WHERE enumtypid = 'ops.job_type_enum'::regtype")
print(f"Job types: {[r[0] for r in cur.fetchall()]}")

cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_schema = 'ops' AND table_name = 'intake_logs'"
)
print(f"intake_logs columns: {[r[0] for r in cur.fetchall()]}")

cur.execute(
    "SELECT COUNT(*) FROM information_schema.views WHERE table_schema = 'analytics' AND table_name = 'v_enforcement_activity'"
)
print(f"v_enforcement_activity exists: {cur.fetchone()[0] == 1}")

cur.execute(
    "SELECT COUNT(*) FROM information_schema.routines WHERE routine_schema = 'public' AND routine_name = 'enforcement_activity_metrics'"
)
print(f"enforcement_activity_metrics exists: {cur.fetchone()[0] == 1}")

conn.close()
print("\nDone!")
