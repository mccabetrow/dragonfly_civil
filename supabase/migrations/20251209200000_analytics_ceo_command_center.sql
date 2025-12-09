-- ============================================================================
-- Migration: analytics.v_ceo_command_center
-- Created: 2025-12-09
-- Purpose: Single-row executive summary view for CEO Dashboard Command Center
-- ============================================================================
-- Provides unified metrics across portfolio, pipeline, enforcement, and ops.
-- Designed for the CEO dashboard to show company-wide health at a glance.
-- ============================================================================
-- Ensure analytics schema exists
CREATE SCHEMA IF NOT EXISTS analytics;
GRANT USAGE ON SCHEMA analytics TO authenticated,
    service_role;
-- ============================================================================
-- VIEW: analytics.v_ceo_command_center
-- ============================================================================
-- Returns exactly ONE ROW with comprehensive executive metrics:
--
-- PORTFOLIO HEALTH:
--   - total_judgments: Total judgments in system
--   - total_judgment_value: Sum of all judgment amounts
--   - active_judgments: Judgments not in 'closed' or 'collected' status
--   - avg_judgment_value: Average judgment amount
--
-- PIPELINE VELOCITY:
--   - judgments_24h: New judgments in last 24 hours
--   - judgments_7d: New judgments in last 7 days
--   - judgments_30d: New judgments in last 30 days
--   - intake_value_24h: Value of judgments added last 24 hours
--   - intake_value_7d: Value of judgments added last 7 days
--
-- ENFORCEMENT PERFORMANCE:
--   - enforcement_cases_active: Active enforcement cases
--   - enforcement_cases_stalled: Cases with no activity in 14 days
--   - enforcement_actions_pending: Pending enforcement actions
--   - enforcement_actions_completed_7d: Actions completed last 7 days
--   - pending_attorney_signatures: Actions awaiting attorney signature
--
-- TIER DISTRIBUTION:
--   - tier_a_count: High-value tier A judgments
--   - tier_b_count: Tier B judgments
--   - tier_c_count: Tier C judgments
--   - tier_d_count: Low-priority tier D judgments
--   - tier_unassigned_count: Judgments without tier assignment
--
-- OPS HEALTH:
--   - queue_pending: Pending jobs in job queue
--   - queue_failed: Failed jobs in job queue
--   - batch_success_rate_30d: Ingest batch success rate (last 30 days)
--   - last_successful_import_ts: Timestamp of last successful import
--
-- GENERATED:
--   - generated_at: Timestamp when this data was computed
-- ============================================================================
CREATE OR REPLACE VIEW analytics.v_ceo_command_center AS WITH portfolio_stats AS (
        SELECT COUNT(*) AS total_judgments,
            COALESCE(SUM(judgment_amount), 0) AS total_judgment_value,
            COUNT(*) FILTER (
                WHERE status NOT IN ('closed', 'collected')
            ) AS active_judgments,
            COALESCE(AVG(judgment_amount), 0) AS avg_judgment_value
        FROM public.judgments
    ),
    pipeline_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            ) AS judgments_24h,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '7 days'
            ) AS judgments_7d,
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '30 days'
            ) AS judgments_30d,
            COALESCE(
                SUM(judgment_amount) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '24 hours'
                ),
                0
            ) AS intake_value_24h,
            COALESCE(
                SUM(judgment_amount) FILTER (
                    WHERE created_at >= NOW() - INTERVAL '7 days'
                ),
                0
            ) AS intake_value_7d
        FROM public.judgments
    ),
    enforcement_case_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE status NOT IN ('closed', 'collected', 'abandoned')
            ) AS enforcement_cases_active,
            COUNT(*) FILTER (
                WHERE updated_at < NOW() - INTERVAL '14 days'
                    AND status NOT IN ('closed', 'collected', 'abandoned')
            ) AS enforcement_cases_stalled
        FROM public.enforcement_cases
    ),
    enforcement_action_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE status = 'pending'
            ) AS enforcement_actions_pending,
            COUNT(*) FILTER (
                WHERE status = 'completed'
                    AND created_at >= NOW() - INTERVAL '7 days'
            ) AS enforcement_actions_completed_7d,
            COUNT(*) FILTER (
                WHERE status = 'pending'
                    AND requires_attorney_signature = true
            ) AS pending_attorney_signatures
        FROM public.enforcement_actions
    ),
    tier_stats AS (
        -- tier is on plaintiffs, not judgments - join via plaintiff_id
        SELECT COUNT(*) FILTER (
                WHERE p.tier = 'A'
            ) AS tier_a_count,
            COUNT(*) FILTER (
                WHERE p.tier = 'B'
            ) AS tier_b_count,
            COUNT(*) FILTER (
                WHERE p.tier = 'C'
            ) AS tier_c_count,
            COUNT(*) FILTER (
                WHERE p.tier = 'D'
            ) AS tier_d_count,
            COUNT(*) FILTER (
                WHERE p.tier IS NULL
                    OR p.tier = ''
            ) AS tier_unassigned_count
        FROM public.judgments j
            LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    ),
    queue_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE status::text = 'pending'
            ) AS queue_pending,
            COUNT(*) FILTER (
                WHERE status::text = 'failed'
            ) AS queue_failed
        FROM ops.job_queue
    ),
    batch_stats AS (
        SELECT CASE
                WHEN COUNT(*) = 0 THEN 100.0
                ELSE ROUND(
                    (
                        COUNT(*) FILTER (
                            WHERE status = 'completed'
                        )::NUMERIC / COUNT(*)::NUMERIC
                    ) * 100,
                    1
                )
            END AS batch_success_rate_30d,
            MAX(completed_at) FILTER (
                WHERE status = 'completed'
            ) AS last_successful_import_ts
        FROM ops.ingest_batches
        WHERE created_at >= NOW() - INTERVAL '30 days'
    )
SELECT -- Portfolio Health
    ps.total_judgments::INTEGER,
    ROUND(ps.total_judgment_value, 2)::NUMERIC(15, 2) AS total_judgment_value,
    ps.active_judgments::INTEGER,
    ROUND(ps.avg_judgment_value, 2)::NUMERIC(12, 2) AS avg_judgment_value,
    -- Pipeline Velocity
    pip.judgments_24h::INTEGER,
    pip.judgments_7d::INTEGER,
    pip.judgments_30d::INTEGER,
    ROUND(pip.intake_value_24h, 2)::NUMERIC(15, 2) AS intake_value_24h,
    ROUND(pip.intake_value_7d, 2)::NUMERIC(15, 2) AS intake_value_7d,
    -- Enforcement Performance
    COALESCE(ecs.enforcement_cases_active, 0)::INTEGER AS enforcement_cases_active,
    COALESCE(ecs.enforcement_cases_stalled, 0)::INTEGER AS enforcement_cases_stalled,
    COALESCE(eas.enforcement_actions_pending, 0)::INTEGER AS enforcement_actions_pending,
    COALESCE(eas.enforcement_actions_completed_7d, 0)::INTEGER AS enforcement_actions_completed_7d,
    COALESCE(eas.pending_attorney_signatures, 0)::INTEGER AS pending_attorney_signatures,
    -- Tier Distribution
    ts.tier_a_count::INTEGER,
    ts.tier_b_count::INTEGER,
    ts.tier_c_count::INTEGER,
    ts.tier_d_count::INTEGER,
    ts.tier_unassigned_count::INTEGER,
    -- Ops Health
    qs.queue_pending::INTEGER,
    qs.queue_failed::INTEGER,
    bs.batch_success_rate_30d::NUMERIC(5, 1),
    bs.last_successful_import_ts AS last_successful_import_ts,
    -- Generated timestamp
    NOW() AS generated_at
FROM portfolio_stats ps
    CROSS JOIN pipeline_stats pip
    CROSS JOIN enforcement_case_stats ecs
    CROSS JOIN enforcement_action_stats eas
    CROSS JOIN tier_stats ts
    CROSS JOIN queue_stats qs
    CROSS JOIN batch_stats bs;
-- ============================================================================
-- COMMENT
-- ============================================================================
COMMENT ON VIEW analytics.v_ceo_command_center IS 'CEO Command Center - Single-row executive dashboard metrics. Aggregates portfolio health, pipeline velocity, enforcement performance, tier distribution, and ops health. Designed for real-time CEO dashboard.';
-- ============================================================================
-- RPC FUNCTION: ceo_command_center_metrics
-- ============================================================================
-- Wrapper function for Supabase client to query the view
-- Returns single row as JSONB-friendly table for REST API consumption
-- ============================================================================
CREATE OR REPLACE FUNCTION public.ceo_command_center_metrics() RETURNS TABLE (
        -- Portfolio Health
        total_judgments INTEGER,
        total_judgment_value NUMERIC(15, 2),
        active_judgments INTEGER,
        avg_judgment_value NUMERIC(12, 2),
        -- Pipeline Velocity
        judgments_24h INTEGER,
        judgments_7d INTEGER,
        judgments_30d INTEGER,
        intake_value_24h NUMERIC(15, 2),
        intake_value_7d NUMERIC(15, 2),
        -- Enforcement Performance
        enforcement_cases_active INTEGER,
        enforcement_cases_stalled INTEGER,
        enforcement_actions_pending INTEGER,
        enforcement_actions_completed_7d INTEGER,
        pending_attorney_signatures INTEGER,
        -- Tier Distribution
        tier_a_count INTEGER,
        tier_b_count INTEGER,
        tier_c_count INTEGER,
        tier_d_count INTEGER,
        tier_unassigned_count INTEGER,
        -- Ops Health
        queue_pending INTEGER,
        queue_failed INTEGER,
        batch_success_rate_30d NUMERIC(5, 1),
        last_successful_import_ts TIMESTAMPTZ,
        -- Generated
        generated_at TIMESTAMPTZ
    ) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
SELECT total_judgments,
    total_judgment_value,
    active_judgments,
    avg_judgment_value,
    judgments_24h,
    judgments_7d,
    judgments_30d,
    intake_value_24h,
    intake_value_7d,
    enforcement_cases_active,
    enforcement_cases_stalled,
    enforcement_actions_pending,
    enforcement_actions_completed_7d,
    pending_attorney_signatures,
    tier_a_count,
    tier_b_count,
    tier_c_count,
    tier_d_count,
    tier_unassigned_count,
    queue_pending,
    queue_failed,
    batch_success_rate_30d,
    last_successful_import_ts,
    generated_at
FROM analytics.v_ceo_command_center
LIMIT 1;
$$;
-- ============================================================================
-- GRANTS
-- ============================================================================
-- View grants
GRANT SELECT ON analytics.v_ceo_command_center TO authenticated;
GRANT SELECT ON analytics.v_ceo_command_center TO service_role;
-- RPC function grants
GRANT EXECUTE ON FUNCTION public.ceo_command_center_metrics() TO authenticated;
GRANT EXECUTE ON FUNCTION public.ceo_command_center_metrics() TO service_role;
-- ============================================================================
-- Verification queries (for manual testing)
-- ============================================================================
-- SELECT * FROM analytics.v_ceo_command_center;
-- SELECT * FROM public.ceo_command_center_metrics();