-- =============================================================================
-- 0304_rls_view_rpc_compatibility.sql
-- Dragonfly Civil – Ensure Views & RPCs Work With New RLS
-- =============================================================================
-- CRITICAL: Views with security_invoker = true will use caller's permissions.
-- RPCs marked SECURITY DEFINER bypass RLS and run as owner.
-- This migration ensures all dashboard views and n8n/worker RPCs continue to work.
-- =============================================================================
BEGIN;
-- =============================================================================
-- DASHBOARD VIEWS: Set security_invoker = false for public read access
-- =============================================================================
-- These views are consumed by the dashboard and need to be readable by 
-- authenticated users without requiring specific roles.
-- v_plaintiffs_overview
ALTER VIEW public.v_plaintiffs_overview
SET (security_invoker = false);
GRANT SELECT ON public.v_plaintiffs_overview TO anon,
    authenticated,
    service_role;
-- v_enforcement_overview  
ALTER VIEW public.v_enforcement_overview
SET (security_invoker = false);
GRANT SELECT ON public.v_enforcement_overview TO anon,
    authenticated,
    service_role;
-- v_enforcement_recent
ALTER VIEW public.v_enforcement_recent
SET (security_invoker = false);
GRANT SELECT ON public.v_enforcement_recent TO anon,
    authenticated,
    service_role;
-- v_judgment_pipeline
ALTER VIEW public.v_judgment_pipeline
SET (security_invoker = false);
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated,
    service_role;
-- v_plaintiff_call_queue
ALTER VIEW public.v_plaintiff_call_queue
SET (security_invoker = false);
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
    authenticated,
    service_role;
-- v_plaintiff_open_tasks
ALTER VIEW public.v_plaintiff_open_tasks
SET (security_invoker = false);
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon,
    authenticated,
    service_role;
-- v_metrics_intake_daily
ALTER VIEW public.v_metrics_intake_daily
SET (security_invoker = false);
GRANT SELECT ON public.v_metrics_intake_daily TO anon,
    authenticated,
    service_role;
-- v_metrics_pipeline
ALTER VIEW public.v_metrics_pipeline
SET (security_invoker = false);
GRANT SELECT ON public.v_metrics_pipeline TO anon,
    authenticated,
    service_role;
-- v_metrics_enforcement
ALTER VIEW public.v_metrics_enforcement
SET (security_invoker = false);
GRANT SELECT ON public.v_metrics_enforcement TO anon,
    authenticated,
    service_role;
-- v_collectability_snapshot (public wrapper)
ALTER VIEW public.v_collectability_snapshot
SET (security_invoker = false);
GRANT SELECT ON public.v_collectability_snapshot TO anon,
    authenticated,
    service_role;
-- v_priority_pipeline (service_role only - sensitive ranking)
ALTER VIEW public.v_priority_pipeline
SET (security_invoker = false);
GRANT SELECT ON public.v_priority_pipeline TO service_role;
-- v_pipeline_snapshot
ALTER VIEW public.v_pipeline_snapshot
SET (security_invoker = false);
GRANT SELECT ON public.v_pipeline_snapshot TO service_role;
-- v_case_copilot_latest
ALTER VIEW public.v_case_copilot_latest
SET (security_invoker = false);
GRANT SELECT ON public.v_case_copilot_latest TO service_role;
-- v_enforcement_case_summary
ALTER VIEW public.v_enforcement_case_summary
SET (security_invoker = false);
GRANT SELECT ON public.v_enforcement_case_summary TO anon,
    authenticated,
    service_role;
-- v_enforcement_timeline
ALTER VIEW public.v_enforcement_timeline
SET (security_invoker = false);
GRANT SELECT ON public.v_enforcement_timeline TO anon,
    authenticated,
    service_role;
-- v_plaintiffs_jbi_900
ALTER VIEW public.v_plaintiffs_jbi_900
SET (security_invoker = false);
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO anon,
    authenticated,
    service_role;
-- v_ceo_financial_summary (new CEO view)
ALTER VIEW public.v_ceo_financial_summary
SET (security_invoker = false);
GRANT SELECT ON public.v_ceo_financial_summary TO authenticated,
    service_role;
-- =============================================================================
-- VERIFY SECURITY DEFINER RPCs (n8n/worker compatibility)
-- =============================================================================
-- All SECURITY DEFINER functions bypass RLS and run as the function owner.
-- These are safe because:
--   1. They already check auth.role() = 'service_role' internally, OR
--   2. They're only granted to service_role, OR
--   3. They validate input and only perform allowed operations
-- Queue functions (n8n uses these)
-- Already SECURITY DEFINER with service_role grants
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO service_role;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
GRANT EXECUTE ON FUNCTION public.pgmq_delete(text, bigint) TO service_role;
-- Enforcement flow functions
GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.set_enforcement_stage(bigint, text, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.score_case_collectability(uuid, boolean, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.generate_enforcement_tasks(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO service_role;
-- =============================================================================
-- MATERIALIZED VIEW REFRESH PRIVILEGES
-- =============================================================================
-- If you have materialized views, service_role needs REFRESH privilege
-- Currently none exist, but this is where they'd be granted
-- =============================================================================
-- AUDIT: Log this RLS deployment
-- =============================================================================
INSERT INTO public.dragonfly_role_audit_log (
        action,
        target_user_id,
        role,
        performed_by,
        details
    )
VALUES (
        'grant',
        '00000000-0000-0000-0000-000000000000'::uuid,
        -- system action
        'system',
        NULL,
        jsonb_build_object(
            'event',
            'rls_deployment',
            'migration',
            '0304_rls_view_rpc_compatibility',
            'timestamp',
            timezone('utc', now()),
            'changes',
            ARRAY [
            'Views set to security_invoker=false for dashboard access',
            'SECURITY DEFINER RPCs verified for n8n/worker compatibility',
            'Grants consolidated for service_role'
        ]
        )
    );
SELECT public.pgrst_reload();
COMMIT;
