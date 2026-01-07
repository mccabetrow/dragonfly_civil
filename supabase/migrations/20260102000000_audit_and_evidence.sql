-- ============================================================================
-- Migration: Audit & Evidence Vault
-- Purpose: Immutable audit logging and tamper-proof file tracking
-- Date: 2026-01-02
-- ============================================================================
-- ============================================================================
-- PART 1: Audit Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS audit;
COMMENT ON SCHEMA audit IS 'Immutable audit logging - INSERT only, no UPDATE/DELETE';
-- -----------------------------------------------------------------------------
-- Actor Type Enum
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'actor_type'
) THEN CREATE TYPE audit.actor_type AS ENUM ('user', 'system', 'service', 'anonymous');
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- Event Log Table (Immutable)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit.event_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_id UUID,
    -- NULL for anonymous/system
    actor_type audit.actor_type NOT NULL DEFAULT 'system',
    action TEXT NOT NULL,
    -- e.g., 'judgment.created', 'plaintiff.status_changed'
    entity_type TEXT NOT NULL,
    -- e.g., 'judgment', 'plaintiff', 'file'
    entity_id UUID,
    -- FK to the affected entity
    changes JSONB,
    -- Before/after state or action details
    org_id UUID REFERENCES tenant.orgs(id),
    ip_address INET,
    user_agent TEXT,
    request_id UUID -- Correlation ID for tracing
);
-- Table comment
COMMENT ON TABLE audit.event_log IS '{"description": "Immutable audit log - INSERT only", "sensitivity": "HIGH", "retention": "7_years"}';
-- Column comments
COMMENT ON COLUMN audit.event_log.id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
COMMENT ON COLUMN audit.event_log.ts IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Event timestamp (immutable)"}';
COMMENT ON COLUMN audit.event_log.actor_id IS '{"tag": "INTERNAL", "sensitivity": "MEDIUM", "description": "User ID who performed action"}';
COMMENT ON COLUMN audit.event_log.actor_type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Type of actor (user/system/service)"}';
COMMENT ON COLUMN audit.event_log.action IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Action performed (e.g., judgment.created)"}';
COMMENT ON COLUMN audit.event_log.entity_type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Type of entity affected"}';
COMMENT ON COLUMN audit.event_log.entity_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "ID of affected entity"}';
COMMENT ON COLUMN audit.event_log.changes IS '{"tag": "CONFIDENTIAL", "sensitivity": "HIGH", "description": "Before/after state (may contain PII)"}';
COMMENT ON COLUMN audit.event_log.org_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Organization context"}';
COMMENT ON COLUMN audit.event_log.ip_address IS '{"tag": "PII", "sensitivity": "MEDIUM", "description": "Client IP address"}';
COMMENT ON COLUMN audit.event_log.user_agent IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Client user agent string"}';
COMMENT ON COLUMN audit.event_log.request_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Request correlation ID"}';
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_event_log_ts ON audit.event_log(ts DESC);
CREATE INDEX IF NOT EXISTS idx_event_log_actor_id ON audit.event_log(actor_id);
CREATE INDEX IF NOT EXISTS idx_event_log_entity ON audit.event_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_event_log_org_id ON audit.event_log(org_id);
CREATE INDEX IF NOT EXISTS idx_event_log_action ON audit.event_log(action);
-- -----------------------------------------------------------------------------
-- IMMUTABILITY ENFORCEMENT
-- Revoke UPDATE and DELETE from ALL roles
-- -----------------------------------------------------------------------------
-- Revoke modification permissions from all standard roles
REVOKE
UPDATE,
    DELETE ON audit.event_log
FROM PUBLIC;
REVOKE
UPDATE,
    DELETE ON audit.event_log
FROM anon;
REVOKE
UPDATE,
    DELETE ON audit.event_log
FROM authenticated;
REVOKE
UPDATE,
    DELETE ON audit.event_log
FROM service_role;
-- Create a trigger to block any UPDATE/DELETE attempts (defense in depth)
CREATE OR REPLACE FUNCTION audit.prevent_modification() RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = audit AS $$ BEGIN RAISE EXCEPTION 'IMMUTABLE: audit.event_log does not allow % operations',
    TG_OP USING HINT = 'Audit logs are append-only for legal compliance';
RETURN NULL;
END;
$$;
DROP TRIGGER IF EXISTS trg_prevent_update ON audit.event_log;
CREATE TRIGGER trg_prevent_update BEFORE
UPDATE ON audit.event_log FOR EACH ROW EXECUTE FUNCTION audit.prevent_modification();
DROP TRIGGER IF EXISTS trg_prevent_delete ON audit.event_log;
CREATE TRIGGER trg_prevent_delete BEFORE DELETE ON audit.event_log FOR EACH ROW EXECUTE FUNCTION audit.prevent_modification();
-- -----------------------------------------------------------------------------
-- Audit Logging RPC Function
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION audit.log_event(
        p_action TEXT,
        p_entity_type TEXT,
        p_entity_id UUID DEFAULT NULL,
        p_changes JSONB DEFAULT NULL,
        p_actor_id UUID DEFAULT NULL,
        p_actor_type audit.actor_type DEFAULT 'system',
        p_org_id UUID DEFAULT NULL,
        p_ip_address INET DEFAULT NULL,
        p_user_agent TEXT DEFAULT NULL,
        p_request_id UUID DEFAULT NULL
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = audit,
    public AS $$
DECLARE v_event_id UUID;
v_actor_id UUID;
BEGIN -- Use provided actor_id or try to get from auth context
v_actor_id := COALESCE(p_actor_id, auth.uid());
INSERT INTO audit.event_log (
        actor_id,
        actor_type,
        action,
        entity_type,
        entity_id,
        changes,
        org_id,
        ip_address,
        user_agent,
        request_id
    )
VALUES (
        v_actor_id,
        p_actor_type,
        p_action,
        p_entity_type,
        p_entity_id,
        p_changes,
        p_org_id,
        p_ip_address,
        p_user_agent,
        p_request_id
    )
RETURNING id INTO v_event_id;
RETURN v_event_id;
END;
$$;
COMMENT ON FUNCTION audit.log_event IS 'Insert an immutable audit log entry';
-- Grant execute to roles that need to log events
GRANT EXECUTE ON FUNCTION audit.log_event TO authenticated;
GRANT EXECUTE ON FUNCTION audit.log_event TO service_role;
-- ============================================================================
-- PART 2: Evidence Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS evidence;
COMMENT ON SCHEMA evidence IS 'Tamper-proof file tracking and evidence vault';
-- -----------------------------------------------------------------------------
-- Evidence Files Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence.files (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    bucket_path TEXT NOT NULL,
    -- e.g., 'evidence/org-123/file-456.pdf'
    file_name TEXT NOT NULL,
    -- Original filename
    sha256_hash CHAR(64) NOT NULL,
    -- 64 hex chars = 256 bits
    size_bytes BIGINT NOT NULL CHECK (size_bytes >= 0),
    mime_type TEXT NOT NULL,
    uploaded_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    uploaded_by UUID REFERENCES auth.users(id),
    legal_hold BOOLEAN NOT NULL DEFAULT false,
    retention_until DATE,
    -- NULL = retain indefinitely
    entity_type TEXT,
    -- What this file relates to (judgment, plaintiff, etc.)
    entity_id UUID,
    -- FK to related entity
    metadata JSONB DEFAULT '{}',
    -- Additional structured metadata
    verified_at TIMESTAMPTZ,
    -- Last integrity verification
    verified_hash_match BOOLEAN,
    -- Result of last verification
    -- Ensure SHA-256 hash is valid hex
    CONSTRAINT chk_sha256_format CHECK (sha256_hash ~ '^[a-f0-9]{64}$')
);
-- Table comment
COMMENT ON TABLE evidence.files IS '{"description": "Evidence vault - tamper-proof file registry", "sensitivity": "HIGH", "retention": "permanent"}';
-- Column comments
COMMENT ON COLUMN evidence.files.id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
COMMENT ON COLUMN evidence.files.org_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Owning organization"}';
COMMENT ON COLUMN evidence.files.bucket_path IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Supabase Storage path"}';
COMMENT ON COLUMN evidence.files.file_name IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Original filename"}';
COMMENT ON COLUMN evidence.files.sha256_hash IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "SHA-256 hash for integrity verification"}';
COMMENT ON COLUMN evidence.files.size_bytes IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "File size in bytes"}';
COMMENT ON COLUMN evidence.files.mime_type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "MIME type of file"}';
COMMENT ON COLUMN evidence.files.uploaded_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Upload timestamp"}';
COMMENT ON COLUMN evidence.files.uploaded_by IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "User who uploaded"}';
COMMENT ON COLUMN evidence.files.legal_hold IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "If true, file cannot be deleted"}';
COMMENT ON COLUMN evidence.files.retention_until IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Retention expiry date"}';
COMMENT ON COLUMN evidence.files.entity_type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Related entity type"}';
COMMENT ON COLUMN evidence.files.entity_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Related entity ID"}';
COMMENT ON COLUMN evidence.files.metadata IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Additional file metadata"}';
COMMENT ON COLUMN evidence.files.verified_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Last integrity check timestamp"}';
COMMENT ON COLUMN evidence.files.verified_hash_match IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Last integrity check result"}';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_evidence_files_org_id ON evidence.files(org_id);
CREATE INDEX IF NOT EXISTS idx_evidence_files_entity ON evidence.files(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_evidence_files_sha256 ON evidence.files(sha256_hash);
CREATE INDEX IF NOT EXISTS idx_evidence_files_legal_hold ON evidence.files(legal_hold)
WHERE legal_hold = true;
CREATE INDEX IF NOT EXISTS idx_evidence_files_uploaded_at ON evidence.files(uploaded_at DESC);
-- Unique constraint: same hash in same org = duplicate
CREATE UNIQUE INDEX IF NOT EXISTS idx_evidence_files_org_hash ON evidence.files(org_id, sha256_hash);
-- -----------------------------------------------------------------------------
-- Evidence File Audit Trail
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence.file_events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    file_id UUID NOT NULL REFERENCES evidence.files(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    -- 'uploaded', 'verified', 'accessed', 'legal_hold_set'
    actor_id UUID,
    details JSONB
);
COMMENT ON TABLE evidence.file_events IS '{"description": "Audit trail for evidence file operations", "sensitivity": "HIGH"}';
CREATE INDEX IF NOT EXISTS idx_file_events_file_id ON evidence.file_events(file_id);
CREATE INDEX IF NOT EXISTS idx_file_events_ts ON evidence.file_events(ts DESC);
-- -----------------------------------------------------------------------------
-- RLS for Evidence Tables
-- -----------------------------------------------------------------------------
ALTER TABLE evidence.files ENABLE ROW LEVEL SECURITY;
ALTER TABLE evidence.file_events ENABLE ROW LEVEL SECURITY;
-- Org isolation for evidence files
CREATE POLICY "evidence_files_org_isolation" ON evidence.files FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "evidence_files_service_role_bypass" ON evidence.files FOR ALL TO service_role USING (true) WITH CHECK (true);
-- File events inherit from files
CREATE POLICY "evidence_file_events_org_isolation" ON evidence.file_events FOR ALL USING (
    EXISTS (
        SELECT 1
        FROM evidence.files f
        WHERE f.id = evidence.file_events.file_id
            AND f.org_id IN (
                SELECT tenant.user_org_ids()
            )
    )
);
CREATE POLICY "evidence_file_events_service_role_bypass" ON evidence.file_events FOR ALL TO service_role USING (true) WITH CHECK (true);
-- -----------------------------------------------------------------------------
-- Legal Hold Enforcement
-- Prevent deletion of files under legal hold
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION evidence.enforce_legal_hold() RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = evidence AS $$ BEGIN IF OLD.legal_hold = true THEN RAISE EXCEPTION 'LEGAL_HOLD: Cannot delete file % - under legal hold',
    OLD.id USING HINT = 'Remove legal hold before deletion (requires elevated privileges)';
END IF;
RETURN OLD;
END;
$$;
DROP TRIGGER IF EXISTS trg_enforce_legal_hold ON evidence.files;
CREATE TRIGGER trg_enforce_legal_hold BEFORE DELETE ON evidence.files FOR EACH ROW EXECUTE FUNCTION evidence.enforce_legal_hold();
-- -----------------------------------------------------------------------------
-- Helper Function: Register Evidence File
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION evidence.register_file(
        p_org_id UUID,
        p_bucket_path TEXT,
        p_file_name TEXT,
        p_sha256_hash TEXT,
        p_size_bytes BIGINT,
        p_mime_type TEXT,
        p_entity_type TEXT DEFAULT NULL,
        p_entity_id UUID DEFAULT NULL,
        p_metadata JSONB DEFAULT '{}'
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = evidence,
    audit,
    public AS $$
DECLARE v_file_id UUID;
v_user_id UUID;
BEGIN v_user_id := auth.uid();
-- Insert file record
INSERT INTO evidence.files (
        org_id,
        bucket_path,
        file_name,
        sha256_hash,
        size_bytes,
        mime_type,
        uploaded_by,
        entity_type,
        entity_id,
        metadata
    )
VALUES (
        p_org_id,
        p_bucket_path,
        p_file_name,
        lower(p_sha256_hash),
        -- Normalize to lowercase
        p_size_bytes,
        p_mime_type,
        v_user_id,
        p_entity_type,
        p_entity_id,
        p_metadata
    )
RETURNING id INTO v_file_id;
-- Log upload event
INSERT INTO evidence.file_events (file_id, event_type, actor_id, details)
VALUES (
        v_file_id,
        'uploaded',
        v_user_id,
        jsonb_build_object(
            'file_name',
            p_file_name,
            'size_bytes',
            p_size_bytes,
            'sha256_hash',
            lower(p_sha256_hash)
        )
    );
-- Log to audit
PERFORM audit.log_event(
    p_action := 'evidence.file_uploaded',
    p_entity_type := 'evidence_file',
    p_entity_id := v_file_id,
    p_org_id := p_org_id,
    p_changes := jsonb_build_object(
        'file_name',
        p_file_name,
        'bucket_path',
        p_bucket_path,
        'sha256_hash',
        lower(p_sha256_hash)
    )
);
RETURN v_file_id;
END;
$$;
COMMENT ON FUNCTION evidence.register_file IS 'Register a new evidence file with hash verification';
GRANT EXECUTE ON FUNCTION evidence.register_file TO authenticated;
GRANT EXECUTE ON FUNCTION evidence.register_file TO service_role;
-- -----------------------------------------------------------------------------
-- Grants
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA audit TO authenticated,
    service_role;
GRANT USAGE ON SCHEMA evidence TO authenticated,
    service_role;
GRANT SELECT ON audit.event_log TO authenticated;
GRANT INSERT ON audit.event_log TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON evidence.files TO authenticated;
GRANT ALL ON evidence.files TO service_role;
GRANT SELECT,
    INSERT ON evidence.file_events TO authenticated;
GRANT ALL ON evidence.file_events TO service_role;
-- ============================================================================
-- Migration Complete
-- ============================================================================
