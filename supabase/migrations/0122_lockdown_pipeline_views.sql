-- 0122_lockdown_pipeline_views.sql
-- Tighten privileges on internal dashboard/case copilot views so that only service_role can access them.
BEGIN;
-- v_case_copilot_latest should not be directly visible to anon/authenticated
REVOKE ALL PRIVILEGES ON TABLE public.v_case_copilot_latest
FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.v_case_copilot_latest
FROM authenticated;
-- v_pipeline_snapshot should be internal only
REVOKE ALL PRIVILEGES ON TABLE public.v_pipeline_snapshot
FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.v_pipeline_snapshot
FROM authenticated;
-- v_priority_pipeline should be internal only
REVOKE ALL PRIVILEGES ON TABLE public.v_priority_pipeline
FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.v_priority_pipeline
FROM authenticated;
COMMIT;