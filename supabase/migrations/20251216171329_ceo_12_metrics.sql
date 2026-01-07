-- ============================================================================
-- Migration: analytics.v_ceo_12_metrics
-- Created: 2025-12-16
-- Purpose: Canonical 12 CEO Metrics for Dragonfly Civil Executive Dashboard
-- ============================================================================
--
-- THE 12 CEO METRICS (grouped by category):
--
-- PIPELINE (3 metrics)
--   1. pipeline_total_aum          - Total Assets Under Management (sum of all judgment amounts)
--   2. pipeline_active_cases       - Count of cases not closed/collected
--   3. pipeline_intake_velocity_7d - New judgments added in last 7 days
--
-- QUALITY (2 metrics)
--   4. quality_batch_success_rate  - % of CSV batches that completed successfully (30d)
--   5. quality_data_integrity_score - % of records passing validation rules
--
-- ENFORCEMENT (3 metrics)
--   6. enforcement_active_cases    - Active enforcement cases in progress
--   7. enforcement_stalled_cases   - Cases with no activity in 14+ days
--   8. enforcement_actions_7d      - Enforcement actions completed last 7 days
--
-- REVENUE (2 metrics)
--   9.  revenue_collected_30d      - Amount collected in last 30 days
--   10. revenue_recovery_rate      - Historical recovery rate (collected / total judgment)
--
-- RISK (2 metrics)
--   11. risk_queue_failures        - Failed jobs in ops queue
--   12. risk_aging_90d             - Cases older than 90 days without resolution
--
-- ============================================================================
-- Ensure analytics schema exists
CREATE SCHEMA IF NOT EXISTS analytics;
-- ============================================================================
-- VIEW: analytics.v_ceo_12_metrics
-- ============================================================================
-- Returns exactly ONE ROW with all 12 CEO metrics + alert status for each
-- ============================================================================
DROP VIEW IF EXISTS analytics.v_ceo_12_metrics CASCADE;
CREATE OR REPLACE VIEW analytics.v_ceo_12_metrics AS WITH -- ============================================================================
    -- PIPELINE METRICS
    -- ============================================================================
    pipeline_stats AS (
        SELECT -- M1: pipeline_total_aum
            COALESCE(SUM(judgment_amount), 0)::NUMERIC(15, 2) AS pipeline_total_aum,
            -- M2: pipeline_active_cases
            COUNT(*) FILTER (
                WHERE COALESCE(status, 'pending') NOT IN ('closed', 'collected')
            )::INTEGER AS pipeline_active_cases,
            -- M3: pipeline_intake_velocity_7d
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '7 days'
            )::INTEGER AS pipeline_intake_velocity_7d
        FROM public.judgments
    ),
    -- ============================================================================
    -- QUALITY METRICS
    -- ============================================================================
    quality_batch_stats AS (
        SELECT -- M4: quality_batch_success_rate
            CASE
                WHEN COUNT(*) = 0 THEN 100.0
                ELSE ROUND(
                    (
                        COUNT(*) FILTER (
                            WHERE status = 'completed'
                        )::NUMERIC / COUNT(*)::NUMERIC
                    ) * 100,
                    1
                )
            END AS quality_batch_success_rate
        FROM ops.ingest_batches
        WHERE created_at >= NOW() - INTERVAL '30 days'
    ),
    quality_data_integrity AS (
        SELECT -- M5: quality_data_integrity_score
            -- Based on: judgments with all required fields populated
            CASE
                WHEN COUNT(*) = 0 THEN 100.0
                ELSE ROUND(
                    (
                        COUNT(*) FILTER (
                            WHERE case_number IS NOT NULL
                                AND case_number <> ''
                                AND judgment_amount IS NOT NULL
                                AND judgment_amount > 0
                                AND (
                                    plaintiff_name IS NOT NULL
                                    OR defendant_name IS NOT NULL
                                )
                        )::NUMERIC / COUNT(*)::NUMERIC
                    ) * 100,
                    1
                )
            END AS quality_data_integrity_score
        FROM public.judgments
    ),
    -- ============================================================================
    -- ENFORCEMENT METRICS
    -- ============================================================================
    enforcement_stats AS (
        SELECT -- M6: enforcement_active_cases
            COUNT(*) FILTER (
                WHERE COALESCE(status, 'open') NOT IN ('closed', 'collected', 'abandoned')
            )::INTEGER AS enforcement_active_cases,
            -- M7: enforcement_stalled_cases (no activity in 14+ days)
            COUNT(*) FILTER (
                WHERE updated_at < NOW() - INTERVAL '14 days'
                    AND COALESCE(status, 'open') NOT IN ('closed', 'collected', 'abandoned')
            )::INTEGER AS enforcement_stalled_cases
        FROM public.enforcement_cases
    ),
    enforcement_action_stats AS (
        SELECT -- M8: enforcement_actions_7d
            COUNT(*) FILTER (
                WHERE status = 'completed'
                    AND created_at >= NOW() - INTERVAL '7 days'
            )::INTEGER AS enforcement_actions_7d
        FROM public.enforcement_actions
    ),
    -- ============================================================================
    -- REVENUE METRICS
    -- ============================================================================
    revenue_stats AS (
        SELECT -- M9: revenue_collected_30d
            -- Sum of amounts from completed enforcement cases in last 30 days
            COALESCE(
                SUM(
                    CASE
                        WHEN ec.status = 'collected'
                        AND ec.updated_at >= NOW() - INTERVAL '30 days' THEN j.judgment_amount
                        ELSE 0
                    END
                ),
                0
            )::NUMERIC(15, 2) AS revenue_collected_30d,
            -- M10: revenue_recovery_rate (historical)
            CASE
                WHEN SUM(j.judgment_amount) = 0 THEN 0
                ELSE ROUND(
                    (
                        SUM(
                            CASE
                                WHEN ec.status = 'collected' THEN j.judgment_amount
                                ELSE 0
                            END
                        ) / SUM(j.judgment_amount)
                    ) * 100,
                    2
                )
            END AS revenue_recovery_rate
        FROM public.enforcement_cases ec
            LEFT JOIN public.judgments j ON ec.judgment_id = j.id
    ),
    -- ============================================================================
    -- RISK METRICS
    -- ============================================================================
    risk_queue_stats AS (
        SELECT -- M11: risk_queue_failures
            COUNT(*) FILTER (
                WHERE status::TEXT = 'failed'
            )::INTEGER AS risk_queue_failures
        FROM ops.job_queue
    ),
    risk_aging_stats AS (
        SELECT -- M12: risk_aging_90d (cases older than 90 days without resolution)
            COUNT(*) FILTER (
                WHERE created_at < NOW() - INTERVAL '90 days'
                    AND COALESCE(status, 'pending') NOT IN ('closed', 'collected')
            )::INTEGER AS risk_aging_90d
        FROM public.judgments
    ),
    -- ============================================================================
    -- ALERT THRESHOLDS
    -- ============================================================================
    -- Green: healthy, Yellow: warning, Red: critical
    thresholds AS (
        SELECT -- Pipeline thresholds
            100000::NUMERIC AS pipeline_aum_warning,
            -- Warn if AUM < 100k
            50000::NUMERIC AS pipeline_aum_critical,
            -- Critical if AUM < 50k
            10::INTEGER AS intake_velocity_warning,
            -- Warn if < 10 new/week
            5::INTEGER AS intake_velocity_critical,
            -- Critical if < 5 new/week
            -- Quality thresholds
            95.0::NUMERIC AS batch_success_warning,
            -- Warn if < 95%
            90.0::NUMERIC AS batch_success_critical,
            -- Critical if < 90%
            98.0::NUMERIC AS data_integrity_warning,
            -- Warn if < 98%
            95.0::NUMERIC AS data_integrity_critical,
            -- Critical if < 95%
            -- Enforcement thresholds
            10::INTEGER AS stalled_cases_warning,
            -- Warn if > 10 stalled
            25::INTEGER AS stalled_cases_critical,
            -- Critical if > 25 stalled
            5::INTEGER AS actions_7d_warning,
            -- Warn if < 5 actions/week
            2::INTEGER AS actions_7d_critical,
            -- Critical if < 2 actions/week
            -- Revenue thresholds
            5.0::NUMERIC AS recovery_rate_warning,
            -- Warn if < 5%
            2.0::NUMERIC AS recovery_rate_critical,
            -- Critical if < 2%
            -- Risk thresholds
            5::INTEGER AS queue_failures_warning,
            -- Warn if > 5 failures
            10::INTEGER AS queue_failures_critical,
            -- Critical if > 10 failures
            50::INTEGER AS aging_90d_warning,
            -- Warn if > 50 aged cases
            100::INTEGER AS aging_90d_critical -- Critical if > 100 aged cases
    ) -- ============================================================================
    -- FINAL SELECT: All 12 metrics with values, alerts, and metadata
    -- ============================================================================
SELECT -- METRIC VALUES
    -- Pipeline
    ps.pipeline_total_aum,
    ps.pipeline_active_cases,
    ps.pipeline_intake_velocity_7d,
    -- Quality
    qb.quality_batch_success_rate,
    qi.quality_data_integrity_score,
    -- Enforcement
    es.enforcement_active_cases,
    es.enforcement_stalled_cases,
    ea.enforcement_actions_7d,
    -- Revenue
    rs.revenue_collected_30d,
    rs.revenue_recovery_rate,
    -- Risk
    rq.risk_queue_failures,
    ra.risk_aging_90d,
    -- ALERT STATUSES (green/yellow/red)
    CASE
        WHEN ps.pipeline_total_aum < t.pipeline_aum_critical THEN 'red'
        WHEN ps.pipeline_total_aum < t.pipeline_aum_warning THEN 'yellow'
        ELSE 'green'
    END AS pipeline_aum_alert,
    CASE
        WHEN ps.pipeline_intake_velocity_7d < t.intake_velocity_critical THEN 'red'
        WHEN ps.pipeline_intake_velocity_7d < t.intake_velocity_warning THEN 'yellow'
        ELSE 'green'
    END AS intake_velocity_alert,
    CASE
        WHEN qb.quality_batch_success_rate < t.batch_success_critical THEN 'red'
        WHEN qb.quality_batch_success_rate < t.batch_success_warning THEN 'yellow'
        ELSE 'green'
    END AS batch_success_alert,
    CASE
        WHEN qi.quality_data_integrity_score < t.data_integrity_critical THEN 'red'
        WHEN qi.quality_data_integrity_score < t.data_integrity_warning THEN 'yellow'
        ELSE 'green'
    END AS data_integrity_alert,
    CASE
        WHEN es.enforcement_stalled_cases > t.stalled_cases_critical THEN 'red'
        WHEN es.enforcement_stalled_cases > t.stalled_cases_warning THEN 'yellow'
        ELSE 'green'
    END AS stalled_cases_alert,
    CASE
        WHEN ea.enforcement_actions_7d < t.actions_7d_critical THEN 'red'
        WHEN ea.enforcement_actions_7d < t.actions_7d_warning THEN 'yellow'
        ELSE 'green'
    END AS actions_7d_alert,
    CASE
        WHEN rs.revenue_recovery_rate < t.recovery_rate_critical THEN 'red'
        WHEN rs.revenue_recovery_rate < t.recovery_rate_warning THEN 'yellow'
        ELSE 'green'
    END AS recovery_rate_alert,
    CASE
        WHEN rq.risk_queue_failures > t.queue_failures_critical THEN 'red'
        WHEN rq.risk_queue_failures > t.queue_failures_warning THEN 'yellow'
        ELSE 'green'
    END AS queue_failures_alert,
    CASE
        WHEN ra.risk_aging_90d > t.aging_90d_critical THEN 'red'
        WHEN ra.risk_aging_90d > t.aging_90d_warning THEN 'yellow'
        ELSE 'green'
    END AS aging_90d_alert,
    -- METADATA
    NOW() AS generated_at,
    '1.0' AS metric_version
FROM pipeline_stats ps
    CROSS JOIN quality_batch_stats qb
    CROSS JOIN quality_data_integrity qi
    CROSS JOIN enforcement_stats es
    CROSS JOIN enforcement_action_stats ea
    CROSS JOIN revenue_stats rs
    CROSS JOIN risk_queue_stats rq
    CROSS JOIN risk_aging_stats ra
    CROSS JOIN thresholds t;
-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON VIEW analytics.v_ceo_12_metrics IS 'Canonical 12 CEO Metrics for Dragonfly Civil. Categories: Pipeline (3), Quality (2), Enforcement (3), Revenue (2), Risk (2). Includes metric values and alert status (green/yellow/red). Refresh rate: real-time (on-demand query).';
-- ============================================================================
-- RPC FUNCTION: ceo_12_metrics
-- ============================================================================
-- Wrapper function for Supabase client REST API consumption
-- ============================================================================
CREATE OR REPLACE FUNCTION public.ceo_12_metrics() RETURNS TABLE (
        -- Pipeline
        pipeline_total_aum NUMERIC(15, 2),
        pipeline_active_cases INTEGER,
        pipeline_intake_velocity_7d INTEGER,
        -- Quality
        quality_batch_success_rate NUMERIC(5, 1),
        quality_data_integrity_score NUMERIC(5, 1),
        -- Enforcement
        enforcement_active_cases INTEGER,
        enforcement_stalled_cases INTEGER,
        enforcement_actions_7d INTEGER,
        -- Revenue
        revenue_collected_30d NUMERIC(15, 2),
        revenue_recovery_rate NUMERIC(5, 2),
        -- Risk
        risk_queue_failures INTEGER,
        risk_aging_90d INTEGER,
        -- Alerts
        pipeline_aum_alert TEXT,
        intake_velocity_alert TEXT,
        batch_success_alert TEXT,
        data_integrity_alert TEXT,
        stalled_cases_alert TEXT,
        actions_7d_alert TEXT,
        recovery_rate_alert TEXT,
        queue_failures_alert TEXT,
        aging_90d_alert TEXT,
        -- Metadata
        generated_at TIMESTAMPTZ,
        metric_version TEXT
    ) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
SELECT pipeline_total_aum,
    pipeline_active_cases,
    pipeline_intake_velocity_7d,
    quality_batch_success_rate,
    quality_data_integrity_score,
    enforcement_active_cases,
    enforcement_stalled_cases,
    enforcement_actions_7d,
    revenue_collected_30d,
    revenue_recovery_rate,
    risk_queue_failures,
    risk_aging_90d,
    pipeline_aum_alert,
    intake_velocity_alert,
    batch_success_alert,
    data_integrity_alert,
    stalled_cases_alert,
    actions_7d_alert,
    recovery_rate_alert,
    queue_failures_alert,
    aging_90d_alert,
    generated_at,
    metric_version
FROM analytics.v_ceo_12_metrics
LIMIT 1;
$$;
COMMENT ON FUNCTION public.ceo_12_metrics IS 'Returns the 12 CEO metrics with alert statuses. Call via Supabase RPC: client.rpc("ceo_12_metrics")';
-- ============================================================================
-- GRANTS
-- ============================================================================
GRANT USAGE ON SCHEMA analytics TO authenticated,
    service_role;
GRANT SELECT ON analytics.v_ceo_12_metrics TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION public.ceo_12_metrics() TO authenticated,
    service_role;
-- ============================================================================
-- METRIC REFERENCE TABLE (for documentation and UI consumption)
-- ============================================================================
CREATE TABLE IF NOT EXISTS analytics.ceo_metric_definitions (
    id SERIAL PRIMARY KEY,
    metric_key TEXT UNIQUE NOT NULL,
    category TEXT NOT NULL,
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    unit TEXT NOT NULL,
    sql_source TEXT NOT NULL,
    refresh_rate TEXT NOT NULL,
    warning_threshold TEXT,
    critical_threshold TEXT,
    dashboard_card_position INTEGER,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
-- Insert the 12 metric definitions
INSERT INTO analytics.ceo_metric_definitions (
        metric_key,
        category,
        display_name,
        description,
        unit,
        sql_source,
        refresh_rate,
        warning_threshold,
        critical_threshold,
        dashboard_card_position
    )
VALUES -- Pipeline metrics
    (
        'pipeline_total_aum',
        'Pipeline',
        'Total AUM',
        'Total Assets Under Management - sum of all judgment amounts in the portfolio',
        'currency',
        'SUM(judgment_amount) FROM public.judgments',
        'real-time',
        '< $100,000',
        '< $50,000',
        1
    ),
    (
        'pipeline_active_cases',
        'Pipeline',
        'Active Cases',
        'Count of cases not in closed/collected status',
        'count',
        'COUNT(*) FROM public.judgments WHERE status NOT IN (closed, collected)',
        'real-time',
        NULL,
        NULL,
        2
    ),
    (
        'pipeline_intake_velocity_7d',
        'Pipeline',
        'Intake Velocity (7d)',
        'New judgments added to the system in the last 7 days',
        'count',
        'COUNT(*) FROM public.judgments WHERE created_at >= NOW() - 7 days',
        'real-time',
        '< 10',
        '< 5',
        3
    ),
    -- Quality metrics
    (
        'quality_batch_success_rate',
        'Quality',
        'Batch Success Rate',
        'Percentage of CSV import batches that completed successfully (30 day window)',
        'percentage',
        'COUNT(completed) / COUNT(*) FROM ops.ingest_batches (30d)',
        'real-time',
        '< 95%',
        '< 90%',
        4
    ),
    (
        'quality_data_integrity_score',
        'Quality',
        'Data Integrity Score',
        'Percentage of judgment records with all required fields populated',
        'percentage',
        'COUNT(valid) / COUNT(*) FROM public.judgments',
        'real-time',
        '< 98%',
        '< 95%',
        5
    ),
    -- Enforcement metrics
    (
        'enforcement_active_cases',
        'Enforcement',
        'Active Enforcement',
        'Enforcement cases currently in progress',
        'count',
        'COUNT(*) FROM public.enforcement_cases WHERE status != closed',
        'real-time',
        NULL,
        NULL,
        6
    ),
    (
        'enforcement_stalled_cases',
        'Enforcement',
        'Stalled Cases',
        'Enforcement cases with no activity in 14+ days',
        'count',
        'COUNT(*) FROM public.enforcement_cases WHERE updated_at < 14 days ago',
        'real-time',
        '> 10',
        '> 25',
        7
    ),
    (
        'enforcement_actions_7d',
        'Enforcement',
        'Actions Completed (7d)',
        'Enforcement actions completed in the last 7 days',
        'count',
        'COUNT(*) FROM public.enforcement_actions WHERE status=completed AND last 7d',
        'real-time',
        '< 5',
        '< 2',
        8
    ),
    -- Revenue metrics
    (
        'revenue_collected_30d',
        'Revenue',
        'Collections (30d)',
        'Total amount collected from successfully enforced judgments in last 30 days',
        'currency',
        'SUM(collected_amount) FROM enforcement_cases WHERE collected (30d)',
        'real-time',
        NULL,
        NULL,
        9
    ),
    (
        'revenue_recovery_rate',
        'Revenue',
        'Recovery Rate',
        'Historical percentage of judgment amounts successfully collected',
        'percentage',
        'SUM(collected) / SUM(total_judgment) * 100',
        'real-time',
        '< 5%',
        '< 2%',
        10
    ),
    -- Risk metrics
    (
        'risk_queue_failures',
        'Risk',
        'Queue Failures',
        'Number of failed jobs in the operations queue',
        'count',
        'COUNT(*) FROM ops.job_queue WHERE status = failed',
        'real-time',
        '> 5',
        '> 10',
        11
    ),
    (
        'risk_aging_90d',
        'Risk',
        'Aging Cases (90d+)',
        'Cases older than 90 days without resolution',
        'count',
        'COUNT(*) FROM public.judgments WHERE created_at < 90d AND not resolved',
        'real-time',
        '> 50',
        '> 100',
        12
    ) ON CONFLICT (metric_key) DO
UPDATE
SET category = EXCLUDED.category,
    display_name = EXCLUDED.display_name,
    description = EXCLUDED.description,
    unit = EXCLUDED.unit,
    sql_source = EXCLUDED.sql_source,
    refresh_rate = EXCLUDED.refresh_rate,
    warning_threshold = EXCLUDED.warning_threshold,
    critical_threshold = EXCLUDED.critical_threshold,
    dashboard_card_position = EXCLUDED.dashboard_card_position;
COMMENT ON TABLE analytics.ceo_metric_definitions IS 'Reference table containing definitions for the 12 CEO metrics. Used by dashboard and documentation.';
GRANT SELECT ON analytics.ceo_metric_definitions TO authenticated,
    service_role;
