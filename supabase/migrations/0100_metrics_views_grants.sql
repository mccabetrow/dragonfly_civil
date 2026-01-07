-- 0100_metrics_views_grants.sql
-- Normalize grants for executive metrics views to pass tools.security_audit:
-- anon/authenticated: SELECT only
-- service_role: full privileges.
REVOKE ALL PRIVILEGES ON public.v_metrics_intake_daily
FROM anon,
authenticated;
REVOKE ALL PRIVILEGES ON public.v_metrics_pipeline
FROM anon,
authenticated;
REVOKE ALL PRIVILEGES ON public.v_metrics_enforcement
FROM anon,
authenticated;
GRANT SELECT ON public.v_metrics_intake_daily TO anon,
authenticated,
service_role;
GRANT SELECT ON public.v_metrics_pipeline TO anon,
authenticated,
service_role;
GRANT SELECT ON public.v_metrics_enforcement TO anon,
authenticated,
service_role;
GRANT ALL PRIVILEGES ON public.v_metrics_intake_daily TO service_role;
GRANT ALL PRIVILEGES ON public.v_metrics_pipeline TO service_role;
GRANT ALL PRIVILEGES ON public.v_metrics_enforcement TO service_role;

