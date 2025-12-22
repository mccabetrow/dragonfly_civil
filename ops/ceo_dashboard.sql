-- ============================================================================
-- CEO DASHBOARD - System Health Overview
-- ============================================================================
-- Purpose: Single-table view of all critical system metrics
-- Usage: Run in Supabase SQL Editor for instant system health snapshot
-- ============================================================================
WITH metrics AS (
    -- ========================================================================
    -- QUEUE HEALTH
    -- ========================================================================
    SELECT 'Queue Health' AS metric_category,
        'Queue Depth (Pending Jobs)' AS metric_name,
        COALESCE(
            (
                SELECT COUNT(*)::TEXT
                FROM ops.job_queue
                WHERE status = 'pending'
            ),
            '0'
        ) AS current_value,
        '< 100' AS target,
        CASE
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'pending'
                ),
                0
            ) < 50 THEN '✅'
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'pending'
                ),
                0
            ) < 100 THEN '⚠️'
            ELSE '❌'
        END AS status,
        1 AS sort_order
    UNION ALL
    SELECT 'Queue Health',
        'Queue Freshness (Oldest Pending)',
        COALESCE(
            ROUND(
                EXTRACT(
                    EPOCH
                    FROM (NOW() - MIN(created_at))
                ) / 60
            )::TEXT || ' min',
            'N/A'
        ),
        '< 30 min',
        CASE
            WHEN (
                SELECT MIN(created_at)
                FROM ops.job_queue
                WHERE status = 'pending'
            ) IS NULL THEN '✅'
            WHEN EXTRACT(
                EPOCH
                FROM (
                        NOW() - (
                            SELECT MIN(created_at)
                            FROM ops.job_queue
                            WHERE status = 'pending'
                        )
                    )
            ) / 60 < 15 THEN '✅'
            WHEN EXTRACT(
                EPOCH
                FROM (
                        NOW() - (
                            SELECT MIN(created_at)
                            FROM ops.job_queue
                            WHERE status = 'pending'
                        )
                    )
            ) / 60 < 30 THEN '⚠️'
            ELSE '❌'
        END,
        2
    FROM ops.job_queue
    WHERE status = 'pending'
    UNION ALL
    -- ========================================================================
    -- PERFORMANCE
    -- ========================================================================
    SELECT 'Performance',
        'P95 Latency (24h)',
        COALESCE(
            ROUND(
                PERCENTILE_CONT(0.95) WITHIN GROUP (
                    ORDER BY EXTRACT(
                            EPOCH
                            FROM (updated_at - COALESCE(started_at, created_at))
                        )
                )
            )::TEXT || ' sec',
            'N/A'
        ),
        '< 30 sec',
        CASE
            WHEN PERCENTILE_CONT(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(
                        EPOCH
                        FROM (updated_at - COALESCE(started_at, created_at))
                    )
            ) IS NULL THEN '✅'
            WHEN PERCENTILE_CONT(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(
                        EPOCH
                        FROM (updated_at - COALESCE(started_at, created_at))
                    )
            ) < 15 THEN '✅'
            WHEN PERCENTILE_CONT(0.95) WITHIN GROUP (
                ORDER BY EXTRACT(
                        EPOCH
                        FROM (updated_at - COALESCE(started_at, created_at))
                    )
            ) < 30 THEN '⚠️'
            ELSE '❌'
        END,
        3
    FROM ops.job_queue
    WHERE status = 'completed'
        AND updated_at > NOW() - INTERVAL '24 hours'
    UNION ALL
    SELECT 'Performance',
        'Jobs Completed (24h)',
        COALESCE(
            (
                SELECT COUNT(*)::TEXT
                FROM ops.job_queue
                WHERE status = 'completed'
                    AND updated_at > NOW() - INTERVAL '24 hours'
            ),
            '0'
        ),
        '> 0',
        CASE
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'completed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                ),
                0
            ) > 100 THEN '✅'
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'completed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                ),
                0
            ) > 0 THEN '⚠️'
            ELSE '❌'
        END,
        4
    UNION ALL
    -- ========================================================================
    -- RELIABILITY
    -- ========================================================================
    SELECT 'Reliability',
        'Active Workers (5 min)',
        COALESCE(
            (
                SELECT COUNT(DISTINCT worker_id)::TEXT
                FROM ops.job_queue
                WHERE status = 'processing'
                    AND started_at > NOW() - INTERVAL '5 minutes'
            ),
            '0'
        ),
        '>= 1',
        CASE
            WHEN COALESCE(
                (
                    SELECT COUNT(DISTINCT worker_id)
                    FROM ops.job_queue
                    WHERE status = 'processing'
                        AND started_at > NOW() - INTERVAL '5 minutes'
                ),
                0
            ) >= 2 THEN '✅'
            WHEN COALESCE(
                (
                    SELECT COUNT(DISTINCT worker_id)
                    FROM ops.job_queue
                    WHERE status = 'processing'
                        AND started_at > NOW() - INTERVAL '5 minutes'
                ),
                0
            ) >= 1 THEN '⚠️'
            ELSE '❌'
        END,
        5
    UNION ALL
    SELECT 'Reliability',
        'Error Rate (24h)',
        COALESCE(
            ROUND(
                100.0 * (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'failed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                )::NUMERIC / NULLIF(
                    (
                        SELECT COUNT(*)
                        FROM ops.job_queue
                        WHERE updated_at > NOW() - INTERVAL '24 hours'
                    ),
                    0
                ),
                2
            )::TEXT || '%',
            '0%'
        ),
        '< 5%',
        CASE
            WHEN COALESCE(
                100.0 * (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'failed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                )::NUMERIC / NULLIF(
                    (
                        SELECT COUNT(*)
                        FROM ops.job_queue
                        WHERE updated_at > NOW() - INTERVAL '24 hours'
                    ),
                    0
                ),
                0
            ) < 1 THEN '✅'
            WHEN COALESCE(
                100.0 * (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'failed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                )::NUMERIC / NULLIF(
                    (
                        SELECT COUNT(*)
                        FROM ops.job_queue
                        WHERE updated_at > NOW() - INTERVAL '24 hours'
                    ),
                    0
                ),
                0
            ) < 5 THEN '⚠️'
            ELSE '❌'
        END,
        6
    UNION ALL
    SELECT 'Reliability',
        'Failed Jobs (24h)',
        COALESCE(
            (
                SELECT COUNT(*)::TEXT
                FROM ops.job_queue
                WHERE status = 'failed'
                    AND updated_at > NOW() - INTERVAL '24 hours'
            ),
            '0'
        ),
        '< 10',
        CASE
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'failed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                ),
                0
            ) = 0 THEN '✅'
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'failed'
                        AND updated_at > NOW() - INTERVAL '24 hours'
                ),
                0
            ) < 10 THEN '⚠️'
            ELSE '❌'
        END,
        7
    UNION ALL
    -- ========================================================================
    -- SAFETY (REAPER)
    -- ========================================================================
    SELECT 'Safety',
        'Reaper Last Run',
        COALESCE(
            (
                SELECT CASE
                        WHEN MAX(start_time) IS NULL THEN 'Never'
                        ELSE ROUND(
                            EXTRACT(
                                EPOCH
                                FROM (NOW() - MAX(start_time))
                            ) / 60
                        )::TEXT || ' min ago'
                    END
                FROM cron.job_run_details jrd
                    JOIN cron.job j ON j.jobid = jrd.jobid
                WHERE j.jobname = 'dragonfly_reaper'
                    AND jrd.status = 'succeeded'
            ),
            'Not Configured'
        ),
        '< 10 min',
        CASE
            WHEN NOT EXISTS (
                SELECT 1
                FROM pg_namespace
                WHERE nspname = 'cron'
            ) THEN '⚠️'
            WHEN (
                SELECT MAX(start_time)
                FROM cron.job_run_details jrd
                    JOIN cron.job j ON j.jobid = jrd.jobid
                WHERE j.jobname = 'dragonfly_reaper'
                    AND jrd.status = 'succeeded'
            ) IS NULL THEN '⚠️'
            WHEN EXTRACT(
                EPOCH
                FROM (
                        NOW() - (
                            SELECT MAX(start_time)
                            FROM cron.job_run_details jrd
                                JOIN cron.job j ON j.jobid = jrd.jobid
                            WHERE j.jobname = 'dragonfly_reaper'
                                AND jrd.status = 'succeeded'
                        )
                    )
            ) / 60 < 10 THEN '✅'
            ELSE '❌'
        END,
        8
    UNION ALL
    SELECT 'Safety',
        'Stuck Jobs (> 10 min)',
        COALESCE(
            (
                SELECT COUNT(*)::TEXT
                FROM ops.job_queue
                WHERE status = 'processing'
                    AND started_at < NOW() - INTERVAL '10 minutes'
            ),
            '0'
        ),
        '0',
        CASE
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'processing'
                        AND started_at < NOW() - INTERVAL '10 minutes'
                ),
                0
            ) = 0 THEN '✅'
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM ops.job_queue
                    WHERE status = 'processing'
                        AND started_at < NOW() - INTERVAL '10 minutes'
                ),
                0
            ) < 5 THEN '⚠️'
            ELSE '❌'
        END,
        9
    UNION ALL
    -- ========================================================================
    -- INTAKE PIPELINE
    -- ========================================================================
    SELECT 'Intake',
        'Plaintiffs (Total)',
        COALESCE(
            (
                SELECT COUNT(*)::TEXT
                FROM public.plaintiffs
            ),
            '0'
        ),
        '> 0',
        CASE
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM public.plaintiffs
                ),
                0
            ) > 100 THEN '✅'
            WHEN COALESCE(
                (
                    SELECT COUNT(*)
                    FROM public.plaintiffs
                ),
                0
            ) > 0 THEN '⚠️'
            ELSE '❌'
        END,
        10
    UNION ALL
    SELECT 'Intake',
        'Plaintiffs (Today)',
        COALESCE(
            (
                SELECT COUNT(*)::TEXT
                FROM public.plaintiffs
                WHERE created_at::DATE = CURRENT_DATE
            ),
            '0'
        ),
        '>= 0',
        '✅',
        11
)
SELECT metric_category AS "Category",
    metric_name AS "Metric",
    current_value AS "Current Value",
    target AS "Target",
    status AS "Status"
FROM metrics
ORDER BY sort_order;
-- ============================================================================
-- QUICK REFERENCE
-- ============================================================================
-- ✅ = Healthy (within target)
-- ⚠️ = Warning (approaching threshold)
-- ❌ = Critical (action required)
--
-- Run this query daily or before any demo to verify system health.
-- ============================================================================