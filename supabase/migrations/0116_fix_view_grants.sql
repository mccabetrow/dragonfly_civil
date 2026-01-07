-- 0116_fix_view_grants.sql
-- Align dashboard and metrics view grants with security_audit expectations.
-- migrate:up
BEGIN;
-- Enforcement + dashboard views: anon/authenticated get SELECT only.
REVOKE ALL ON public.v_enforcement_overview
FROM PUBLIC;
REVOKE ALL ON public.v_enforcement_overview
FROM anon;
REVOKE ALL ON public.v_enforcement_overview
FROM authenticated;
GRANT SELECT ON public.v_enforcement_overview TO anon;
GRANT SELECT ON public.v_enforcement_overview TO authenticated;
GRANT SELECT ON public.v_enforcement_overview TO service_role;
REVOKE ALL ON public.v_enforcement_recent
FROM PUBLIC;
REVOKE ALL ON public.v_enforcement_recent
FROM anon;
REVOKE ALL ON public.v_enforcement_recent
FROM authenticated;
GRANT SELECT ON public.v_enforcement_recent TO anon;
GRANT SELECT ON public.v_enforcement_recent TO authenticated;
GRANT SELECT ON public.v_enforcement_recent TO service_role;
REVOKE ALL ON public.v_judgment_pipeline
FROM PUBLIC;
REVOKE ALL ON public.v_judgment_pipeline
FROM anon;
REVOKE ALL ON public.v_judgment_pipeline
FROM authenticated;
GRANT SELECT ON public.v_judgment_pipeline TO anon;
GRANT SELECT ON public.v_judgment_pipeline TO authenticated;
GRANT SELECT ON public.v_judgment_pipeline TO service_role;
REVOKE ALL ON public.v_plaintiff_call_queue
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiff_call_queue
FROM anon;
REVOKE ALL ON public.v_plaintiff_call_queue
FROM authenticated;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon;
GRANT SELECT ON public.v_plaintiff_call_queue TO authenticated;
GRANT SELECT ON public.v_plaintiff_call_queue TO service_role;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM anon;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM authenticated;
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon;
GRANT SELECT ON public.v_plaintiff_open_tasks TO authenticated;
GRANT SELECT ON public.v_plaintiff_open_tasks TO service_role;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM anon;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM authenticated;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO anon;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO authenticated;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO service_role;
REVOKE ALL ON public.v_plaintiffs_overview
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiffs_overview
FROM anon;
REVOKE ALL ON public.v_plaintiffs_overview
FROM authenticated;
GRANT SELECT ON public.v_plaintiffs_overview TO anon;
GRANT SELECT ON public.v_plaintiffs_overview TO authenticated;
GRANT SELECT ON public.v_plaintiffs_overview TO service_role;
-- Metrics views: only service_role retains SELECT.
REVOKE ALL ON public.v_metrics_intake_daily
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_intake_daily
FROM anon;
REVOKE ALL ON public.v_metrics_intake_daily
FROM authenticated;
GRANT SELECT ON public.v_metrics_intake_daily TO service_role;
REVOKE ALL ON public.v_metrics_pipeline
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_pipeline
FROM anon;
REVOKE ALL ON public.v_metrics_pipeline
FROM authenticated;
GRANT SELECT ON public.v_metrics_pipeline TO service_role;
REVOKE ALL ON public.v_metrics_enforcement
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_enforcement
FROM anon;
REVOKE ALL ON public.v_metrics_enforcement
FROM authenticated;
GRANT SELECT ON public.v_metrics_enforcement TO service_role;
SELECT public.pgrst_reload();
COMMIT;
-- migrate:down
BEGIN;
-- Revert metrics views to expose SELECT to anon/authenticated if needed by legacy flows.
REVOKE ALL ON public.v_metrics_intake_daily
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_intake_daily
FROM anon;
REVOKE ALL ON public.v_metrics_intake_daily
FROM authenticated;
GRANT SELECT ON public.v_metrics_intake_daily TO anon;
GRANT SELECT ON public.v_metrics_intake_daily TO authenticated;
GRANT SELECT ON public.v_metrics_intake_daily TO service_role;
REVOKE ALL ON public.v_metrics_pipeline
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_pipeline
FROM anon;
REVOKE ALL ON public.v_metrics_pipeline
FROM authenticated;
GRANT SELECT ON public.v_metrics_pipeline TO anon;
GRANT SELECT ON public.v_metrics_pipeline TO authenticated;
GRANT SELECT ON public.v_metrics_pipeline TO service_role;
REVOKE ALL ON public.v_metrics_enforcement
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_enforcement
FROM anon;
REVOKE ALL ON public.v_metrics_enforcement
FROM authenticated;
GRANT SELECT ON public.v_metrics_enforcement TO anon;
GRANT SELECT ON public.v_metrics_enforcement TO authenticated;
GRANT SELECT ON public.v_metrics_enforcement TO service_role;
-- Dashboard views revert to SELECT grants (same as previous default).
REVOKE ALL ON public.v_enforcement_overview
FROM PUBLIC;
REVOKE ALL ON public.v_enforcement_overview
FROM anon;
REVOKE ALL ON public.v_enforcement_overview
FROM authenticated;
GRANT SELECT ON public.v_enforcement_overview TO anon;
GRANT SELECT ON public.v_enforcement_overview TO authenticated;
GRANT SELECT ON public.v_enforcement_overview TO service_role;
REVOKE ALL ON public.v_enforcement_recent
FROM PUBLIC;
REVOKE ALL ON public.v_enforcement_recent
FROM anon;
REVOKE ALL ON public.v_enforcement_recent
FROM authenticated;
GRANT SELECT ON public.v_enforcement_recent TO anon;
GRANT SELECT ON public.v_enforcement_recent TO authenticated;
GRANT SELECT ON public.v_enforcement_recent TO service_role;
REVOKE ALL ON public.v_judgment_pipeline
FROM PUBLIC;
REVOKE ALL ON public.v_judgment_pipeline
FROM anon;
REVOKE ALL ON public.v_judgment_pipeline
FROM authenticated;
GRANT SELECT ON public.v_judgment_pipeline TO anon;
GRANT SELECT ON public.v_judgment_pipeline TO authenticated;
GRANT SELECT ON public.v_judgment_pipeline TO service_role;
REVOKE ALL ON public.v_plaintiff_call_queue
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiff_call_queue
FROM anon;
REVOKE ALL ON public.v_plaintiff_call_queue
FROM authenticated;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon;
GRANT SELECT ON public.v_plaintiff_call_queue TO authenticated;
GRANT SELECT ON public.v_plaintiff_call_queue TO service_role;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM anon;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM authenticated;
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon;
GRANT SELECT ON public.v_plaintiff_open_tasks TO authenticated;
GRANT SELECT ON public.v_plaintiff_open_tasks TO service_role;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM anon;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM authenticated;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO anon;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO authenticated;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO service_role;
REVOKE ALL ON public.v_plaintiffs_overview
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiffs_overview
FROM anon;
REVOKE ALL ON public.v_plaintiffs_overview
FROM authenticated;
GRANT SELECT ON public.v_plaintiffs_overview TO anon;
GRANT SELECT ON public.v_plaintiffs_overview TO authenticated;
GRANT SELECT ON public.v_plaintiffs_overview TO service_role;
SELECT public.pgrst_reload();
COMMIT;
