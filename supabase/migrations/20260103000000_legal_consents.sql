-- ============================================================================
-- Migration: Legal Consents & Authorization Tracking
-- Purpose: Track LOA, Fee Agreements, and consent documents
-- Date: 2026-01-03
-- ============================================================================
-- ============================================================================
-- PART 1: Legal Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS legal;
COMMENT ON SCHEMA legal IS 'Legal consent and authorization tracking';
-- -----------------------------------------------------------------------------
-- Consent Type Enum
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'consent_type'
) THEN CREATE TYPE legal.consent_type AS ENUM (
    'fee_agreement',
    -- Fee/compensation agreement
    'loa',
    -- Letter of Authorization
    'terms',
    -- Terms of service
    'privacy',
    -- Privacy policy acknowledgment
    'communication',
    -- Communication consent (calls, emails)
    'representation' -- Legal representation agreement
);
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- Consent Status Enum
-- -----------------------------------------------------------------------------
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'consent_status'
) THEN CREATE TYPE legal.consent_status AS ENUM (
    'active',
    -- Currently valid
    'superseded',
    -- Replaced by newer version
    'revoked',
    -- Explicitly revoked by plaintiff
    'expired' -- Time-limited consent expired
);
END IF;
END $$;
-- -----------------------------------------------------------------------------
-- Consents Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS legal.consents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    plaintiff_id UUID NOT NULL REFERENCES public.plaintiffs(id) ON DELETE RESTRICT,
    consent_type legal.consent_type NOT NULL,
    status legal.consent_status NOT NULL DEFAULT 'active',
    version TEXT NOT NULL,
    -- Document version (e.g., 'v2.1', '2026-01')
    -- Acceptance details
    accepted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    accepted_by_ip INET,
    -- IP address at time of acceptance
    accepted_by_user_agent TEXT,
    -- Document reference
    document_hash UUID REFERENCES evidence.files(id),
    -- FK to evidence vault
    -- Validity period (optional)
    valid_from TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until TIMESTAMPTZ,
    -- NULL = no expiration
    -- Revocation tracking
    revoked_at TIMESTAMPTZ,
    revoked_reason TEXT,
    -- Metadata
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSONB DEFAULT '{}',
    -- Prevent duplicate active consents of same type for same plaintiff
    CONSTRAINT uq_active_consent UNIQUE (plaintiff_id, consent_type, status) DEFERRABLE INITIALLY DEFERRED
);
-- Table comment
COMMENT ON TABLE legal.consents IS '{"description": "Legal consent and authorization tracking", "sensitivity": "HIGH", "retention": "permanent"}';
-- Column comments (Classification)
COMMENT ON COLUMN legal.consents.id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
COMMENT ON COLUMN legal.consents.org_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Owning organization"}';
COMMENT ON COLUMN legal.consents.plaintiff_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "FK to plaintiff"}';
COMMENT ON COLUMN legal.consents.consent_type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Type of consent"}';
COMMENT ON COLUMN legal.consents.status IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Consent status"}';
COMMENT ON COLUMN legal.consents.version IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Document version"}';
COMMENT ON COLUMN legal.consents.accepted_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Acceptance timestamp"}';
COMMENT ON COLUMN legal.consents.accepted_by_ip IS '{"tag": "PII", "sensitivity": "MEDIUM", "description": "IP address at acceptance"}';
COMMENT ON COLUMN legal.consents.accepted_by_user_agent IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "User agent at acceptance"}';
COMMENT ON COLUMN legal.consents.document_hash IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "FK to evidence file"}';
COMMENT ON COLUMN legal.consents.valid_from IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Validity start date"}';
COMMENT ON COLUMN legal.consents.valid_until IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Validity end date"}';
COMMENT ON COLUMN legal.consents.revoked_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Revocation timestamp"}';
COMMENT ON COLUMN legal.consents.revoked_reason IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Reason for revocation"}';
COMMENT ON COLUMN legal.consents.created_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record creation timestamp"}';
COMMENT ON COLUMN legal.consents.updated_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record update timestamp"}';
COMMENT ON COLUMN legal.consents.metadata IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Additional consent metadata"}';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_consents_org_id ON legal.consents(org_id);
CREATE INDEX IF NOT EXISTS idx_consents_plaintiff_id ON legal.consents(plaintiff_id);
CREATE INDEX IF NOT EXISTS idx_consents_type_status ON legal.consents(consent_type, status);
CREATE INDEX IF NOT EXISTS idx_consents_accepted_at ON legal.consents(accepted_at DESC);
-- Composite index for authorization lookups
CREATE INDEX IF NOT EXISTS idx_consents_authorization ON legal.consents(plaintiff_id, consent_type, status)
WHERE status = 'active';
-- -----------------------------------------------------------------------------
-- Consent History Table (Immutable audit trail)
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS legal.consent_history (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    consent_id UUID NOT NULL REFERENCES legal.consents(id),
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    event_type TEXT NOT NULL,
    -- 'created', 'superseded', 'revoked', 'expired'
    old_status legal.consent_status,
    new_status legal.consent_status,
    actor_id UUID,
    details JSONB
);
COMMENT ON TABLE legal.consent_history IS '{"description": "Consent change history", "sensitivity": "HIGH"}';
CREATE INDEX IF NOT EXISTS idx_consent_history_consent_id ON legal.consent_history(consent_id);
CREATE INDEX IF NOT EXISTS idx_consent_history_ts ON legal.consent_history(ts DESC);
-- -----------------------------------------------------------------------------
-- Auto-update trigger for consents
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION legal.update_consent_timestamp() RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = legal AS $$ BEGIN NEW.updated_at := now();
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_consents_updated_at ON legal.consents;
CREATE TRIGGER trg_consents_updated_at BEFORE
UPDATE ON legal.consents FOR EACH ROW EXECUTE FUNCTION legal.update_consent_timestamp();
-- -----------------------------------------------------------------------------
-- Consent history trigger
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION legal.log_consent_change() RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = legal,
    audit AS $$ BEGIN IF TG_OP = 'INSERT' THEN
INSERT INTO legal.consent_history (
        consent_id,
        event_type,
        new_status,
        details
    )
VALUES (
        NEW.id,
        'created',
        NEW.status,
        jsonb_build_object(
            'consent_type',
            NEW.consent_type::text,
            'version',
            NEW.version,
            'plaintiff_id',
            NEW.plaintiff_id
        )
    );
-- Also log to audit schema
PERFORM audit.log_event(
    p_action := 'consent.created',
    p_entity_type := 'consent',
    p_entity_id := NEW.id,
    p_org_id := NEW.org_id,
    p_changes := jsonb_build_object(
        'consent_type',
        NEW.consent_type::text,
        'plaintiff_id',
        NEW.plaintiff_id
    )
);
ELSIF TG_OP = 'UPDATE'
AND OLD.status IS DISTINCT
FROM NEW.status THEN
INSERT INTO legal.consent_history (
        consent_id,
        event_type,
        old_status,
        new_status,
        details
    )
VALUES (
        NEW.id,
        CASE
            WHEN NEW.status = 'revoked' THEN 'revoked'
            WHEN NEW.status = 'superseded' THEN 'superseded'
            WHEN NEW.status = 'expired' THEN 'expired'
            ELSE 'status_changed'
        END,
        OLD.status,
        NEW.status,
        jsonb_build_object(
            'revoked_reason',
            NEW.revoked_reason
        )
    );
PERFORM audit.log_event(
    p_action := 'consent.status_changed',
    p_entity_type := 'consent',
    p_entity_id := NEW.id,
    p_org_id := NEW.org_id,
    p_changes := jsonb_build_object(
        'old_status',
        OLD.status::text,
        'new_status',
        NEW.status::text,
        'revoked_reason',
        NEW.revoked_reason
    )
);
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_consent_history ON legal.consents;
CREATE TRIGGER trg_consent_history
AFTER
INSERT
    OR
UPDATE ON legal.consents FOR EACH ROW EXECUTE FUNCTION legal.log_consent_change();
-- ============================================================================
-- PART 2: RLS for Legal Schema
-- ============================================================================
ALTER TABLE legal.consents ENABLE ROW LEVEL SECURITY;
ALTER TABLE legal.consent_history ENABLE ROW LEVEL SECURITY;
-- Org isolation for consents
CREATE POLICY "consents_org_isolation" ON legal.consents FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
CREATE POLICY "consents_service_role_bypass" ON legal.consents FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Consent history inherits from consents
CREATE POLICY "consent_history_org_isolation" ON legal.consent_history FOR ALL USING (
    EXISTS (
        SELECT 1
        FROM legal.consents c
        WHERE c.id = legal.consent_history.consent_id
            AND c.org_id IN (
                SELECT tenant.user_org_ids()
            )
    )
);
CREATE POLICY "consent_history_service_role_bypass" ON legal.consent_history FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ============================================================================
-- PART 3: Authorization View
-- ============================================================================
-- Create enforcement schema if not exists
CREATE SCHEMA IF NOT EXISTS enforcement;
-- View: Only plaintiffs with valid, active fee_agreement AND loa
CREATE OR REPLACE VIEW enforcement.v_authorized_plaintiffs AS
SELECT DISTINCT p.id AS plaintiff_id,
    p.org_id,
    p.name AS plaintiff_name,
    p.status AS plaintiff_status,
    p.tier AS plaintiff_tier,
    -- Fee agreement details
    fa.id AS fee_agreement_id,
    fa.version AS fee_agreement_version,
    fa.accepted_at AS fee_agreement_accepted_at,
    -- LOA details
    loa.id AS loa_id,
    loa.version AS loa_version,
    loa.accepted_at AS loa_accepted_at,
    -- Authorization status
    true AS is_fully_authorized,
    LEAST(fa.valid_until, loa.valid_until) AS authorization_expires_at
FROM public.plaintiffs p -- Must have active fee agreement
    INNER JOIN legal.consents fa ON (
        fa.plaintiff_id = p.id
        AND fa.consent_type = 'fee_agreement'
        AND fa.status = 'active'
        AND fa.valid_from <= now()
        AND (
            fa.valid_until IS NULL
            OR fa.valid_until > now()
        )
    ) -- Must have active LOA
    INNER JOIN legal.consents loa ON (
        loa.plaintiff_id = p.id
        AND loa.consent_type = 'loa'
        AND loa.status = 'active'
        AND loa.valid_from <= now()
        AND (
            loa.valid_until IS NULL
            OR loa.valid_until > now()
        )
    )
WHERE p.status != 'inactive';
COMMENT ON VIEW enforcement.v_authorized_plaintiffs IS 'Plaintiffs with valid fee_agreement AND loa - safe for enforcement actions';
-- ============================================================================
-- PART 4: Unauthorized Plaintiffs View (for alerts/remediation)
-- ============================================================================
CREATE OR REPLACE VIEW enforcement.v_unauthorized_plaintiffs AS
SELECT p.id AS plaintiff_id,
    p.org_id,
    p.name AS plaintiff_name,
    p.status AS plaintiff_status,
    p.created_at AS plaintiff_created_at,
    -- Missing authorizations
    CASE
        WHEN fa.id IS NULL THEN true
        ELSE false
    END AS missing_fee_agreement,
    CASE
        WHEN loa.id IS NULL THEN true
        ELSE false
    END AS missing_loa,
    -- Existing but expired/revoked
    fa.status AS fee_agreement_status,
    loa.status AS loa_status,
    -- How long they've been unauthorized
    now() - p.created_at AS days_since_intake
FROM public.plaintiffs p -- Left join to find missing consents
    LEFT JOIN legal.consents fa ON (
        fa.plaintiff_id = p.id
        AND fa.consent_type = 'fee_agreement'
        AND fa.status = 'active'
        AND fa.valid_from <= now()
        AND (
            fa.valid_until IS NULL
            OR fa.valid_until > now()
        )
    )
    LEFT JOIN legal.consents loa ON (
        loa.plaintiff_id = p.id
        AND loa.consent_type = 'loa'
        AND loa.status = 'active'
        AND loa.valid_from <= now()
        AND (
            loa.valid_until IS NULL
            OR loa.valid_until > now()
        )
    )
WHERE p.status != 'inactive'
    AND (
        fa.id IS NULL
        OR loa.id IS NULL
    );
COMMENT ON VIEW enforcement.v_unauthorized_plaintiffs IS 'Plaintiffs missing required authorizations - need remediation';
-- ============================================================================
-- PART 5: Helper Functions
-- ============================================================================
-- Check if a plaintiff is authorized for enforcement
CREATE OR REPLACE FUNCTION legal.is_authorized(p_plaintiff_id UUID) RETURNS BOOLEAN LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = legal,
    public AS $$
SELECT EXISTS (
        SELECT 1
        FROM enforcement.v_authorized_plaintiffs
        WHERE plaintiff_id = p_plaintiff_id
    );
$$;
COMMENT ON FUNCTION legal.is_authorized IS 'Check if plaintiff has valid fee_agreement + loa';
-- Record a new consent
CREATE OR REPLACE FUNCTION legal.record_consent(
        p_org_id UUID,
        p_plaintiff_id UUID,
        p_consent_type legal.consent_type,
        p_version TEXT,
        p_document_hash UUID DEFAULT NULL,
        p_accepted_by_ip INET DEFAULT NULL,
        p_valid_until TIMESTAMPTZ DEFAULT NULL,
        p_metadata JSONB DEFAULT '{}'
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = legal,
    public AS $$
DECLARE v_consent_id UUID;
BEGIN -- Mark any existing active consent of same type as superseded
UPDATE legal.consents
SET status = 'superseded',
    updated_at = now()
WHERE plaintiff_id = p_plaintiff_id
    AND consent_type = p_consent_type
    AND status = 'active';
-- Insert new consent
INSERT INTO legal.consents (
        org_id,
        plaintiff_id,
        consent_type,
        version,
        document_hash,
        accepted_by_ip,
        valid_until,
        metadata
    )
VALUES (
        p_org_id,
        p_plaintiff_id,
        p_consent_type,
        p_version,
        p_document_hash,
        p_accepted_by_ip,
        p_valid_until,
        p_metadata
    )
RETURNING id INTO v_consent_id;
RETURN v_consent_id;
END;
$$;
COMMENT ON FUNCTION legal.record_consent IS 'Record a new consent, superseding any existing active consent of same type';
-- Revoke a consent
CREATE OR REPLACE FUNCTION legal.revoke_consent(
        p_consent_id UUID,
        p_reason TEXT DEFAULT 'Revoked by request'
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = legal AS $$ BEGIN
UPDATE legal.consents
SET status = 'revoked',
    revoked_at = now(),
    revoked_reason = p_reason
WHERE id = p_consent_id
    AND status = 'active';
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION legal.revoke_consent IS 'Revoke an active consent';
-- ============================================================================
-- PART 6: Grants
-- ============================================================================
GRANT USAGE ON SCHEMA legal TO authenticated,
    service_role;
GRANT USAGE ON SCHEMA enforcement TO authenticated,
    service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON legal.consents TO authenticated;
GRANT ALL ON legal.consents TO service_role;
GRANT SELECT ON legal.consent_history TO authenticated;
GRANT ALL ON legal.consent_history TO service_role;
GRANT SELECT ON enforcement.v_authorized_plaintiffs TO authenticated;
GRANT SELECT ON enforcement.v_authorized_plaintiffs TO service_role;
GRANT SELECT ON enforcement.v_unauthorized_plaintiffs TO authenticated;
GRANT SELECT ON enforcement.v_unauthorized_plaintiffs TO service_role;
GRANT EXECUTE ON FUNCTION legal.is_authorized TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION legal.record_consent TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION legal.revoke_consent TO authenticated,
    service_role;
-- ============================================================================
-- Migration Complete
-- ============================================================================
