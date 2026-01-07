-- Add ops_triage_alerts RPC alias for n8n flow compatibility
BEGIN;
-- =========================================================================
-- public.ops_triage_alerts (RPC alias) – matches n8n flow expectation
-- The flow calls rpc/ops_triage_alerts with { "limit": 25 }
-- =========================================================================
CREATE OR REPLACE FUNCTION public.ops_triage_alerts(p_limit integer DEFAULT 50) RETURNS SETOF public.ops_triage_alerts LANGUAGE sql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT *
FROM public.ops_triage_alerts_fetch('open', p_limit);
$$;
GRANT EXECUTE ON FUNCTION public.ops_triage_alerts(integer) TO authenticated,
    service_role;
COMMIT;
