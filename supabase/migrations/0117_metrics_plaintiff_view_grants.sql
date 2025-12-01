-- 0117_metrics_plaintiff_view_grants.sql
-- Lock down metrics + plaintiff detail views per security audit.
-- migrate:up
BEGIN;
-- Metrics views: service role only.
REVOKE ALL ON public.v_metrics_enforcement
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_enforcement
FROM anon;
REVOKE ALL ON public.v_metrics_enforcement
FROM authenticated;
GRANT SELECT ON public.v_metrics_enforcement TO service_role;
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
-- Plaintiff detail views: service role only.
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM anon;
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM authenticated;
GRANT SELECT ON public.v_plaintiff_open_tasks TO service_role;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM PUBLIC;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM anon;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM authenticated;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO service_role;
SELECT public.pgrst_reload();
COMMIT;
-- migrate:down
BEGIN;
-- Revert plaintiff detail views to anon/auth read-only visibility.
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
-- Revert metrics views to anon/auth read-only visibility.
REVOKE ALL ON public.v_metrics_enforcement
FROM PUBLIC;
REVOKE ALL ON public.v_metrics_enforcement
FROM anon;
REVOKE ALL ON public.v_metrics_enforcement
FROM authenticated;
GRANT SELECT ON public.v_metrics_enforcement TO anon;
GRANT SELECT ON public.v_metrics_enforcement TO authenticated;
GRANT SELECT ON public.v_metrics_enforcement TO service_role;
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
SELECT public.pgrst_reload();
COMMIT;