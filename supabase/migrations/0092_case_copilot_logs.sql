-- 0092_case_copilot_logs.sql
-- Track Case Copilot invocations for auditing and capacity planning.
BEGIN;
CREATE TABLE IF NOT EXISTS public.case_copilot_logs (
    id bigserial PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES public.enforcement_cases (
        id
    ) ON DELETE CASCADE,
    model text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX IF NOT EXISTS case_copilot_logs_case_idx ON public.case_copilot_logs (
    case_id, created_at DESC
);
ALTER TABLE public.case_copilot_logs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS case_copilot_logs_service_rw ON public.case_copilot_logs;
CREATE POLICY case_copilot_logs_service_rw ON public.case_copilot_logs FOR ALL USING (
    auth.role() = 'service_role'
) WITH CHECK (auth.role() = 'service_role');
REVOKE ALL ON public.case_copilot_logs
FROM public;
REVOKE ALL ON public.case_copilot_logs
FROM anon;
REVOKE ALL ON public.case_copilot_logs
FROM authenticated;
GRANT SELECT,
INSERT,
UPDATE,
DELETE ON public.case_copilot_logs TO service_role;
COMMIT;

