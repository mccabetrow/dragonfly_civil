-- 0118_security_audit_final.sql
-- Align metrics + internal plaintiff views with tools.security_audit expectations.
BEGIN;
-- Metrics views: service_role only (no anon/auth)
REVOKE ALL ON public.v_metrics_intake_daily
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON public.v_metrics_pipeline
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON public.v_metrics_enforcement
FROM PUBLIC,
    anon,
    authenticated;
GRANT SELECT ON public.v_metrics_intake_daily TO service_role;
GRANT SELECT ON public.v_metrics_pipeline TO service_role;
GRANT SELECT ON public.v_metrics_enforcement TO service_role;
-- Internal-only plaintiff views: service_role only (no anon/auth)
REVOKE ALL ON public.v_plaintiff_open_tasks
FROM PUBLIC,
    anon,
    authenticated;
REVOKE ALL ON public.v_plaintiffs_jbi_900
FROM PUBLIC,
    anon,
    authenticated;
GRANT SELECT ON public.v_plaintiff_open_tasks TO service_role;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO service_role;
-- Make sure PostgREST sees new grants
SELECT public.pgrst_reload();
COMMIT;
