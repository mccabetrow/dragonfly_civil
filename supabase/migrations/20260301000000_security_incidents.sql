-- ============================================================================
-- Migration: Security Incidents Tracking
-- Purpose: Persistent logging of security events (rate limits, abuse, threats)
-- Date: 2026-03-01
-- ============================================================================
--
-- This schema provides:
--   1. Immutable incident records for security forensics
--   2. Structured event types for automated alerting
--   3. IP tracking for abuse pattern detection
--   4. Integration with audit trail for compliance
-- ============================================================================
-- ============================================================================
-- PART 1: Security Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS security;
COMMENT ON SCHEMA security IS 'Security incident tracking and threat detection';
-- ============================================================================
-- PART 2: Severity Enum
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
    WHERE t.typname = 'incident_severity'
        AND n.nspname = 'security'
) THEN CREATE TYPE security.incident_severity AS ENUM (
    'info',
    -- Informational (e.g., rate limit warning)
    'warning',
    -- Suspicious activity requiring review
    'critical' -- Active attack or breach attempt
);
END IF;
END $$;
-- ============================================================================
-- PART 3: Incidents Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS security.incidents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Timestamp (immutable)
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Severity classification
    severity security.incident_severity NOT NULL DEFAULT 'info',
    -- Event classification
    event_type TEXT NOT NULL,
    -- Source identification
    source_ip INET,
    user_id UUID REFERENCES auth.users(id) ON DELETE
    SET NULL,
        -- Request context
        request_path TEXT,
        request_method TEXT,
        user_agent TEXT,
        -- Structured details
        metadata JSONB DEFAULT '{}',
        -- Tracking
        acknowledged_at TIMESTAMPTZ,
        acknowledged_by UUID REFERENCES auth.users(id),
        resolution_notes TEXT,
        -- Prevent tampering
        CONSTRAINT chk_event_type_not_empty CHECK (char_length(event_type) > 0)
);
-- Table comments
COMMENT ON TABLE security.incidents IS '{"description": "Security incident log for threat detection and forensics", "sensitivity": "HIGH", "retention": "7_years"}';
COMMENT ON COLUMN security.incidents.event_type IS 'Classification: rate_limit_exceeded, enumeration_attempt, auth_failure, suspicious_payload, ip_blocklist, etc.';
COMMENT ON COLUMN security.incidents.source_ip IS 'Client IP address (may be behind proxy)';
COMMENT ON COLUMN security.incidents.metadata IS 'Event-specific details: request count, threshold, pattern data';
-- ============================================================================
-- PART 4: Indexes
-- ============================================================================
-- Time-based queries (most common)
CREATE INDEX IF NOT EXISTS idx_security_incidents_ts ON security.incidents(ts DESC);
-- Severity filtering for alerting
CREATE INDEX IF NOT EXISTS idx_security_incidents_severity ON security.incidents(severity, ts DESC);
-- Event type analysis
CREATE INDEX IF NOT EXISTS idx_security_incidents_event_type ON security.incidents(event_type, ts DESC);
-- IP-based pattern detection
CREATE INDEX IF NOT EXISTS idx_security_incidents_source_ip ON security.incidents(source_ip, ts DESC)
WHERE source_ip IS NOT NULL;
-- User-based incident tracking
CREATE INDEX IF NOT EXISTS idx_security_incidents_user_id ON security.incidents(user_id, ts DESC)
WHERE user_id IS NOT NULL;
-- Unacknowledged incidents (for dashboard)
CREATE INDEX IF NOT EXISTS idx_security_incidents_unacked ON security.incidents(severity, ts DESC)
WHERE acknowledged_at IS NULL;
-- ============================================================================
-- PART 5: Common Event Types (Reference)
-- ============================================================================
COMMENT ON TABLE security.incidents IS $$ { "description": "Security incident log",
"event_types": { "rate_limit_exceeded": "IP exceeded request rate threshold",
"rate_limit_warning": "IP approaching rate limit",
"enumeration_attempt": "Suspicious 404 pattern (ID scanning)",
"auth_failure_burst": "Multiple auth failures from same IP",
"suspicious_payload": "Request body matched threat signature",
"ip_blocklist_hit": "Request from known malicious IP",
"jwt_tampering": "Invalid or manipulated JWT detected",
"sql_injection_attempt": "SQL injection pattern detected",
"path_traversal_attempt": "Directory traversal detected",
"excessive_body_size": "Request body exceeded limits" } } $$;
-- ============================================================================
-- PART 6: Helper Functions
-- ============================================================================
-- Log a security incident (used by middleware)
CREATE OR REPLACE FUNCTION security.log_incident(
        p_severity security.incident_severity,
        p_event_type TEXT,
        p_source_ip INET DEFAULT NULL,
        p_user_id UUID DEFAULT NULL,
        p_request_path TEXT DEFAULT NULL,
        p_request_method TEXT DEFAULT NULL,
        p_user_agent TEXT DEFAULT NULL,
        p_metadata JSONB DEFAULT '{}'
    ) RETURNS UUID LANGUAGE sql SECURITY DEFINER
SET search_path = security,
    public AS $$
INSERT INTO security.incidents (
        severity,
        event_type,
        source_ip,
        user_id,
        request_path,
        request_method,
        user_agent,
        metadata
    )
VALUES (
        p_severity,
        p_event_type,
        p_source_ip,
        p_user_id,
        p_request_path,
        p_request_method,
        p_user_agent,
        p_metadata
    )
RETURNING id;
$$;
COMMENT ON FUNCTION security.log_incident IS 'Log a security incident. Returns the incident UUID.';
-- Get recent incidents by IP (for escalation decisions)
CREATE OR REPLACE FUNCTION security.get_recent_incidents_by_ip(
        p_source_ip INET,
        p_event_type TEXT DEFAULT NULL,
        p_window_minutes INTEGER DEFAULT 60
    ) RETURNS TABLE (
        incident_count BIGINT,
        first_incident TIMESTAMPTZ,
        last_incident TIMESTAMPTZ,
        severities TEXT []
    ) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = security,
    public AS $$
SELECT COUNT(*) AS incident_count,
    MIN(ts) AS first_incident,
    MAX(ts) AS last_incident,
    ARRAY_AGG(DISTINCT severity::TEXT) AS severities
FROM security.incidents
WHERE source_ip = p_source_ip
    AND ts > NOW() - (p_window_minutes || ' minutes')::INTERVAL
    AND (
        p_event_type IS NULL
        OR event_type = p_event_type
    );
$$;
-- Get incident summary for dashboard
CREATE OR REPLACE FUNCTION security.get_incident_summary(p_hours INTEGER DEFAULT 24) RETURNS TABLE (
        severity security.incident_severity,
        event_type TEXT,
        incident_count BIGINT,
        unique_ips BIGINT
    ) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = security,
    public AS $$
SELECT severity,
    event_type,
    COUNT(*) AS incident_count,
    COUNT(DISTINCT source_ip) AS unique_ips
FROM security.incidents
WHERE ts > NOW() - (p_hours || ' hours')::INTERVAL
GROUP BY severity,
    event_type
ORDER BY severity DESC,
    incident_count DESC;
$$;
-- ============================================================================
-- PART 7: Row-Level Security
-- ============================================================================
ALTER TABLE security.incidents ENABLE ROW LEVEL SECURITY;
-- Only service_role can insert (middleware uses service key)
CREATE POLICY "incidents_insert_service_only" ON security.incidents FOR
INSERT TO service_role WITH CHECK (true);
-- Only service_role can read (for dashboard/reporting)
CREATE POLICY "incidents_select_service_only" ON security.incidents FOR
SELECT TO service_role USING (true);
-- Only service_role can update (for acknowledgment)
CREATE POLICY "incidents_update_service_only" ON security.incidents FOR
UPDATE TO service_role USING (true) WITH CHECK (true);
-- No deletes allowed (immutable audit log)
-- (No DELETE policy = no one can delete)
-- ============================================================================
-- PART 8: Grants
-- ============================================================================
GRANT USAGE ON SCHEMA security TO service_role;
GRANT INSERT,
    SELECT,
    UPDATE ON security.incidents TO service_role;
GRANT EXECUTE ON FUNCTION security.log_incident TO service_role;
GRANT EXECUTE ON FUNCTION security.get_recent_incidents_by_ip TO service_role;
GRANT EXECUTE ON FUNCTION security.get_incident_summary TO service_role;
-- Authenticated users cannot directly access (must go through service layer)
-- No grants to authenticated role
-- ============================================================================
-- PART 9: Alerting View (for monitoring integrations)
-- ============================================================================
CREATE OR REPLACE VIEW security.v_critical_incidents_24h AS
SELECT id,
    ts,
    event_type,
    source_ip,
    user_id,
    request_path,
    metadata
FROM security.incidents
WHERE severity = 'critical'
    AND ts > NOW() - INTERVAL '24 hours'
    AND acknowledged_at IS NULL
ORDER BY ts DESC;
COMMENT ON VIEW security.v_critical_incidents_24h IS 'Unacknowledged critical incidents in last 24 hours';
GRANT SELECT ON security.v_critical_incidents_24h TO service_role;
-- ============================================================================
-- VERIFICATION QUERIES
-- ============================================================================
-- Test insert:
--   SELECT security.log_incident(
--       'warning'::security.incident_severity,
--       'rate_limit_exceeded',
--       '192.168.1.1'::inet,
--       NULL,
--       '/api/v1/search',
--       'POST',
--       'Mozilla/5.0',
--       '{"requests": 150, "threshold": 100}'::jsonb
--   );
--
-- Check recent incidents:
--   SELECT * FROM security.get_incident_summary(24);