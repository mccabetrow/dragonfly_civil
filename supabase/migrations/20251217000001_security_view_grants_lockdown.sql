-- =============================================================================
-- Migration: Security Hardening - View Grants Lockdown
-- Purpose: Restrict view access to SELECT-only for dashboard views, remove
--          access from internal/ops views
-- =============================================================================
-- This migration addresses Supabase Security Advisor warnings about views
-- having INSERT, UPDATE, DELETE, TRUNCATE, etc. grants.
--
-- CATEGORIES:
-- 1. Pipeline Views (dashboard-critical): SELECT-only for anon/authenticated
-- 2. Internal/Ops Views: service_role only
-- 3. Metrics Views: service_role only (exposed via RPCs)
--
-- ROLLBACK: See bottom of file for rollback statements
-- VERIFICATION: Run `python -m tools.security_audit --env dev` after applying
-- =============================================================================
BEGIN;
-- =============================================================================
-- 1. PIPELINE VIEWS - Dashboard-critical, SELECT-only access
-- =============================================================================
-- These views power the main dashboard. Keep SELECT, remove everything else.
-- v_plaintiffs_overview
REVOKE ALL ON public.v_plaintiffs_overview
FROM anon;
REVOKE ALL ON public.v_plaintiffs_overview
FROM authenticated;
GRANT SELECT ON public.v_plaintiffs_overview TO anon;
GRANT SELECT ON public.v_plaintiffs_overview TO authenticated;
-- v_judgment_pipeline
REVOKE ALL ON public.v_judgment_pipeline
FROM anon;
REVOKE ALL ON public.v_judgment_pipeline
FROM authenticated;
GRANT SELECT ON public.v_judgment_pipeline TO anon;
GRANT SELECT ON public.v_judgment_pipeline TO authenticated;
-- v_enforcement_overview
REVOKE ALL ON public.v_enforcement_overview
FROM anon;
REVOKE ALL ON public.v_enforcement_overview
FROM authenticated;
GRANT SELECT ON public.v_enforcement_overview TO anon;
GRANT SELECT ON public.v_enforcement_overview TO authenticated;
-- v_enforcement_recent
REVOKE ALL ON public.v_enforcement_recent
FROM anon;
REVOKE ALL ON public.v_enforcement_recent
FROM authenticated;
GRANT SELECT ON public.v_enforcement_recent TO anon;
GRANT SELECT ON public.v_enforcement_recent TO authenticated;
-- v_plaintiff_call_queue
REVOKE ALL ON public.v_plaintiff_call_queue
FROM anon;
REVOKE ALL ON public.v_plaintiff_call_queue
FROM authenticated;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon;
GRANT SELECT ON public.v_plaintiff_call_queue TO authenticated;
-- v_enforcement_timeline (if it's dashboard-facing)
REVOKE ALL ON public.v_enforcement_timeline
FROM anon;
REVOKE ALL ON public.v_enforcement_timeline
FROM authenticated;
GRANT SELECT ON public.v_enforcement_timeline TO anon;
GRANT SELECT ON public.v_enforcement_timeline TO authenticated;
-- =============================================================================
-- 2. INTERNAL VIEWS - Remove all access from anon/authenticated
-- =============================================================================
-- These views expose sensitive internal data and should only be accessible
-- via service_role or SECURITY DEFINER functions.
-- v_cases
REVOKE ALL ON public.v_cases
FROM anon;
REVOKE ALL ON public.v_cases
FROM authenticated;
-- v_entities_simple  
REVOKE ALL ON public.v_entities_simple
FROM anon;
REVOKE ALL ON public.v_entities_simple
FROM authenticated;
-- v_collectability_snapshot
REVOKE ALL ON public.v_collectability_snapshot
FROM anon;
REVOKE ALL ON public.v_collectability_snapshot
FROM authenticated;
-- v_priority_pipeline (internal scoring)
REVOKE ALL ON public.v_priority_pipeline
FROM anon;
REVOKE ALL ON public.v_priority_pipeline
FROM authenticated;
-- v_radar (internal ops)
REVOKE ALL ON public.v_radar
FROM anon;
REVOKE ALL ON public.v_radar
FROM authenticated;
-- v_migration_status (internal ops)
REVOKE ALL ON public.v_migration_status
FROM anon;
REVOKE ALL ON public.v_migration_status
FROM authenticated;
-- =============================================================================
-- 3. OPS/METRICS VIEWS - Remove all access from anon/authenticated
-- =============================================================================
-- These are internal operations views, accessed via service_role only.
-- v_ceo_financial_summary
REVOKE ALL ON public.v_ceo_financial_summary
FROM anon;
REVOKE ALL ON public.v_ceo_financial_summary
FROM authenticated;
-- v_daily_health
REVOKE ALL ON public.v_daily_health
FROM anon;
REVOKE ALL ON public.v_daily_health
FROM authenticated;
-- v_enforcement_action_stats
REVOKE ALL ON public.v_enforcement_action_stats
FROM anon;
REVOKE ALL ON public.v_enforcement_action_stats
FROM authenticated;
-- v_enforcement_actions_overview
REVOKE ALL ON public.v_enforcement_actions_overview
FROM anon;
REVOKE ALL ON public.v_enforcement_actions_overview
FROM authenticated;
-- v_enforcement_actions_pending_signature
REVOKE ALL ON public.v_enforcement_actions_pending_signature
FROM anon;
REVOKE ALL ON public.v_enforcement_actions_pending_signature
FROM authenticated;
-- v_enforcement_actions_recent
REVOKE ALL ON public.v_enforcement_actions_recent
FROM anon;
REVOKE ALL ON public.v_enforcement_actions_recent
FROM authenticated;
-- v_enforcement_case_summary
REVOKE ALL ON public.v_enforcement_case_summary
FROM anon;
REVOKE ALL ON public.v_enforcement_case_summary
FROM authenticated;
-- v_enforcement_pipeline_status
REVOKE ALL ON public.v_enforcement_pipeline_status
FROM anon;
REVOKE ALL ON public.v_enforcement_pipeline_status
FROM authenticated;
-- v_enforcement_tier_overview
REVOKE ALL ON public.v_enforcement_tier_overview
FROM anon;
REVOKE ALL ON public.v_enforcement_tier_overview
FROM authenticated;
-- v_intake_monitor
REVOKE ALL ON public.v_intake_monitor
FROM anon;
REVOKE ALL ON public.v_intake_monitor
FROM authenticated;
-- v_intake_queue
REVOKE ALL ON public.v_intake_queue
FROM anon;
REVOKE ALL ON public.v_intake_queue
FROM authenticated;
-- v_litigation_budget_summary
REVOKE ALL ON public.v_litigation_budget_summary
FROM anon;
REVOKE ALL ON public.v_litigation_budget_summary
FROM authenticated;
-- v_metrics_enforcement
REVOKE ALL ON public.v_metrics_enforcement
FROM anon;
REVOKE ALL ON public.v_metrics_enforcement
FROM authenticated;
-- v_metrics_intake_daily
REVOKE ALL ON public.v_metrics_intake_daily
FROM anon;
REVOKE ALL ON public.v_metrics_intake_daily
FROM authenticated;
-- v_metrics_pipeline
REVOKE ALL ON public.v_metrics_pipeline
FROM anon;
REVOKE ALL ON public.v_metrics_pipeline
FROM authenticated;
-- v_ops_alerts
REVOKE ALL ON public.v_ops_alerts
FROM anon;
REVOKE ALL ON public.v_ops_alerts
FROM authenticated;
-- v_portfolio_judgments
REVOKE ALL ON public.v_portfolio_judgments
FROM anon;
REVOKE ALL ON public.v_portfolio_judgments
FROM authenticated;
COMMIT;
-- =============================================================================
-- ROLLBACK STATEMENTS (run manually if needed)
-- =============================================================================
-- WARNING: Only use these if you need to revert. This reopens security holes.
--
-- Pipeline views (restore full access):
-- GRANT ALL ON public.v_plaintiffs_overview TO anon, authenticated;
-- GRANT ALL ON public.v_judgment_pipeline TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_overview TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_recent TO anon, authenticated;
-- GRANT ALL ON public.v_plaintiff_call_queue TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_timeline TO anon, authenticated;
--
-- Internal views (restore full access):
-- GRANT ALL ON public.v_cases TO anon, authenticated;
-- GRANT ALL ON public.v_entities_simple TO anon, authenticated;
-- GRANT ALL ON public.v_collectability_snapshot TO anon, authenticated;
-- GRANT ALL ON public.v_priority_pipeline TO anon, authenticated;
-- GRANT ALL ON public.v_radar TO anon, authenticated;
-- GRANT ALL ON public.v_migration_status TO anon, authenticated;
--
-- Ops/Metrics views (restore full access):
-- GRANT ALL ON public.v_ceo_financial_summary TO anon, authenticated;
-- GRANT ALL ON public.v_daily_health TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_action_stats TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_actions_overview TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_actions_pending_signature TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_actions_recent TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_case_summary TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_pipeline_status TO anon, authenticated;
-- GRANT ALL ON public.v_enforcement_tier_overview TO anon, authenticated;
-- GRANT ALL ON public.v_intake_monitor TO anon, authenticated;
-- GRANT ALL ON public.v_intake_queue TO anon, authenticated;
-- GRANT ALL ON public.v_litigation_budget_summary TO anon, authenticated;
-- GRANT ALL ON public.v_metrics_enforcement TO anon, authenticated;
-- GRANT ALL ON public.v_metrics_intake_daily TO anon, authenticated;
-- GRANT ALL ON public.v_metrics_pipeline TO anon, authenticated;
-- GRANT ALL ON public.v_ops_alerts TO anon, authenticated;
-- GRANT ALL ON public.v_portfolio_judgments TO anon, authenticated;
-- =============================================================================
-- =============================================================================
-- VERIFICATION QUERY - Check view grants after migration
-- =============================================================================
/*
 SELECT 
 table_name AS view_name,
 grantee,
 string_agg(privilege_type, ', ' ORDER BY privilege_type) AS privileges
 FROM information_schema.table_privileges
 WHERE table_schema = 'public'
 AND table_name LIKE 'v_%'
 AND grantee IN ('anon', 'authenticated')
 GROUP BY table_name, grantee
 ORDER BY table_name, grantee;
 */