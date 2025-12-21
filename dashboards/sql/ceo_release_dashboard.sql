-- ============================================================================
-- CEO Release Dashboard - SLO Status Overview
-- ============================================================================
-- Run this in Supabase SQL Editor for a real-time system health snapshot.
-- Copy/paste directly into the SQL Editor and click "Run".
-- ============================================================================
WITH system_health AS (
    SELECT *
    FROM ops.view_slo_system_health
),

slo_metrics AS (
    SELECT -- Metric 1: Queue Depth
        'Queue Depth' AS metric_name,
        queue_depth::TEXT AS current_value,
        '< 50' AS slo_target,
        CASE
            WHEN queue_depth < 50 THEN 'âœ… HEALTHY'
            WHEN queue_depth < 100 THEN 'âš ï¸\x8f WARNING'
            ELSE 'â\x9dŒ BREACH'
        END AS status,
        1 AS sort_order
    FROM system_health
    UNION ALL
    SELECT
        'P95 Latency (minutes)',
        ROUND(p95_latency_minutes, 2)::TEXT,
        'â‰¤ 10',
        CASE
            WHEN p95_latency_minutes <= 10 THEN 'âœ… HEALTHY'
            WHEN p95_latency_minutes <= 15 THEN 'âš ï¸\x8f WARNING'
            ELSE 'â\x9dŒ BREACH'
        END,
        2
    FROM system_health
    UNION ALL
    SELECT
        'Freshness SLO Compliance',
        freshness_slo_pct::TEXT || '%',
        'â‰¥ 95%',
        CASE
            WHEN freshness_slo_pct >= 95 THEN 'âœ… HEALTHY'
            WHEN freshness_slo_pct >= 90 THEN 'âš ï¸\x8f WARNING'
            ELSE 'â\x9dŒ BREACH'
        END,
        3
    FROM system_health
    UNION ALL
    SELECT
        'Error Rate (24h)',
        ROUND(error_rate_pct, 3)::TEXT || '%',
        '< 1%',
        CASE
            WHEN error_rate_pct < 1 THEN 'âœ… HEALTHY'
            WHEN error_rate_pct < 5 THEN 'âš ï¸\x8f WARNING'
            ELSE 'â\x9dŒ BREACH'
        END,
        4
    FROM system_health
    UNION ALL
    SELECT
        'DLQ Rate (24h)',
        ROUND(dlq_rate_percent, 3)::TEXT || '%',
        '< 1%',
        CASE
            WHEN dlq_rate_percent < 0.5 THEN 'âœ… HEALTHY'
            WHEN dlq_rate_percent < 1.0 THEN 'âš ï¸\x8f WARNING'
            ELSE 'â\x9dŒ BREACH'
        END,
        5
    FROM system_health
    UNION ALL
    SELECT
        'Error Budget Remaining',
        error_budget_remaining_bps::TEXT || ' bps',
        '> 10 bps',
        CASE
            WHEN error_budget_remaining_bps > 50 THEN 'âœ… HEALTHY'
            WHEN error_budget_remaining_bps > 10 THEN 'âš ï¸\x8f WARNING'
            ELSE 'â\x9dŒ BREACH'
        END,
        6
    FROM system_health
    UNION ALL
    SELECT
        'Active Workers',
        active_workers::TEXT,
        'â‰¥ 1',
        CASE
            WHEN active_workers >= 2 THEN 'âœ… HEALTHY'
            WHEN active_workers >= 1 THEN 'âš ï¸\x8f WARNING'
            ELSE 'â\x9dŒ BREACH'
        END,
        7
    FROM system_health
    UNION ALL
    SELECT
        'Dead Workers',
        dead_workers::TEXT,
        '= 0',
        CASE
            WHEN dead_workers = 0 THEN 'âœ… HEALTHY'
            ELSE 'âš ï¸\x8f WARNING'
        END,
        8
    FROM system_health
    UNION ALL
    SELECT
        'Stuck Jobs (>30min)',
        stuck_jobs::TEXT,
        '= 0',
        CASE
            WHEN stuck_jobs = 0 THEN 'âœ… HEALTHY'
            ELSE 'â\x9dŒ BREACH'
        END,
        9
    FROM system_health
    UNION ALL
    SELECT
        'Jobs Completed (24h)',
        completed_jobs_24h::TEXT,
        'N/A (info)',
        'ðŸ“Š INFO',
        10
    FROM system_health
    UNION ALL
    SELECT
        'Jobs Failed (24h)',
        failed_jobs_24h::TEXT,
        'N/A (info)',
        CASE
            WHEN failed_jobs_24h = 0 THEN 'ðŸ“Š INFO'
            ELSE 'âš ï¸\x8f ' || failed_jobs_24h::TEXT || ' failures'
        END,
        11
    FROM system_health
    UNION ALL
    SELECT
        'Jobs Reaped (24h)',
        jobs_reaped_24h::TEXT,
        'N/A (info)',
        CASE
            WHEN jobs_reaped_24h = 0 THEN 'ðŸ“Š INFO'
            ELSE 'ðŸ“Š ' || jobs_reaped_24h::TEXT || ' recovered'
        END,
        12
    FROM system_health
    UNION ALL
    SELECT
        'â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90',
        'â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90',
        'â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90',
        'â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90â•\x90',
        13
    UNION ALL
    SELECT
        'OVERALL SYSTEM STATUS',
        overall_status,
        'HEALTHY',
        CASE
            WHEN overall_status = 'HEALTHY' THEN 'âœ… OPERATIONAL'
            WHEN overall_status = 'WARNING' THEN 'âš ï¸\x8f DEGRADED'
            ELSE 'â\x9dŒ CRITICAL'
        END,
        14
    FROM system_health
    UNION ALL
    SELECT
        'Measured At',
        TO_CHAR(measured_at, 'YYYY-MM-DD HH24:MI:SS TZ'),
        '-',
        'ðŸ•\x90',
        15
    FROM system_health
)

SELECT
    metric_name AS "Metric",
    current_value AS "Current Value",
    slo_target AS "Target",
    status AS "Status"
FROM slo_metrics
ORDER BY sort_order;
