-- Migration: 0207_audit_tables_append_only.sql
-- Purpose: Enforce append-only semantics on FCRA/FDCPA audit tables by revoking
--          UPDATE and DELETE grants from both 'authenticated' and 'service_role'.
--          These tables are immutable audit logs that should only support INSERT
--          operations from application code.
--
-- Tables affected:
--   - public.external_data_calls (FCRA audit log)
--   - public.communications (FDCPA communications log)
--
-- Note: postgres retains full privileges for admin/migration use.
BEGIN;
-- Revoke UPDATE and DELETE on external_data_calls (FCRA audit)
REVOKE
UPDATE,
    DELETE ON public.external_data_calls
FROM authenticated;
REVOKE
UPDATE,
    DELETE ON public.external_data_calls
FROM service_role;
-- Revoke UPDATE and DELETE on communications (FDCPA audit)
REVOKE
UPDATE,
    DELETE ON public.communications
FROM authenticated;
REVOKE
UPDATE,
    DELETE ON public.communications
FROM service_role;
-- Add comments documenting the append-only constraint
COMMENT ON TABLE public.external_data_calls IS 'FCRA audit log for external data API calls. APPEND-ONLY: no UPDATE/DELETE for authenticated/service_role.';
COMMENT ON TABLE public.communications IS 'FDCPA-regulated communications log. APPEND-ONLY: no UPDATE/DELETE for authenticated/service_role.';
COMMIT;
