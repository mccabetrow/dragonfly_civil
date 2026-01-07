-- ============================================================================
-- Migration: 20251201182738_fix_dashboard_view_grants.sql
-- Purpose: Restore dashboard view grants for Vercel console deployment
-- 
-- The Mom Enforcement Console (dragonfly-dashboard) deployed to Vercel is
-- returning "permission denied for view" errors. This migration grants SELECT
-- on all dashboard views to anon and authenticated roles.
--
-- RLS remains intact on underlying tables; only view-level grants are adjusted.
-- This migration is idempotent (safe to run multiple times).
-- Uses DO block to skip non-existent views gracefully.
-- ============================================================================
DO $$
DECLARE v_name text;
views_to_grant text [] := ARRAY [
        -- Core Case & Collectability Views
        'v_collectability_snapshot',
        'v_cases',
        'v_entities_simple',
        -- Plaintiff Views
        'v_plaintiffs_overview',
        'v_plaintiff_call_queue',
        'v_plaintiff_summary',
        'v_plaintiff_funnel_stats',
        'v_plaintiff_open_tasks',
        -- Judgment Pipeline Views
        'v_judgment_pipeline',
        'v_priority_pipeline',
        'v_pipeline_snapshot',
        -- Enforcement Views
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_enforcement_pipeline_status',
        'v_enforcement_actions_pending_signature',
        'v_enforcement_actions_recent',
        'v_enforcement_case_summary',
        -- Executive / Metrics Views
        'v_metrics_intake_daily',
        'v_metrics_pipeline',
        'v_metrics_enforcement',
        -- Ops Views
        'v_ops_daily_summary',
        -- Case Copilot Views
        'v_case_copilot_latest'
    ];
BEGIN FOREACH v_name IN ARRAY views_to_grant LOOP IF EXISTS (
    SELECT 1
    FROM information_schema.views
    WHERE table_schema = 'public'
        AND table_name = v_name
) THEN EXECUTE format(
    'GRANT SELECT ON public.%I TO anon, authenticated',
    v_name
);
RAISE NOTICE 'Granted SELECT on public.% to anon, authenticated',
v_name;
ELSE RAISE NOTICE 'View public.% does not exist, skipping',
v_name;
END IF;
END LOOP;
END $$;
-- Notify PostgREST to reload schema cache
NOTIFY pgrst,
'reload schema';
