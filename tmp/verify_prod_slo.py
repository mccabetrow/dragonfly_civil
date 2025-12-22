"""Verify PROD SLO views are working."""

import psycopg
from psycopg.rows import dict_row

dsn = "postgresql://postgres:Norwaykmt99!!@db.iaketsyhmqbwaabgykux.supabase.co:5432/postgres"

with psycopg.connect(dsn, row_factory=dict_row) as conn:
    result = conn.execute("SELECT * FROM ops.view_slo_system_health").fetchone()
    print("=== PROD SLO System Health ===")
    print(f"  Overall Status:    {result['overall_status']}")
    print(f"  Queue Depth:       {result['queue_depth']}")
    print(f"  P95 Latency:       {result['p95_latency_minutes']} min")
    print(f"  Freshness SLO:     {result['freshness_slo_pct']}%")
    print(f"  Error Rate:        {result['error_rate_pct']}%")
    print(f"  DLQ Rate:          {result['dlq_rate_percent']}%")
    print(f"  Active Workers:    {result['active_workers']}")
    print(f"  Stuck Jobs:        {result['stuck_jobs']}")
    print()
    print("✅ PROD SLO views operational!")
