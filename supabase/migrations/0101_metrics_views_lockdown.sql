-- 0101_metrics_views_lockdown.sql
-- Lock down executive metrics views to the explicit PostgREST roles and ensure service_role keeps full privileges.
REVOKE ALL PRIVILEGES ON public.v_metrics_intake_daily
FROM public;
REVOKE ALL PRIVILEGES ON public.v_metrics_pipeline
FROM public;
REVOKE ALL PRIVILEGES ON public.v_metrics_enforcement
FROM public;
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

