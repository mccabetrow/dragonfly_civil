-- 0210_enforcement_action_views.sql
-- Dashboard views for enforcement actions visibility.
-- These views power the Mom-friendly dashboard showing what's happening after enrichment.
-- ============================================================================
-- VIEW: v_enforcement_actions_overview
-- ============================================================================
-- Summary of enforcement actions by status and type.
-- Shows counts and attorney signature requirements at a glance.
CREATE OR REPLACE VIEW public.v_enforcement_actions_overview AS
SELECT ea.action_type,
    ea.status,
    COUNT(*) AS action_count,
    COUNT(*) FILTER (
        WHERE ea.requires_attorney_signature = true
    ) AS needs_signature_count,
    SUM(COALESCE(cj.principal_amount, 0))::numeric AS total_principal_amount,
    MIN(ea.created_at) AS oldest_action_at,
    MAX(ea.created_at) AS newest_action_at
FROM public.enforcement_actions ea
    LEFT JOIN public.core_judgments cj ON cj.id = ea.judgment_id
GROUP BY ea.action_type,
    ea.status
ORDER BY CASE
        ea.status
        WHEN 'pending' THEN 1
        WHEN 'planned' THEN 2
        WHEN 'served' THEN 3
        WHEN 'completed' THEN 4
        WHEN 'failed' THEN 5
        WHEN 'cancelled' THEN 6
        WHEN 'expired' THEN 7
        ELSE 99
    END,
    ea.action_type;
COMMENT ON VIEW public.v_enforcement_actions_overview IS 'Aggregated enforcement actions by type and status for executive dashboard.';
-- ============================================================================
-- VIEW: v_enforcement_actions_pending_signature
-- ============================================================================
-- Actions awaiting attorney signature - Mom's priority queue.
CREATE OR REPLACE VIEW public.v_enforcement_actions_pending_signature AS
SELECT ea.id AS action_id,
    ea.judgment_id,
    cj.case_index_number,
    cj.debtor_name,
    cj.principal_amount,
    ea.action_type,
    ea.status,
    ea.notes,
    ea.created_at,
    -- Age in days for prioritization
    EXTRACT(
        DAY
        FROM (now() - ea.created_at)
    )::int AS age_days,
    -- Metadata for context
    ea.metadata
FROM public.enforcement_actions ea
    JOIN public.core_judgments cj ON cj.id = ea.judgment_id
WHERE ea.requires_attorney_signature = true
    AND ea.status IN ('planned', 'pending')
ORDER BY ea.created_at ASC;
COMMENT ON VIEW public.v_enforcement_actions_pending_signature IS 'Enforcement actions awaiting attorney signature, sorted by age.';
-- ============================================================================
-- VIEW: v_enforcement_actions_recent
-- ============================================================================
-- Recent enforcement action activity for the timeline.
CREATE OR REPLACE VIEW public.v_enforcement_actions_recent AS
SELECT ea.id AS action_id,
    ea.judgment_id,
    cj.case_index_number,
    cj.debtor_name,
    ea.action_type,
    ea.status,
    ea.requires_attorney_signature,
    ea.generated_url,
    ea.notes,
    ea.created_at,
    ea.updated_at,
    -- Judgment context
    cj.principal_amount,
    cj.collectability_score,
    cj.status AS judgment_status
FROM public.enforcement_actions ea
    JOIN public.core_judgments cj ON cj.id = ea.judgment_id
ORDER BY ea.created_at DESC
LIMIT 100;
COMMENT ON VIEW public.v_enforcement_actions_recent IS 'Most recent enforcement actions for activity feed.';
-- ============================================================================
-- VIEW: v_enforcement_pipeline_status
-- ============================================================================
-- Pipeline view showing where each judgment is in the enforcement flow.
-- This is the main "Mom dashboard" view.
CREATE OR REPLACE VIEW public.v_enforcement_pipeline_status AS WITH intelligence_summary AS (
        -- Get intelligence status per judgment
        SELECT di.judgment_id,
            di.employer_name IS NOT NULL AS has_employer,
            di.bank_name IS NOT NULL AS has_bank,
            di.has_benefits_only_account,
            di.confidence_score,
            di.income_band,
            di.last_updated AS intel_updated_at
        FROM public.debtor_intelligence di
    ),
    action_summary AS (
        -- Aggregate actions per judgment
        SELECT ea.judgment_id,
            COUNT(*) AS total_actions,
            COUNT(*) FILTER (
                WHERE ea.status = 'planned'
            ) AS planned_actions,
            COUNT(*) FILTER (
                WHERE ea.status = 'pending'
            ) AS pending_actions,
            COUNT(*) FILTER (
                WHERE ea.status = 'completed'
            ) AS completed_actions,
            COUNT(*) FILTER (
                WHERE ea.status = 'failed'
            ) AS failed_actions,
            COUNT(*) FILTER (
                WHERE ea.requires_attorney_signature
                    AND ea.status IN ('planned', 'pending')
            ) AS awaiting_signature,
            -- Action types present
            ARRAY_AGG(DISTINCT ea.action_type) AS action_types,
            MAX(ea.created_at) AS last_action_at
        FROM public.enforcement_actions ea
        GROUP BY ea.judgment_id
    )
SELECT cj.id AS judgment_id,
    cj.case_index_number,
    cj.debtor_name,
    cj.principal_amount,
    cj.judgment_date,
    cj.status AS judgment_status,
    cj.collectability_score,
    cj.created_at AS judgment_created_at,
    -- Intelligence status
    COALESCE(isumm.has_employer, false) AS has_employer_intel,
    COALESCE(isumm.has_bank, false) AS has_bank_intel,
    COALESCE(isumm.has_benefits_only_account, false) AS is_benefits_only,
    isumm.confidence_score AS intel_confidence,
    isumm.income_band,
    isumm.intel_updated_at,
    -- Pipeline stage derived from status
    CASE
        WHEN cj.status IN ('satisfied', 'vacated', 'expired') THEN 'closed'
        WHEN isumm.judgment_id IS NULL THEN 'awaiting_enrichment'
        WHEN COALESCE(asumm.total_actions, 0) = 0 THEN 'awaiting_action_plan'
        WHEN COALESCE(asumm.awaiting_signature, 0) > 0 THEN 'awaiting_signature'
        WHEN COALESCE(asumm.pending_actions, 0) > 0 THEN 'actions_in_progress'
        WHEN COALESCE(asumm.completed_actions, 0) > 0
        AND COALESCE(asumm.pending_actions, 0) = 0 THEN 'actions_complete'
        ELSE 'unknown'
    END AS pipeline_stage,
    -- Action summary
    COALESCE(asumm.total_actions, 0) AS total_actions,
    COALESCE(asumm.planned_actions, 0) AS planned_actions,
    COALESCE(asumm.pending_actions, 0) AS pending_actions,
    COALESCE(asumm.completed_actions, 0) AS completed_actions,
    COALESCE(asumm.awaiting_signature, 0) AS awaiting_signature,
    asumm.action_types,
    asumm.last_action_at
FROM public.core_judgments cj
    LEFT JOIN intelligence_summary isumm ON isumm.judgment_id = cj.id
    LEFT JOIN action_summary asumm ON asumm.judgment_id = cj.id
ORDER BY CASE
        WHEN COALESCE(asumm.awaiting_signature, 0) > 0 THEN 1 -- Signature needed first
        WHEN COALESCE(asumm.pending_actions, 0) > 0 THEN 2 -- In progress
        WHEN isumm.judgment_id IS NULL THEN 3 -- Needs enrichment
        WHEN COALESCE(asumm.total_actions, 0) = 0 THEN 4 -- Needs action plan
        ELSE 5
    END,
    cj.principal_amount DESC NULLS LAST;
COMMENT ON VIEW public.v_enforcement_pipeline_status IS 'Main pipeline view showing each judgment stage from enrichment through enforcement.';
-- ============================================================================
-- VIEW: v_enforcement_action_stats
-- ============================================================================
-- Daily/weekly stats for trend tracking.
CREATE OR REPLACE VIEW public.v_enforcement_action_stats AS WITH daily_stats AS (
        SELECT date_trunc('day', ea.created_at)::date AS activity_date,
            ea.action_type,
            COUNT(*) AS actions_created,
            COUNT(*) FILTER (
                WHERE ea.requires_attorney_signature
            ) AS needing_signature
        FROM public.enforcement_actions ea
        WHERE ea.created_at >= now() - interval '30 days'
        GROUP BY 1,
            2
    )
SELECT activity_date,
    action_type,
    actions_created,
    needing_signature,
    SUM(actions_created) OVER (
        PARTITION BY action_type
        ORDER BY activity_date
    ) AS cumulative_actions
FROM daily_stats
ORDER BY activity_date DESC,
    action_type;
COMMENT ON VIEW public.v_enforcement_action_stats IS 'Daily enforcement action statistics for trend analysis.';
-- ============================================================================
-- GRANTS: Make views accessible to dashboard
-- ============================================================================
GRANT SELECT ON public.v_enforcement_actions_overview TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_enforcement_actions_pending_signature TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_enforcement_actions_recent TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_enforcement_pipeline_status TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_enforcement_action_stats TO anon,
    authenticated,
    service_role;
