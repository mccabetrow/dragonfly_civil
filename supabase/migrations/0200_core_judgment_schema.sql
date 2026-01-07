-- ============================================================================
-- 0200_core_judgment_schema.sql
-- Core Judgment Schema: standardized judgment, debtor intelligence, and
-- enforcement action tables for Dragonfly Civil
-- ============================================================================
--
-- PURPOSE:
--   Introduce three canonical tables that formalize the judgment enforcement
--   data model. These tables are additive—they do NOT replace or drop any
--   existing structures. Future migrations may consolidate legacy tables
--   (public.judgments, judgments.cases, etc.) once data is migrated.
--
-- LEGAL CONTEXT:
--   - NY CPLR Article 52 governs enforcement remedies.
--   - Money judgments enforceable 20 years (CPLR 211(b)).
--   - Real property liens last 10 years, renewable once.
--
-- SAFE PATTERNS:
--   - CREATE TABLE IF NOT EXISTS
--   - CREATE TYPE IF NOT EXISTS (via DO blocks)
--   - ADD COLUMN IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
--
-- ============================================================================
-- ============================================================================
-- ENUM TYPES
-- ============================================================================
-- judgment_status_enum: tracks lifecycle stage of a judgment
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'judgment_status_enum'
) THEN CREATE TYPE public.judgment_status_enum AS ENUM (
    'unsatisfied',
    -- Judgment entered, no payments received
    'partially_satisfied',
    -- Partial payments made
    'satisfied',
    -- Fully paid / discharged
    'vacated',
    -- Judgment overturned
    'expired',
    -- Exceeded statutory enforcement window
    'on_hold' -- Paused for legal/compliance reasons
);
END IF;
END $$;
COMMENT ON TYPE public.judgment_status_enum IS 'Lifecycle status of a judgment record.';
-- enforcement_action_type_enum: categorizes enforcement attempts
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'enforcement_action_type_enum'
) THEN CREATE TYPE public.enforcement_action_type_enum AS ENUM (
    'information_subpoena',
    -- CPLR 5224 subpoena
    'restraining_notice',
    -- CPLR 5222 restraint
    'property_execution',
    -- Sheriff levy on personal property
    'income_execution',
    -- Wage garnishment (CPLR 5231)
    'bank_levy',
    -- Bank account levy
    'real_property_lien',
    -- Docketed judgment lien
    'demand_letter',
    -- Pre-enforcement demand
    'settlement_offer',
    -- Negotiated payment plan offer
    'skiptrace',
    -- Debtor location attempt
    'asset_search',
    -- Asset discovery investigation
    'other' -- Catch-all for future types
);
END IF;
END $$;
COMMENT ON TYPE public.enforcement_action_type_enum IS 'Types of enforcement actions taken on a judgment.';
-- enforcement_action_status_enum: status of a specific enforcement action
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'enforcement_action_status_enum'
) THEN CREATE TYPE public.enforcement_action_status_enum AS ENUM (
    'planned',
    -- Queued but not started
    'pending',
    -- Initiated, awaiting response
    'served',
    -- Served/delivered to recipient
    'completed',
    -- Action finished successfully
    'failed',
    -- Action failed (e.g., wrong address)
    'cancelled',
    -- Withdrawn before completion
    'expired' -- Time-limited action expired
);
END IF;
END $$;
COMMENT ON TYPE public.enforcement_action_status_enum IS 'Status of an individual enforcement action.';
-- ============================================================================
-- TABLE: public.core_judgments
-- ============================================================================
-- One row per judgment. This is the canonical source for judgment data in the
-- new schema. Existing tables (public.judgments, judgments.judgments) remain
-- for backward compatibility until data migration is complete.
--
-- TODO: Future consolidation task—migrate data from public.judgments and
--       judgments.judgments into core_judgments, then deprecate legacy tables.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.core_judgments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Case identifiers
    case_index_number text UNIQUE NOT NULL,
    -- Court index/docket number
    -- Party information
    debtor_name text,
    -- Primary debtor name
    original_creditor text,
    -- Original judgment creditor
    -- Judgment details
    judgment_date date,
    -- Date judgment was entered
    principal_amount numeric(14, 2),
    -- Original judgment amount
    interest_rate numeric(5, 2) DEFAULT 9.0,
    -- NY statutory rate is 9%
    -- Court information
    court_name text,
    -- Full court name
    county text,
    -- NY county
    -- Status and lifecycle
    status public.judgment_status_enum DEFAULT 'unsatisfied',
    -- Computed expiration dates (NY CPLR rules)
    -- Real property liens: 10 years from entry (CPLR 5203)
    lien_expiry_date date GENERATED ALWAYS AS (judgment_date + INTERVAL '10 years') STORED,
    -- Judgment enforcement window: 20 years from entry (CPLR 211(b))
    judgment_expiry_date date GENERATED ALWAYS AS (judgment_date + INTERVAL '20 years') STORED,
    -- Scoring and prioritization
    collectability_score int CHECK (
        collectability_score BETWEEN 0 AND 100
    ),
    -- Audit timestamps
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_core_judgments_status ON public.core_judgments (status);
CREATE INDEX IF NOT EXISTS idx_core_judgments_county ON public.core_judgments (county);
CREATE INDEX IF NOT EXISTS idx_core_judgments_collectability ON public.core_judgments (collectability_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_core_judgments_judgment_date ON public.core_judgments (judgment_date DESC);
CREATE INDEX IF NOT EXISTS idx_core_judgments_lien_expiry ON public.core_judgments (lien_expiry_date)
WHERE status NOT IN ('satisfied', 'vacated', 'expired');
CREATE INDEX IF NOT EXISTS idx_core_judgments_judgment_expiry ON public.core_judgments (judgment_expiry_date)
WHERE status NOT IN ('satisfied', 'vacated', 'expired');
-- Touch updated_at on update
DROP TRIGGER IF EXISTS trg_core_judgments_touch_updated ON public.core_judgments;
CREATE TRIGGER trg_core_judgments_touch_updated BEFORE
UPDATE ON public.core_judgments FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
COMMENT ON TABLE public.core_judgments IS 'Canonical judgment records. One row per judgment entered by a court.';
COMMENT ON COLUMN public.core_judgments.case_index_number IS 'Court-assigned docket/index number (unique identifier).';
COMMENT ON COLUMN public.core_judgments.interest_rate IS 'Applicable interest rate (default 9% per NY CPLR 5004).';
COMMENT ON COLUMN public.core_judgments.lien_expiry_date IS 'Date real property lien expires (10 years from judgment per CPLR 5203).';
COMMENT ON COLUMN public.core_judgments.judgment_expiry_date IS 'Date enforcement window closes (20 years from judgment per CPLR 211(b)).';
COMMENT ON COLUMN public.core_judgments.collectability_score IS 'Scoring 0-100 based on enrichment signals; higher = more likely to collect.';
-- ============================================================================
-- TABLE: public.debtor_intelligence
-- ============================================================================
-- Enriched data linked to a judgment. Stores employment, banking, and asset
-- information discovered through skiptrace, FOIL, or manual research.
--
-- NOTE: Existing enrichment data lives in judgments.enrichment_runs and
--       judgments.foil_responses. This table provides a structured alternative.
--
-- TODO: Consider view or materialized view to unify legacy enrichment sources
--       with this table for a single intelligence API.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.debtor_intelligence (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Link to judgment
    judgment_id uuid NOT NULL REFERENCES public.core_judgments(id) ON DELETE CASCADE,
    -- Data provenance
    data_source text,
    -- e.g., 'lexisnexis', 'foil', 'manual', 'skiptrace'
    -- Employment intelligence
    employer_name text,
    employer_address text,
    income_band text,
    -- e.g., '$50k-75k', '$75k-100k'
    -- Banking intelligence
    bank_name text,
    bank_address text,
    -- Asset indicators
    home_ownership text,
    -- 'owner', 'renter', 'unknown'
    has_benefits_only_account boolean,
    -- True if account exempt under CPLR 5222(d)
    -- Quality metrics
    confidence_score numeric(5, 2),
    -- 0-100 confidence in data accuracy
    is_verified boolean DEFAULT false,
    -- Human-verified flag
    -- Audit timestamps
    last_updated timestamptz NOT NULL DEFAULT timezone('utc', now()),
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
-- Indexes for common lookups
CREATE INDEX IF NOT EXISTS idx_debtor_intelligence_judgment ON public.debtor_intelligence (judgment_id);
CREATE INDEX IF NOT EXISTS idx_debtor_intelligence_source ON public.debtor_intelligence (data_source);
CREATE INDEX IF NOT EXISTS idx_debtor_intelligence_verified ON public.debtor_intelligence (is_verified)
WHERE is_verified = true;
-- Touch last_updated on update
DROP TRIGGER IF EXISTS trg_debtor_intelligence_touch_updated ON public.debtor_intelligence;
CREATE TRIGGER trg_debtor_intelligence_touch_updated BEFORE
UPDATE ON public.debtor_intelligence FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
-- Adapt trigger to update last_updated instead of updated_at
CREATE OR REPLACE FUNCTION public.touch_last_updated() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.last_updated = timezone('utc', now());
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_debtor_intelligence_touch_last_updated ON public.debtor_intelligence;
CREATE TRIGGER trg_debtor_intelligence_touch_last_updated BEFORE
UPDATE ON public.debtor_intelligence FOR EACH ROW EXECUTE FUNCTION public.touch_last_updated();
COMMENT ON TABLE public.debtor_intelligence IS 'Enriched debtor information linked to judgments—employment, banking, assets.';
COMMENT ON COLUMN public.debtor_intelligence.data_source IS 'Origin of the intelligence (lexisnexis, foil, manual, skiptrace, etc.).';
COMMENT ON COLUMN public.debtor_intelligence.income_band IS 'Estimated income range for wage garnishment planning.';
COMMENT ON COLUMN public.debtor_intelligence.has_benefits_only_account IS 'True if debtor bank account may be exempt under CPLR 5222(d).';
COMMENT ON COLUMN public.debtor_intelligence.confidence_score IS 'Data quality score 0-100; higher = more reliable.';
COMMENT ON COLUMN public.debtor_intelligence.is_verified IS 'True if a human has verified this record.';
-- ============================================================================
-- TABLE: public.enforcement_actions
-- ============================================================================
-- Log of each enforcement attempt or document generated for a judgment.
-- This complements existing public.enforcement_timeline and
-- public.enforcement_history tables with structured action typing.
--
-- TODO: Evaluate unifying enforcement_timeline events with this table or
--       creating a view that joins both for a consolidated action feed.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.enforcement_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Link to judgment
    judgment_id uuid NOT NULL REFERENCES public.core_judgments(id) ON DELETE CASCADE,
    -- Action classification
    action_type public.enforcement_action_type_enum NOT NULL,
    status public.enforcement_action_status_enum DEFAULT 'planned',
    -- Legal workflow flags
    requires_attorney_signature boolean DEFAULT false,
    -- True if attorney must sign before sending
    -- Generated documents
    generated_url text,
    -- Link to generated PDF/document
    -- Notes and metadata
    notes text,
    -- Free-form notes
    metadata jsonb DEFAULT '{}'::jsonb,
    -- Extensible structured data
    -- Audit timestamps
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_enforcement_actions_judgment ON public.enforcement_actions (judgment_id);
CREATE INDEX IF NOT EXISTS idx_enforcement_actions_type ON public.enforcement_actions (action_type);
CREATE INDEX IF NOT EXISTS idx_enforcement_actions_status ON public.enforcement_actions (status);
CREATE INDEX IF NOT EXISTS idx_enforcement_actions_pending_signature ON public.enforcement_actions (requires_attorney_signature)
WHERE requires_attorney_signature = true
    AND status IN ('planned', 'pending');
CREATE INDEX IF NOT EXISTS idx_enforcement_actions_created ON public.enforcement_actions (created_at DESC);
-- Touch updated_at on update
DROP TRIGGER IF EXISTS trg_enforcement_actions_touch_updated ON public.enforcement_actions;
CREATE TRIGGER trg_enforcement_actions_touch_updated BEFORE
UPDATE ON public.enforcement_actions FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
COMMENT ON TABLE public.enforcement_actions IS 'Log of enforcement attempts and generated documents per judgment.';
COMMENT ON COLUMN public.enforcement_actions.action_type IS 'Type of enforcement action (subpoena, levy, garnishment, etc.).';
COMMENT ON COLUMN public.enforcement_actions.requires_attorney_signature IS 'True if document needs attorney sign-off before service.';
COMMENT ON COLUMN public.enforcement_actions.generated_url IS 'URL or storage path to generated enforcement document.';
COMMENT ON COLUMN public.enforcement_actions.metadata IS 'Extensible JSON for action-specific data (e.g., served_to, response_deadline).';
-- ============================================================================
-- ROW LEVEL SECURITY
-- ============================================================================
-- Apply RLS to all three tables following existing Dragonfly patterns:
--   - service_role: full CRUD
--   - authenticated: read-only
--   - anon: read-only (for dashboard)
-- ============================================================================
-- core_judgments RLS
ALTER TABLE public.core_judgments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS core_judgments_select_public ON public.core_judgments;
DROP POLICY IF EXISTS core_judgments_insert_service ON public.core_judgments;
DROP POLICY IF EXISTS core_judgments_update_service ON public.core_judgments;
DROP POLICY IF EXISTS core_judgments_delete_service ON public.core_judgments;
CREATE POLICY core_judgments_select_public ON public.core_judgments FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
CREATE POLICY core_judgments_insert_service ON public.core_judgments FOR
INSERT WITH CHECK (auth.role() = 'service_role');
CREATE POLICY core_judgments_update_service ON public.core_judgments FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY core_judgments_delete_service ON public.core_judgments FOR DELETE USING (auth.role() = 'service_role');
REVOKE ALL ON public.core_judgments
FROM public;
GRANT SELECT ON public.core_judgments TO anon,
    authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.core_judgments TO service_role;
-- debtor_intelligence RLS
ALTER TABLE public.debtor_intelligence ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS debtor_intelligence_select_service ON public.debtor_intelligence;
DROP POLICY IF EXISTS debtor_intelligence_insert_service ON public.debtor_intelligence;
DROP POLICY IF EXISTS debtor_intelligence_update_service ON public.debtor_intelligence;
DROP POLICY IF EXISTS debtor_intelligence_delete_service ON public.debtor_intelligence;
-- Debtor intelligence is sensitive; restrict to authenticated + service_role
CREATE POLICY debtor_intelligence_select_service ON public.debtor_intelligence FOR
SELECT USING (auth.role() IN ('authenticated', 'service_role'));
CREATE POLICY debtor_intelligence_insert_service ON public.debtor_intelligence FOR
INSERT WITH CHECK (auth.role() = 'service_role');
CREATE POLICY debtor_intelligence_update_service ON public.debtor_intelligence FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY debtor_intelligence_delete_service ON public.debtor_intelligence FOR DELETE USING (auth.role() = 'service_role');
REVOKE ALL ON public.debtor_intelligence
FROM public;
REVOKE ALL ON public.debtor_intelligence
FROM anon;
GRANT SELECT ON public.debtor_intelligence TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.debtor_intelligence TO service_role;
-- enforcement_actions RLS
ALTER TABLE public.enforcement_actions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS enforcement_actions_select_public ON public.enforcement_actions;
DROP POLICY IF EXISTS enforcement_actions_insert_service ON public.enforcement_actions;
DROP POLICY IF EXISTS enforcement_actions_update_service ON public.enforcement_actions;
DROP POLICY IF EXISTS enforcement_actions_delete_service ON public.enforcement_actions;
CREATE POLICY enforcement_actions_select_public ON public.enforcement_actions FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
CREATE POLICY enforcement_actions_insert_service ON public.enforcement_actions FOR
INSERT WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_actions_update_service ON public.enforcement_actions FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
CREATE POLICY enforcement_actions_delete_service ON public.enforcement_actions FOR DELETE USING (auth.role() = 'service_role');
REVOKE ALL ON public.enforcement_actions
FROM public;
GRANT SELECT ON public.enforcement_actions TO anon,
    authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.enforcement_actions TO service_role;
-- ============================================================================
-- CONSOLIDATION TODOs
-- ============================================================================
-- The following existing tables store overlapping data. Future work should
-- migrate/unify them with the new core tables:
--
-- 1. public.judgments
--    - Legacy judgment table with case_number, judgment_amount, etc.
--    - TODO: Create view or sync trigger to keep core_judgments aligned.
--
-- 2. judgments.judgments + judgments.cases
--    - Normalized case/judgment model in the judgments schema.
--    - TODO: Evaluate whether to migrate to core_judgments or maintain both.
--
-- 3. judgments.enrichment_runs
--    - Enrichment audit log with status and payload.
--    - TODO: Consider linking to debtor_intelligence or creating a unified view.
--
-- 4. judgments.foil_responses
--    - FOIL response payloads per case.
--    - TODO: ETL to debtor_intelligence where structured fields apply.
--
-- 5. public.enforcement_timeline / public.enforcement_history
--    - Event logs for enforcement stages.
--    - TODO: Evaluate unifying with enforcement_actions or creating a view.
--
-- 6. public.enforcement_cases
--    - Active enforcement case tracker.
--    - TODO: May link to core_judgments via judgment_id FK once migrated.
-- ============================================================================
-- End of migration
