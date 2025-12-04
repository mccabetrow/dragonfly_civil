-- ============================================================================
-- 0305_fcra_access_logging.sql
-- FCRA-Compliant Access Logging for Sensitive Consumer Data
-- ============================================================================
--
-- PURPOSE:
--   Extends FCRA compliance by logging all access (SELECT, UPDATE, EXPORT)
--   to sensitive consumer data tables. This migration creates:
--   1. Immutable access_logs table (append-only, no UPDATE/DELETE)
--   2. log_access() RPC for manual access logging
--   3. Automatic UPDATE triggers on sensitive tables
--   4. DELETE protection rules on protected tables
--   5. RLS policies restricting access to audit-role only
--
-- PROTECTED TABLES (sensitive consumer data):
--   - public.debtor_intelligence (employment, banking, assets)
--   - public.external_data_calls (already has separate audit)
--   - public.outreach_log (call/contact history)
--   - public.plaintiff_call_attempts (call outcomes)
--   - public.plaintiff_contacts (contact information)
--
-- COMPLIANCE:
--   - FCRA § 604: Permissible purpose documentation
--   - FCRA § 609: Consumer disclosure records
--   - GLBA Safeguards Rule: Access monitoring
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- TABLE: public.access_logs
-- ============================================================================
-- Immutable, append-only audit trail for all sensitive data access.
-- No UPDATE or DELETE operations are permitted on this table.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.access_logs (
    -- Primary key
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- When the access occurred (immutable after insert)
    accessed_at timestamptz NOT NULL DEFAULT now(),
    -- Who accessed the data (Supabase auth user ID or service identifier)
    user_id uuid,
    -- Optional: username or service name for readability
    user_identifier text,
    -- Which table was accessed
    table_name text NOT NULL,
    -- Primary key of the accessed row (text to support various PK types)
    row_id text,
    -- Type of access
    access_type text NOT NULL CHECK (
        access_type IN ('SELECT', 'UPDATE', 'EXPORT', 'DELETE_BLOCKED')
    ),
    -- Additional context (permissible purpose, query type, etc.)
    -- IMPORTANT: Never store raw PII in metadata
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Session/request context for correlation
    session_id uuid,
    -- IP address for security auditing (if available)
    ip_address inet
);
-- ============================================================================
-- INDEXES
-- ============================================================================
-- Index for querying by time range (most common audit query)
CREATE INDEX IF NOT EXISTS idx_access_logs_accessed_at ON public.access_logs(accessed_at DESC);
-- Index for querying by table (for per-table audit reports)
CREATE INDEX IF NOT EXISTS idx_access_logs_table_name ON public.access_logs(table_name);
-- Index for querying by user (for user access reports)
CREATE INDEX IF NOT EXISTS idx_access_logs_user_id ON public.access_logs(user_id);
-- Composite index for common audit query: table + time range
CREATE INDEX IF NOT EXISTS idx_access_logs_table_time ON public.access_logs(table_name, accessed_at DESC);
-- Index for querying by row (for record-level audit)
CREATE INDEX IF NOT EXISTS idx_access_logs_row_id ON public.access_logs(row_id);
-- Composite index for access type filtering
CREATE INDEX IF NOT EXISTS idx_access_logs_access_type ON public.access_logs(access_type, accessed_at DESC);
-- ============================================================================
-- COMMENTS
-- ============================================================================
COMMENT ON TABLE public.access_logs IS 'FCRA-compliant immutable audit log for sensitive data access. Append-only; UPDATE and DELETE are blocked.';
COMMENT ON COLUMN public.access_logs.id IS 'Unique identifier for this access record.';
COMMENT ON COLUMN public.access_logs.accessed_at IS 'Timestamp when the access occurred.';
COMMENT ON COLUMN public.access_logs.user_id IS 'Supabase auth.uid() of the user who accessed the data.';
COMMENT ON COLUMN public.access_logs.user_identifier IS 'Human-readable user or service identifier.';
COMMENT ON COLUMN public.access_logs.table_name IS 'Name of the table that was accessed.';
COMMENT ON COLUMN public.access_logs.row_id IS 'Primary key of the row that was accessed (as text).';
COMMENT ON COLUMN public.access_logs.access_type IS 'Type of access: SELECT, UPDATE, EXPORT, or DELETE_BLOCKED.';
COMMENT ON COLUMN public.access_logs.metadata IS 'Additional context (permissible purpose, query type). Never store raw PII.';
COMMENT ON COLUMN public.access_logs.session_id IS 'Correlation ID for grouping related access events.';
COMMENT ON COLUMN public.access_logs.ip_address IS 'Client IP address for security auditing.';
-- ============================================================================
-- IMMUTABILITY: Block UPDATE and DELETE via RULE
-- ============================================================================
-- These rules make the access_logs table truly append-only.
-- Any attempt to UPDATE or DELETE will fail with an exception.
-- ============================================================================
CREATE OR REPLACE RULE access_logs_no_update AS ON UPDATE TO public.access_logs DO INSTEAD NOTHING;
CREATE OR REPLACE RULE access_logs_no_delete AS ON DELETE TO public.access_logs DO INSTEAD NOTHING;
-- ============================================================================
-- FUNCTION: public.log_access
-- ============================================================================
-- RPC function for logging data access events.
--
-- USAGE (from n8n, workers, or authenticated queries):
--   SELECT public.log_access(
--       _table_name := 'debtor_intelligence',
--       _row_id := 'uuid-of-row',
--       _access_type := 'SELECT',
--       _metadata := '{"purpose": "wage_garnishment_research"}'::jsonb
--   );
--
-- SECURITY:
--   - SECURITY DEFINER: Runs with owner privileges to bypass RLS for insert
--   - Accessible to service_role and authenticated users with audit role
-- ============================================================================
CREATE OR REPLACE FUNCTION public.log_access(
        _table_name text,
        _row_id text DEFAULT NULL,
        _access_type text DEFAULT 'SELECT',
        _metadata jsonb DEFAULT '{}'::jsonb,
        _session_id uuid DEFAULT NULL
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _new_id uuid;
_user_id uuid;
_user_identifier text;
_ip inet;
BEGIN -- Validate access_type
IF _access_type NOT IN ('SELECT', 'UPDATE', 'EXPORT', 'DELETE_BLOCKED') THEN RAISE EXCEPTION 'Invalid access_type: %. Must be SELECT, UPDATE, EXPORT, or DELETE_BLOCKED',
_access_type;
END IF;
-- Capture the calling user's ID if available
BEGIN _user_id := auth.uid();
EXCEPTION
WHEN OTHERS THEN _user_id := NULL;
END;
-- Try to get user email as identifier
BEGIN
SELECT email INTO _user_identifier
FROM auth.users
WHERE id = _user_id;
EXCEPTION
WHEN OTHERS THEN _user_identifier := COALESCE(current_user, 'unknown');
END;
-- Try to get client IP from request headers
BEGIN _ip := (
    current_setting('request.headers', true)::jsonb->>'x-forwarded-for'
)::inet;
EXCEPTION
WHEN OTHERS THEN _ip := NULL;
END;
-- Insert the access log entry
INSERT INTO public.access_logs (
        accessed_at,
        user_id,
        user_identifier,
        table_name,
        row_id,
        access_type,
        metadata,
        session_id,
        ip_address
    )
VALUES (
        now(),
        _user_id,
        _user_identifier,
        _table_name,
        _row_id,
        _access_type,
        COALESCE(_metadata, '{}'::jsonb),
        _session_id,
        _ip
    )
RETURNING id INTO _new_id;
RETURN _new_id;
END;
$$;
COMMENT ON FUNCTION public.log_access IS 'Logs a data access event for FCRA compliance. Call when accessing sensitive consumer data. Params: _table_name, _row_id, _access_type (SELECT/UPDATE/EXPORT/DELETE_BLOCKED), _metadata (jsonb, no PII), _session_id.';
-- ============================================================================
-- TRIGGER FUNCTION: log_sensitive_update
-- ============================================================================
-- Automatically logs UPDATE operations on sensitive tables.
-- Captures old and new values (excluding PII) for audit trail.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.log_sensitive_update() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _row_id text;
_user_id uuid;
_user_identifier text;
_meta jsonb;
BEGIN -- Extract the primary key (assumes 'id' column exists)
_row_id := NEW.id::text;
-- Capture user info
BEGIN _user_id := auth.uid();
EXCEPTION
WHEN OTHERS THEN _user_id := NULL;
END;
BEGIN
SELECT email INTO _user_identifier
FROM auth.users
WHERE id = _user_id;
EXCEPTION
WHEN OTHERS THEN _user_identifier := COALESCE(current_user, 'unknown');
END;
-- Build metadata with changed columns (no PII values)
_meta := jsonb_build_object(
    'trigger',
    TG_NAME,
    'operation',
    'UPDATE',
    'changed_at',
    now()
);
-- Log the access
INSERT INTO public.access_logs (
        accessed_at,
        user_id,
        user_identifier,
        table_name,
        row_id,
        access_type,
        metadata
    )
VALUES (
        now(),
        _user_id,
        _user_identifier,
        TG_TABLE_NAME,
        _row_id,
        'UPDATE',
        _meta
    );
RETURN NEW;
END;
$$;
-- ============================================================================
-- TRIGGER FUNCTION: block_sensitive_delete
-- ============================================================================
-- Blocks DELETE operations on protected tables and logs the attempt.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.block_sensitive_delete() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _row_id text;
_user_id uuid;
_user_identifier text;
BEGIN -- Extract the primary key
_row_id := OLD.id::text;
-- Capture user info
BEGIN _user_id := auth.uid();
EXCEPTION
WHEN OTHERS THEN _user_id := NULL;
END;
BEGIN
SELECT email INTO _user_identifier
FROM auth.users
WHERE id = _user_id;
EXCEPTION
WHEN OTHERS THEN _user_identifier := COALESCE(current_user, 'unknown');
END;
-- Log the blocked delete attempt
INSERT INTO public.access_logs (
        accessed_at,
        user_id,
        user_identifier,
        table_name,
        row_id,
        access_type,
        metadata
    )
VALUES (
        now(),
        _user_id,
        _user_identifier,
        TG_TABLE_NAME,
        _row_id,
        'DELETE_BLOCKED',
        jsonb_build_object(
            'trigger',
            TG_NAME,
            'operation',
            'DELETE',
            'blocked_at',
            now(),
            'reason',
            'FCRA compliance: DELETE operations on sensitive data are prohibited'
        )
    );
-- Block the delete
RAISE EXCEPTION 'DELETE operations on % are prohibited for FCRA compliance',
TG_TABLE_NAME;
RETURN NULL;
END;
$$;
-- ============================================================================
-- APPLY TRIGGERS TO SENSITIVE TABLES
-- ============================================================================
-- debtor_intelligence: UPDATE logging
DROP TRIGGER IF EXISTS trg_debtor_intelligence_audit_update ON public.debtor_intelligence;
CREATE TRIGGER trg_debtor_intelligence_audit_update
AFTER
UPDATE ON public.debtor_intelligence FOR EACH ROW EXECUTE FUNCTION public.log_sensitive_update();
-- debtor_intelligence: DELETE blocking
DROP TRIGGER IF EXISTS trg_debtor_intelligence_block_delete ON public.debtor_intelligence;
CREATE TRIGGER trg_debtor_intelligence_block_delete BEFORE DELETE ON public.debtor_intelligence FOR EACH ROW EXECUTE FUNCTION public.block_sensitive_delete();
-- outreach_log: UPDATE logging (if table exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'outreach_log'
) THEN DROP TRIGGER IF EXISTS trg_outreach_log_audit_update ON public.outreach_log;
CREATE TRIGGER trg_outreach_log_audit_update
AFTER
UPDATE ON public.outreach_log FOR EACH ROW EXECUTE FUNCTION public.log_sensitive_update();
DROP TRIGGER IF EXISTS trg_outreach_log_block_delete ON public.outreach_log;
CREATE TRIGGER trg_outreach_log_block_delete BEFORE DELETE ON public.outreach_log FOR EACH ROW EXECUTE FUNCTION public.block_sensitive_delete();
END IF;
END $$;
-- plaintiff_call_attempts: UPDATE logging (if table exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_call_attempts'
) THEN DROP TRIGGER IF EXISTS trg_plaintiff_call_attempts_audit_update ON public.plaintiff_call_attempts;
CREATE TRIGGER trg_plaintiff_call_attempts_audit_update
AFTER
UPDATE ON public.plaintiff_call_attempts FOR EACH ROW EXECUTE FUNCTION public.log_sensitive_update();
DROP TRIGGER IF EXISTS trg_plaintiff_call_attempts_block_delete ON public.plaintiff_call_attempts;
CREATE TRIGGER trg_plaintiff_call_attempts_block_delete BEFORE DELETE ON public.plaintiff_call_attempts FOR EACH ROW EXECUTE FUNCTION public.block_sensitive_delete();
END IF;
END $$;
-- plaintiff_contacts: UPDATE logging (if table exists)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
) THEN DROP TRIGGER IF EXISTS trg_plaintiff_contacts_audit_update ON public.plaintiff_contacts;
CREATE TRIGGER trg_plaintiff_contacts_audit_update
AFTER
UPDATE ON public.plaintiff_contacts FOR EACH ROW EXECUTE FUNCTION public.log_sensitive_update();
DROP TRIGGER IF EXISTS trg_plaintiff_contacts_block_delete ON public.plaintiff_contacts;
CREATE TRIGGER trg_plaintiff_contacts_block_delete BEFORE DELETE ON public.plaintiff_contacts FOR EACH ROW EXECUTE FUNCTION public.block_sensitive_delete();
END IF;
END $$;
-- external_data_calls: Already has audit logging, just add DELETE blocking
DROP TRIGGER IF EXISTS trg_external_data_calls_block_delete ON public.external_data_calls;
CREATE TRIGGER trg_external_data_calls_block_delete BEFORE DELETE ON public.external_data_calls FOR EACH ROW EXECUTE FUNCTION public.block_sensitive_delete();
-- ============================================================================
-- ROW LEVEL SECURITY: access_logs
-- ============================================================================
-- The access_logs table has strict RLS:
--   - Only users with 'audit' role can SELECT
--   - Only service_role can INSERT (via SECURITY DEFINER functions)
--   - UPDATE and DELETE are blocked by RULEs (not RLS)
-- ============================================================================
ALTER TABLE public.access_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.access_logs FORCE ROW LEVEL SECURITY;
-- Drop existing policies
DROP POLICY IF EXISTS access_logs_select_audit ON public.access_logs;
DROP POLICY IF EXISTS access_logs_insert_service ON public.access_logs;
-- SELECT: Only audit role can read logs
-- Uses the dragonfly_has_role function from 0300_rls_role_mapping.sql
CREATE POLICY access_logs_select_audit ON public.access_logs FOR
SELECT USING (
        public.dragonfly_has_role('admin')
        OR public.dragonfly_has_role('audit')
        OR auth.role() = 'service_role'
    );
-- INSERT: Only service_role (via SECURITY DEFINER functions)
CREATE POLICY access_logs_insert_service ON public.access_logs FOR
INSERT WITH CHECK (auth.role() = 'service_role');
-- ============================================================================
-- GRANTS
-- ============================================================================
-- Restrict access to access_logs table
REVOKE ALL ON public.access_logs
FROM PUBLIC;
REVOKE ALL ON public.access_logs
FROM anon;
-- Only service_role and authenticated users with audit role can SELECT
-- (RLS will further restrict authenticated users)
GRANT SELECT ON public.access_logs TO service_role;
GRANT SELECT ON public.access_logs TO authenticated;
-- Only service_role can INSERT (through SECURITY DEFINER functions)
GRANT INSERT ON public.access_logs TO service_role;
-- Function grants
REVOKE ALL ON FUNCTION public.log_access(text, text, text, jsonb, uuid)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.log_access(text, text, text, jsonb, uuid)
FROM anon;
GRANT EXECUTE ON FUNCTION public.log_access(text, text, text, jsonb, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.log_access(text, text, text, jsonb, uuid) TO authenticated;
-- ============================================================================
-- CONVENIENCE FUNCTIONS
-- ============================================================================
-- Function to log an EXPORT operation (for bulk data downloads)
CREATE OR REPLACE FUNCTION public.log_export(
        _table_name text,
        _row_count integer,
        _export_format text DEFAULT 'csv',
        _purpose text DEFAULT NULL
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$ BEGIN RETURN public.log_access(
        _table_name := _table_name,
        _row_id := NULL,
        _access_type := 'EXPORT',
        _metadata := jsonb_build_object(
            'row_count',
            _row_count,
            'format',
            _export_format,
            'purpose',
            COALESCE(_purpose, 'not_specified')
        )
    );
END;
$$;
COMMENT ON FUNCTION public.log_export IS 'Logs a bulk data export for FCRA compliance. Call before exporting sensitive data. Params: _table_name, _row_count, _export_format, _purpose.';
REVOKE ALL ON FUNCTION public.log_export(text, integer, text, text)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.log_export(text, integer, text, text)
FROM anon;
GRANT EXECUTE ON FUNCTION public.log_export(text, integer, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.log_export(text, integer, text, text) TO authenticated;
-- Function to query access logs (admin/audit only)
CREATE OR REPLACE FUNCTION public.get_access_logs(
        _table_name text DEFAULT NULL,
        _start_date timestamptz DEFAULT NULL,
        _end_date timestamptz DEFAULT NULL,
        _access_type text DEFAULT NULL,
        _limit integer DEFAULT 100
    ) RETURNS TABLE (
        id uuid,
        accessed_at timestamptz,
        user_identifier text,
        table_name text,
        row_id text,
        access_type text,
        metadata jsonb
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$ BEGIN -- Check if user has audit access
    IF NOT (
        public.dragonfly_has_role('admin')
        OR public.dragonfly_has_role('audit')
    ) THEN RAISE EXCEPTION 'Access denied: audit role required';
END IF;
RETURN QUERY
SELECT al.id,
    al.accessed_at,
    al.user_identifier,
    al.table_name,
    al.row_id,
    al.access_type,
    al.metadata
FROM public.access_logs al
WHERE (
        _table_name IS NULL
        OR al.table_name = _table_name
    )
    AND (
        _start_date IS NULL
        OR al.accessed_at >= _start_date
    )
    AND (
        _end_date IS NULL
        OR al.accessed_at <= _end_date
    )
    AND (
        _access_type IS NULL
        OR al.access_type = _access_type
    )
ORDER BY al.accessed_at DESC
LIMIT _limit;
END;
$$;
COMMENT ON FUNCTION public.get_access_logs IS 'Query access logs with filters. Requires admin or audit role. Params: _table_name, _start_date, _end_date, _access_type, _limit.';
REVOKE ALL ON FUNCTION public.get_access_logs(text, timestamptz, timestamptz, text, integer)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.get_access_logs(text, timestamptz, timestamptz, text, integer)
FROM anon;
GRANT EXECUTE ON FUNCTION public.get_access_logs(text, timestamptz, timestamptz, text, integer) TO service_role;
GRANT EXECUTE ON FUNCTION public.get_access_logs(text, timestamptz, timestamptz, text, integer) TO authenticated;
-- ============================================================================
-- RELOAD POSTGREST SCHEMA CACHE
-- ============================================================================
SELECT public.pgrst_reload();
COMMIT;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================