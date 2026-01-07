-- ============================================================================
-- Migration: Case Domain Model
-- Purpose: Normalized case pipeline with parties, cases, and state tracking
-- Date: 2026-01-05
-- ============================================================================
-- ============================================================================
-- PART 1: Enums
-- ============================================================================
-- Party type enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'party_type'
) THEN CREATE TYPE public.party_type AS ENUM (
    'individual',
    'company',
    'trust',
    'estate',
    'government',
    'other'
);
END IF;
END $$;
-- Party role in a case
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'case_party_role'
) THEN CREATE TYPE public.case_party_role AS ENUM (
    'plaintiff',
    'defendant',
    'attorney',
    'garnishee',
    'judgment_creditor',
    'judgment_debtor',
    'third_party'
);
END IF;
END $$;
-- Case stage enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'case_stage'
) THEN CREATE TYPE public.case_stage AS ENUM (
    'intake',
    'skip_tracing',
    'demand',
    'negotiation',
    'litigation',
    'judgment',
    'enforcement',
    'garnishment',
    'collections',
    'closed',
    'dormant'
);
END IF;
END $$;
-- ============================================================================
-- PART 2: Parties Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.parties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    -- Identity
    name TEXT NOT NULL,
    -- Normalized legal name
    name_normalized TEXT GENERATED ALWAYS AS (lower(trim(name))) STORED,
    type public.party_type NOT NULL DEFAULT 'individual',
    -- Identifiers (nullable, PII)
    ssn_last4 CHAR(4),
    -- Last 4 of SSN (individuals)
    ein TEXT,
    -- Employer ID (companies)
    drivers_license TEXT,
    -- Contact information (structured JSONB)
    contact_info JSONB NOT NULL DEFAULT '{}',
    -- Expected structure:
    -- {
    --   "emails": [{"value": "...", "type": "primary|work|personal", "verified": bool}],
    --   "phones": [{"value": "...", "type": "mobile|home|work", "verified": bool}],
    --   "addresses": [{"street": "...", "city": "...", "state": "...", "zip": "...", "type": "primary|mailing"}]
    -- }
    -- Metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Constraints
    CONSTRAINT chk_ssn_format CHECK (
        ssn_last4 IS NULL
        OR ssn_last4 ~ '^[0-9]{4}$'
    )
);
-- Table comment
COMMENT ON TABLE public.parties IS '{"description": "Normalized party records (plaintiffs, defendants, etc.)", "sensitivity": "HIGH", "contains_pii": true}';
-- Column classifications
COMMENT ON COLUMN public.parties.id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
COMMENT ON COLUMN public.parties.org_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Owning organization"}';
COMMENT ON COLUMN public.parties.name IS '{"tag": "PII", "sensitivity": "HIGH", "description": "Legal name of party"}';
COMMENT ON COLUMN public.parties.name_normalized IS '{"tag": "PII", "sensitivity": "HIGH", "description": "Normalized lowercase name for matching"}';
COMMENT ON COLUMN public.parties.type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Party type (individual/company)"}';
COMMENT ON COLUMN public.parties.ssn_last4 IS '{"tag": "PII", "sensitivity": "CRITICAL", "description": "Last 4 digits of SSN"}';
COMMENT ON COLUMN public.parties.ein IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Employer Identification Number"}';
COMMENT ON COLUMN public.parties.drivers_license IS '{"tag": "PII", "sensitivity": "CRITICAL", "description": "Drivers license number"}';
COMMENT ON COLUMN public.parties.contact_info IS '{"tag": "PII", "sensitivity": "HIGH", "description": "Structured contact information (emails, phones, addresses)"}';
COMMENT ON COLUMN public.parties.notes IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Internal notes about party"}';
COMMENT ON COLUMN public.parties.metadata IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Additional metadata"}';
COMMENT ON COLUMN public.parties.created_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record creation timestamp"}';
COMMENT ON COLUMN public.parties.updated_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record update timestamp"}';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_parties_org_id ON public.parties(org_id);
CREATE INDEX IF NOT EXISTS idx_parties_name_normalized ON public.parties(name_normalized);
CREATE INDEX IF NOT EXISTS idx_parties_type ON public.parties(type);
CREATE INDEX IF NOT EXISTS idx_parties_ssn_last4 ON public.parties(ssn_last4)
WHERE ssn_last4 IS NOT NULL;
-- GIN index for contact_info JSONB searches
CREATE INDEX IF NOT EXISTS idx_parties_contact_info ON public.parties USING GIN (contact_info);
-- ============================================================================
-- PART 3: Cases Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.cases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    -- Case identification
    case_number TEXT NOT NULL,
    court TEXT NOT NULL,
    county TEXT,
    state CHAR(2),
    -- US state abbreviation
    docket_ref TEXT,
    -- External docket reference
    -- Judgment details
    judgment_date DATE,
    filing_date DATE,
    -- Financial
    principal_amount NUMERIC(15, 2) NOT NULL DEFAULT 0,
    interest_rate NUMERIC(5, 4) DEFAULT 0,
    -- e.g., 0.0999 = 9.99%
    current_balance NUMERIC(15, 2) NOT NULL DEFAULT 0,
    total_collected NUMERIC(15, 2) NOT NULL DEFAULT 0,
    -- External references
    source_system TEXT,
    -- Where this case came from (e.g., 'simplicity', 'jbi')
    source_id TEXT,
    -- ID in source system
    -- Metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Constraints
    CONSTRAINT uq_case_identity UNIQUE (org_id, case_number, court),
    CONSTRAINT chk_amounts_positive CHECK (
        principal_amount >= 0
        AND current_balance >= 0
        AND total_collected >= 0
    ),
    CONSTRAINT chk_state_format CHECK (
        state IS NULL
        OR state ~ '^[A-Z]{2}$'
    )
);
-- Table comment
COMMENT ON TABLE public.cases IS '{"description": "Core case/judgment records", "sensitivity": "HIGH", "contains_pii": false}';
-- Column classifications
COMMENT ON COLUMN public.cases.id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
COMMENT ON COLUMN public.cases.org_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Owning organization"}';
COMMENT ON COLUMN public.cases.case_number IS '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "Court-assigned case number"}';
COMMENT ON COLUMN public.cases.court IS '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "Court name"}';
COMMENT ON COLUMN public.cases.county IS '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "County of jurisdiction"}';
COMMENT ON COLUMN public.cases.state IS '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "State abbreviation"}';
COMMENT ON COLUMN public.cases.docket_ref IS '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "External docket reference"}';
COMMENT ON COLUMN public.cases.judgment_date IS '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "Date judgment was entered"}';
COMMENT ON COLUMN public.cases.filing_date IS '{"tag": "PUBLIC", "sensitivity": "LOW", "description": "Date case was filed"}';
COMMENT ON COLUMN public.cases.principal_amount IS '{"tag": "FINANCIAL", "sensitivity": "HIGH", "description": "Original judgment principal"}';
COMMENT ON COLUMN public.cases.interest_rate IS '{"tag": "FINANCIAL", "sensitivity": "MEDIUM", "description": "Post-judgment interest rate"}';
COMMENT ON COLUMN public.cases.current_balance IS '{"tag": "FINANCIAL", "sensitivity": "HIGH", "description": "Current balance owed"}';
COMMENT ON COLUMN public.cases.total_collected IS '{"tag": "FINANCIAL", "sensitivity": "HIGH", "description": "Total amount collected"}';
COMMENT ON COLUMN public.cases.source_system IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Source system identifier"}';
COMMENT ON COLUMN public.cases.source_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "ID in source system"}';
COMMENT ON COLUMN public.cases.notes IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Internal case notes"}';
COMMENT ON COLUMN public.cases.metadata IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Additional metadata"}';
COMMENT ON COLUMN public.cases.created_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record creation timestamp"}';
COMMENT ON COLUMN public.cases.updated_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record update timestamp"}';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_cases_org_id ON public.cases(org_id);
CREATE INDEX IF NOT EXISTS idx_cases_case_number ON public.cases(case_number);
CREATE INDEX IF NOT EXISTS idx_cases_court ON public.cases(court);
CREATE INDEX IF NOT EXISTS idx_cases_judgment_date ON public.cases(judgment_date);
CREATE INDEX IF NOT EXISTS idx_cases_source ON public.cases(source_system, source_id);
-- ============================================================================
-- PART 4: Case Parties Junction Table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.case_parties (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    -- Relationships
    case_id UUID NOT NULL REFERENCES public.cases(id) ON DELETE CASCADE,
    party_id UUID NOT NULL REFERENCES public.parties(id) ON DELETE RESTRICT,
    -- Role in this case
    role public.case_party_role NOT NULL,
    is_primary BOOLEAN NOT NULL DEFAULT false,
    -- Optional: Attorney relationship
    represented_by UUID REFERENCES public.parties(id),
    -- FK to attorney party
    -- Metadata
    notes TEXT,
    metadata JSONB DEFAULT '{}',
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Constraints
    CONSTRAINT uq_case_party_role UNIQUE (case_id, party_id, role)
);
-- Table comment
COMMENT ON TABLE public.case_parties IS '{"description": "Links parties to cases with roles", "sensitivity": "MEDIUM"}';
-- Column classifications
COMMENT ON COLUMN public.case_parties.id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
COMMENT ON COLUMN public.case_parties.org_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Owning organization"}';
COMMENT ON COLUMN public.case_parties.case_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "FK to case"}';
COMMENT ON COLUMN public.case_parties.party_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "FK to party"}';
COMMENT ON COLUMN public.case_parties.role IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Role in case (plaintiff/defendant/etc.)"}';
COMMENT ON COLUMN public.case_parties.is_primary IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Is this the primary party in role"}';
COMMENT ON COLUMN public.case_parties.represented_by IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "FK to representing attorney"}';
COMMENT ON COLUMN public.case_parties.notes IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Notes about party role"}';
COMMENT ON COLUMN public.case_parties.metadata IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Additional metadata"}';
COMMENT ON COLUMN public.case_parties.created_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record creation timestamp"}';
COMMENT ON COLUMN public.case_parties.updated_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record update timestamp"}';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_case_parties_case_id ON public.case_parties(case_id);
CREATE INDEX IF NOT EXISTS idx_case_parties_party_id ON public.case_parties(party_id);
CREATE INDEX IF NOT EXISTS idx_case_parties_role ON public.case_parties(role);
CREATE INDEX IF NOT EXISTS idx_case_parties_org_id ON public.case_parties(org_id);
-- ============================================================================
-- PART 5: Case State Table (1:1 with cases)
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.case_state (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id UUID NOT NULL REFERENCES tenant.orgs(id),
    -- 1:1 relationship with cases
    case_id UUID NOT NULL UNIQUE REFERENCES public.cases(id) ON DELETE CASCADE,
    -- Current state
    stage public.case_stage NOT NULL DEFAULT 'intake',
    status TEXT NOT NULL DEFAULT 'new',
    -- Free-form status within stage
    substatus TEXT,
    -- Optional substatus
    -- Action tracking
    last_action_at TIMESTAMPTZ,
    last_action_type TEXT,
    last_action_by UUID,
    -- User who took last action
    next_action_due TIMESTAMPTZ,
    next_action_type TEXT,
    -- Assignment
    assigned_to UUID,
    -- User assigned to case
    assigned_at TIMESTAMPTZ,
    -- Flags
    is_priority BOOLEAN NOT NULL DEFAULT false,
    is_on_hold BOOLEAN NOT NULL DEFAULT false,
    hold_reason TEXT,
    -- Metadata
    metadata JSONB DEFAULT '{}',
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Table comment
COMMENT ON TABLE public.case_state IS '{"description": "Case stage and workflow state (1:1 with cases)", "sensitivity": "MEDIUM"}';
-- Column classifications
COMMENT ON COLUMN public.case_state.id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Primary key UUID"}';
COMMENT ON COLUMN public.case_state.org_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Owning organization"}';
COMMENT ON COLUMN public.case_state.case_id IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "FK to case (1:1)"}';
COMMENT ON COLUMN public.case_state.stage IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Current pipeline stage"}';
COMMENT ON COLUMN public.case_state.status IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Status within stage"}';
COMMENT ON COLUMN public.case_state.substatus IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Optional substatus"}';
COMMENT ON COLUMN public.case_state.last_action_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Timestamp of last action"}';
COMMENT ON COLUMN public.case_state.last_action_type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Type of last action"}';
COMMENT ON COLUMN public.case_state.last_action_by IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "User who took last action"}';
COMMENT ON COLUMN public.case_state.next_action_due IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "When next action is due"}';
COMMENT ON COLUMN public.case_state.next_action_type IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Type of next action"}';
COMMENT ON COLUMN public.case_state.assigned_to IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Assigned user"}';
COMMENT ON COLUMN public.case_state.assigned_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Assignment timestamp"}';
COMMENT ON COLUMN public.case_state.is_priority IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Priority flag"}';
COMMENT ON COLUMN public.case_state.is_on_hold IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Hold flag"}';
COMMENT ON COLUMN public.case_state.hold_reason IS '{"tag": "CONFIDENTIAL", "sensitivity": "MEDIUM", "description": "Reason for hold"}';
COMMENT ON COLUMN public.case_state.metadata IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Additional metadata"}';
COMMENT ON COLUMN public.case_state.created_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record creation timestamp"}';
COMMENT ON COLUMN public.case_state.updated_at IS '{"tag": "INTERNAL", "sensitivity": "LOW", "description": "Record update timestamp"}';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_case_state_case_id ON public.case_state(case_id);
CREATE INDEX IF NOT EXISTS idx_case_state_org_id ON public.case_state(org_id);
CREATE INDEX IF NOT EXISTS idx_case_state_stage ON public.case_state(stage);
CREATE INDEX IF NOT EXISTS idx_case_state_status ON public.case_state(status);
CREATE INDEX IF NOT EXISTS idx_case_state_next_action ON public.case_state(next_action_due)
WHERE next_action_due IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_case_state_assigned ON public.case_state(assigned_to)
WHERE assigned_to IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_case_state_priority ON public.case_state(is_priority)
WHERE is_priority = true;
-- ============================================================================
-- PART 6: Auto-Update Triggers
-- ============================================================================
-- Generic updated_at trigger function
CREATE OR REPLACE FUNCTION public.update_timestamp() RETURNS TRIGGER LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at := now();
RETURN NEW;
END;
$$;
-- Apply to all tables
DROP TRIGGER IF EXISTS trg_parties_updated_at ON public.parties;
CREATE TRIGGER trg_parties_updated_at BEFORE
UPDATE ON public.parties FOR EACH ROW EXECUTE FUNCTION public.update_timestamp();
DROP TRIGGER IF EXISTS trg_cases_updated_at ON public.cases;
CREATE TRIGGER trg_cases_updated_at BEFORE
UPDATE ON public.cases FOR EACH ROW EXECUTE FUNCTION public.update_timestamp();
DROP TRIGGER IF EXISTS trg_case_parties_updated_at ON public.case_parties;
CREATE TRIGGER trg_case_parties_updated_at BEFORE
UPDATE ON public.case_parties FOR EACH ROW EXECUTE FUNCTION public.update_timestamp();
DROP TRIGGER IF EXISTS trg_case_state_updated_at ON public.case_state;
CREATE TRIGGER trg_case_state_updated_at BEFORE
UPDATE ON public.case_state FOR EACH ROW EXECUTE FUNCTION public.update_timestamp();
-- ============================================================================
-- PART 7: Auto-Create Case State Trigger
-- ============================================================================
-- Automatically create case_state when a case is inserted
CREATE OR REPLACE FUNCTION public.auto_create_case_state() RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$ BEGIN
INSERT INTO public.case_state (org_id, case_id, stage, status)
VALUES (NEW.org_id, NEW.id, 'intake', 'new') ON CONFLICT (case_id) DO NOTHING;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_auto_create_case_state ON public.cases;
CREATE TRIGGER trg_auto_create_case_state
AFTER
INSERT ON public.cases FOR EACH ROW EXECUTE FUNCTION public.auto_create_case_state();
-- ============================================================================
-- PART 8: Row Level Security
-- ============================================================================
-- Enable RLS on all tables
ALTER TABLE public.parties ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_parties ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.case_state ENABLE ROW LEVEL SECURITY;
-- Force RLS for table owners
ALTER TABLE public.parties FORCE ROW LEVEL SECURITY;
ALTER TABLE public.cases FORCE ROW LEVEL SECURITY;
ALTER TABLE public.case_parties FORCE ROW LEVEL SECURITY;
ALTER TABLE public.case_state FORCE ROW LEVEL SECURITY;
-- -----------------------------------------------------------------------------
-- Parties RLS
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "parties_org_isolation" ON public.parties;
CREATE POLICY "parties_org_isolation" ON public.parties FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "parties_service_role_bypass" ON public.parties;
CREATE POLICY "parties_service_role_bypass" ON public.parties FOR ALL TO service_role USING (true) WITH CHECK (true);
-- -----------------------------------------------------------------------------
-- Cases RLS
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "cases_org_isolation" ON public.cases;
CREATE POLICY "cases_org_isolation" ON public.cases FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "cases_service_role_bypass" ON public.cases;
CREATE POLICY "cases_service_role_bypass" ON public.cases FOR ALL TO service_role USING (true) WITH CHECK (true);
-- -----------------------------------------------------------------------------
-- Case Parties RLS
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "case_parties_org_isolation" ON public.case_parties;
CREATE POLICY "case_parties_org_isolation" ON public.case_parties FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "case_parties_service_role_bypass" ON public.case_parties;
CREATE POLICY "case_parties_service_role_bypass" ON public.case_parties FOR ALL TO service_role USING (true) WITH CHECK (true);
-- -----------------------------------------------------------------------------
-- Case State RLS
-- -----------------------------------------------------------------------------
DROP POLICY IF EXISTS "case_state_org_isolation" ON public.case_state;
CREATE POLICY "case_state_org_isolation" ON public.case_state FOR ALL USING (
    org_id IN (
        SELECT tenant.user_org_ids()
    )
);
DROP POLICY IF EXISTS "case_state_service_role_bypass" ON public.case_state;
CREATE POLICY "case_state_service_role_bypass" ON public.case_state FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ============================================================================
-- PART 9: Grants
-- ============================================================================
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.parties TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.cases TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.case_parties TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.case_state TO authenticated;
GRANT ALL ON public.parties TO service_role;
GRANT ALL ON public.cases TO service_role;
GRANT ALL ON public.case_parties TO service_role;
GRANT ALL ON public.case_state TO service_role;
-- ============================================================================
-- PART 10: Convenience Views
-- ============================================================================
-- Full case view with primary plaintiff and defendant
CREATE OR REPLACE VIEW public.v_cases_full AS
SELECT c.id AS case_id,
    c.org_id,
    c.case_number,
    c.court,
    c.county,
    c.state,
    c.judgment_date,
    c.principal_amount,
    c.current_balance,
    c.total_collected,
    -- Primary plaintiff
    pp.id AS plaintiff_id,
    pp.name AS plaintiff_name,
    pp.type AS plaintiff_type,
    -- Primary defendant
    pd.id AS defendant_id,
    pd.name AS defendant_name,
    pd.type AS defendant_type,
    -- State
    cs.stage,
    cs.status,
    cs.next_action_due,
    cs.is_priority,
    cs.is_on_hold,
    cs.assigned_to,
    c.created_at,
    c.updated_at
FROM public.cases c
    LEFT JOIN public.case_state cs ON cs.case_id = c.id
    LEFT JOIN public.case_parties cpp ON (
        cpp.case_id = c.id
        AND cpp.role = 'plaintiff'
        AND cpp.is_primary = true
    )
    LEFT JOIN public.parties pp ON pp.id = cpp.party_id
    LEFT JOIN public.case_parties cpd ON (
        cpd.case_id = c.id
        AND cpd.role = 'defendant'
        AND cpd.is_primary = true
    )
    LEFT JOIN public.parties pd ON pd.id = cpd.party_id;
COMMENT ON VIEW public.v_cases_full IS 'Full case view with primary parties and state';
GRANT SELECT ON public.v_cases_full TO authenticated,
    service_role;
-- ============================================================================
-- Migration Complete
-- ============================================================================
