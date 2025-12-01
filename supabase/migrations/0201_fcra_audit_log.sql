-- ============================================================================
-- 0201_fcra_audit_log.sql
-- FCRA Audit Log: Track all external data provider API calls for compliance
-- ============================================================================
--
-- PURPOSE:
--   The Fair Credit Reporting Act (FCRA) requires maintaining an audit trail
--   for all consumer data access from skip-trace vendors and credit bureaus.
--   This migration creates an append-only audit log for external API calls.
--
-- USAGE:
--   n8n workflows and workers should call public.log_external_data_call()
--   whenever they invoke an external data provider (idiCORE, TLOxp, Tracers,
--   LexisNexis, etc.) to query consumer information.
--
-- SAFE PATTERNS:
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE POLICY ... (idempotent via DROP IF EXISTS first)
--   - CREATE OR REPLACE FUNCTION
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- EXTENSION: Ensure uuid-ossp is available for uuid_generate_v4()
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
-- ============================================================================
-- TABLE: public.external_data_calls
-- ============================================================================
-- Append-only audit log for all external data provider API calls.
-- Each row represents a single API request to a skip-trace or enrichment
-- vendor, linked to the judgment being researched.
--
-- This table is critical for FCRA compliance audits and must never be
-- truncated or have rows deleted in production.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.external_data_calls (
    -- Primary key
    id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
    -- Link to the judgment being researched (nullable for bulk/batch queries)
    judgment_id uuid REFERENCES public.core_judgments(id) ON DELETE
    SET NULL,
        -- Provider identification
        provider text NOT NULL,
        -- e.g., 'idiCORE', 'TLOxp', 'Tracers', 'LexisNexis'
        endpoint text NOT NULL,
        -- API endpoint name or path, e.g., '/person/search'
        -- Request timing
        requested_at timestamptz NOT NULL DEFAULT now(),
        -- Requestor (optional - auth.uid() if called from authenticated context)
        requested_by uuid,
        -- Supabase auth user ID if available
        -- Response status
        status text NOT NULL,
        -- 'success', 'error', 'timeout', 'rate_limited'
        http_code integer,
        -- HTTP response code (200, 400, 500, etc.)
        error_message text,
        -- Error details if status != 'success'
        -- Metadata (IMPORTANT: Never store raw PII in this field)
        -- Store only: query type, record count, confidence scores, timing metrics
        raw_request_meta jsonb NOT NULL DEFAULT '{}'::jsonb
);
-- ============================================================================
-- INDEXES
-- ============================================================================
-- Index for querying by judgment (most common audit query pattern)
CREATE INDEX IF NOT EXISTS idx_external_data_calls_judgment_id ON public.external_data_calls(judgment_id);
-- Index for querying by provider (for vendor usage reports)
CREATE INDEX IF NOT EXISTS idx_external_data_calls_provider ON public.external_data_calls(provider);
-- Index for querying by time range (for compliance audits)
CREATE INDEX IF NOT EXISTS idx_external_data_calls_requested_at ON public.external_data_calls(requested_at DESC);
-- Composite index for common audit query: judgment + time range
CREATE INDEX IF NOT EXISTS idx_external_data_calls_judgment_time ON public.external_data_calls(judgment_id, requested_at DESC);
-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE public.external_data_calls IS 'FCRA audit log for external data provider API calls. Append-only; do not delete rows.';
COMMENT ON COLUMN public.external_data_calls.id IS 'Unique identifier for this API call record.';
COMMENT ON COLUMN public.external_data_calls.judgment_id IS 'Reference to the judgment being researched. NULL for batch/bulk queries.';
COMMENT ON COLUMN public.external_data_calls.provider IS 'Name of the external data provider (idiCORE, TLOxp, Tracers, LexisNexis, etc.).';
COMMENT ON COLUMN public.external_data_calls.endpoint IS 'API endpoint name or path that was called.';
COMMENT ON COLUMN public.external_data_calls.requested_at IS 'Timestamp when the API request was initiated.';
COMMENT ON COLUMN public.external_data_calls.requested_by IS 'Supabase auth.uid() of the user who initiated the request, if available.';
COMMENT ON COLUMN public.external_data_calls.status IS 'Result status: success, error, timeout, rate_limited.';
COMMENT ON COLUMN public.external_data_calls.http_code IS 'HTTP response code from the external API.';
COMMENT ON COLUMN public.external_data_calls.error_message IS 'Error details if the request failed.';
COMMENT ON COLUMN public.external_data_calls.raw_request_meta IS 'Redacted metadata about the request/response. NEVER store raw PII here.';
-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
-- Enable RLS on the audit log table.
-- This is an append-only audit trail:
--   - authenticated users can SELECT (read audit history)
--   - only service_role can INSERT (workers/n8n log entries)
--   - UPDATE and DELETE are blocked for everyone (immutable audit trail)
-- ============================================================================
ALTER TABLE public.external_data_calls ENABLE ROW LEVEL SECURITY;
-- Drop existing policies if they exist (for idempotency)
DROP POLICY IF EXISTS external_data_calls_select_authenticated ON public.external_data_calls;
DROP POLICY IF EXISTS external_data_calls_insert_service ON public.external_data_calls;
-- Allow authenticated users to read audit log entries
-- This supports compliance dashboards and audit queries
CREATE POLICY external_data_calls_select_authenticated ON public.external_data_calls FOR
SELECT USING (auth.role() IN ('authenticated', 'service_role'));
-- Allow only service_role to insert new audit log entries
-- Workers and n8n use service_role credentials
CREATE POLICY external_data_calls_insert_service ON public.external_data_calls FOR
INSERT WITH CHECK (auth.role() = 'service_role');
-- NOTE: No UPDATE or DELETE policies are created.
-- This makes the table append-only, which is required for audit compliance.
-- Any attempt to UPDATE or DELETE will be denied by RLS.
-- ============================================================================
-- GRANTS
-- ============================================================================
-- Revoke all from public, grant specific permissions
REVOKE ALL ON public.external_data_calls
FROM PUBLIC;
REVOKE ALL ON public.external_data_calls
FROM anon;
-- authenticated can only SELECT (read audit entries)
GRANT SELECT ON public.external_data_calls TO authenticated;
-- service_role can SELECT and INSERT (but not UPDATE/DELETE due to RLS)
GRANT SELECT,
    INSERT ON public.external_data_calls TO service_role;
-- ============================================================================
-- FUNCTION: public.log_external_data_call
-- ============================================================================
-- RPC function for logging external data provider API calls.
--
-- USAGE (from n8n or workers):
--   SELECT public.log_external_data_call(
--       _judgment_id := 'uuid-of-judgment',
--       _provider := 'idiCORE',
--       _endpoint := '/person/search',
--       _status := 'success',
--       _http_code := 200,
--       _error_message := NULL,
--       _meta := '{"query_type": "person", "results_count": 3}'::jsonb
--   );
--
-- SECURITY:
--   - SECURITY DEFINER: Runs with owner privileges to bypass RLS for insert
--   - Restricted to service_role via REVOKE/GRANT
--
-- FCRA COMPLIANCE:
--   Call this function EVERY TIME an external skip-trace or enrichment API
--   is invoked. This creates the required audit trail for FCRA compliance.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.log_external_data_call(
        _judgment_id uuid,
        _provider text,
        _endpoint text,
        _status text,
        _http_code integer DEFAULT NULL,
        _error_message text DEFAULT NULL,
        _meta jsonb DEFAULT '{}'::jsonb
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _new_id uuid;
_requested_by uuid;
BEGIN -- Attempt to capture the calling user's ID if available
BEGIN _requested_by := auth.uid();
EXCEPTION
WHEN OTHERS THEN _requested_by := NULL;
END;
-- Insert the audit log entry
INSERT INTO public.external_data_calls (
        judgment_id,
        provider,
        endpoint,
        requested_at,
        requested_by,
        status,
        http_code,
        error_message,
        raw_request_meta
    )
VALUES (
        _judgment_id,
        _provider,
        _endpoint,
        now(),
        _requested_by,
        _status,
        _http_code,
        _error_message,
        COALESCE(_meta, '{}'::jsonb)
    )
RETURNING id INTO _new_id;
RETURN _new_id;
END;
$$;
-- ============================================================================
-- FUNCTION COMMENTS
-- ============================================================================
COMMENT ON FUNCTION public.log_external_data_call IS 'Logs an external data provider API call for FCRA compliance auditing. Call from n8n/workers when invoking skip-trace APIs (idiCORE, TLOxp, Tracers, LexisNexis). Params: _judgment_id (UUID, nullable), _provider, _endpoint, _status, _http_code, _error_message, _meta (jsonb). NEVER store raw PII in _meta.';
-- ============================================================================
-- FUNCTION PERMISSIONS
-- ============================================================================
-- Restrict function execution to service_role only.
-- n8n and workers use service_role credentials.
REVOKE ALL ON FUNCTION public.log_external_data_call(uuid, text, text, text, integer, text, jsonb)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.log_external_data_call(uuid, text, text, text, integer, text, jsonb)
FROM anon;
REVOKE ALL ON FUNCTION public.log_external_data_call(uuid, text, text, text, integer, text, jsonb)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.log_external_data_call(uuid, text, text, text, integer, text, jsonb) TO service_role;
-- ============================================================================
-- RELOAD POSTGREST SCHEMA CACHE
-- ============================================================================
-- Notify PostgREST to pick up the new table and function
SELECT public.pgrst_reload();
COMMIT;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================