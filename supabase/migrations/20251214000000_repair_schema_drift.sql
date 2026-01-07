-- ============================================================================
-- 20251214000000_repair_schema_drift.sql
-- Dragonfly Civil: PROD Schema Drift Repair Migration
-- ============================================================================
--
-- PURPOSE:
--   Repair schema drift in PRODUCTION where early migrations were marked as
--   applied but the actual tables/schemas are missing. This migration is
--   idempotent and can be safely run multiple times on both DEV and PROD.
--
-- DERIVED FROM:
--   - 0001_core_schema.sql
--   - 0016_cases_entities.sql
--   - 0030_judgments_table.sql
--   - 0053_enrichment_runs.sql
--   - 0071_plaintiff_model.sql
--   - 0073_enforcement_stages.sql
--   - 0076_import_runs.sql
--   - 0200_core_judgment_schema.sql
--   - 20251205100000_enforcement_radar.sql
--   - 20251206000000_intelligence_graph.sql
--   - 20251210000000_intake_fortress.sql
--
-- SAFETY PATTERNS:
--   - CREATE SCHEMA IF NOT EXISTS
--   - CREATE TABLE IF NOT EXISTS
--   - ALTER TABLE ... ADD COLUMN IF NOT EXISTS
--   - CREATE INDEX IF NOT EXISTS
--   - CREATE OR REPLACE FUNCTION/VIEW
--   - DO blocks with existence checks for types/policies
--   - Never DROP or ALTER TYPE destructively
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- SECTION 1: EXTENSIONS
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;
CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public;
-- ============================================================================
-- SECTION 2: SCHEMAS
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS judgments;
CREATE SCHEMA IF NOT EXISTS parties;
CREATE SCHEMA IF NOT EXISTS enrichment;
CREATE SCHEMA IF NOT EXISTS outreach;
CREATE SCHEMA IF NOT EXISTS intake;
CREATE SCHEMA IF NOT EXISTS enforcement;
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS ingestion;
CREATE SCHEMA IF NOT EXISTS intelligence;
-- ============================================================================
-- SECTION 3: ENUM TYPES (idempotent via DO blocks)
-- ============================================================================
-- judgments.case_status
DO $$ BEGIN CREATE TYPE judgments.case_status AS ENUM (
    'new',
    'enriched',
    'contacting',
    'intake',
    'enforcing',
    'collected',
    'dead'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- parties.entity_type
DO $$ BEGIN CREATE TYPE parties.entity_type AS ENUM ('person', 'company');
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- enrichment.contact_kind
DO $$ BEGIN CREATE TYPE enrichment.contact_kind AS ENUM ('phone', 'email', 'address');
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- enforcement.action_type
DO $$ BEGIN CREATE TYPE enforcement.action_type AS ENUM (
    'levy',
    'income_exec',
    'lien',
    'turnover'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- public.judgment_status_enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'judgment_status_enum'
) THEN CREATE TYPE public.judgment_status_enum AS ENUM (
    'unsatisfied',
    'partially_satisfied',
    'satisfied',
    'vacated',
    'expired',
    'on_hold'
);
END IF;
END $$;
-- public.enforcement_action_type_enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'enforcement_action_type_enum'
) THEN CREATE TYPE public.enforcement_action_type_enum AS ENUM (
    'information_subpoena',
    'restraining_notice',
    'property_execution',
    'income_execution',
    'bank_levy',
    'real_property_lien',
    'demand_letter',
    'settlement_offer',
    'skiptrace',
    'asset_search',
    'other'
);
END IF;
END $$;
-- public.enforcement_action_status_enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'enforcement_action_status_enum'
) THEN CREATE TYPE public.enforcement_action_status_enum AS ENUM (
    'planned',
    'pending',
    'served',
    'completed',
    'failed',
    'cancelled',
    'expired'
);
END IF;
END $$;
-- intelligence.entity_type
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'entity_type'
        AND typnamespace = (
            SELECT oid
            FROM pg_namespace
            WHERE nspname = 'intelligence'
        )
) THEN CREATE TYPE intelligence.entity_type AS ENUM (
    'person',
    'company',
    'address',
    'court',
    'attorney'
);
END IF;
END $$;
-- intelligence.relation_type
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'relation_type'
        AND typnamespace = (
            SELECT oid
            FROM pg_namespace
            WHERE nspname = 'intelligence'
        )
) THEN CREATE TYPE intelligence.relation_type AS ENUM (
    'plaintiff_in',
    'defendant_in',
    'located_at',
    'employed_by',
    'sued_at'
);
END IF;
END $$;
-- ops.intake_source_type
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'intake_source_type'
) THEN CREATE TYPE ops.intake_source_type AS ENUM (
    'simplicity',
    'jbi',
    'manual',
    'csv_upload',
    'api'
);
END IF;
END $$;
-- public.intake_validation_result
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'intake_validation_result'
) THEN CREATE TYPE public.intake_validation_result AS ENUM (
    'valid',
    'invalid',
    'needs_review'
);
END IF;
END $$;
-- ============================================================================
-- SECTION 4: HELPER FUNCTIONS
-- ============================================================================
-- touch_updated_at trigger function
CREATE OR REPLACE FUNCTION public.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at := NOW();
RETURN NEW;
END;
$$;
-- tg_touch_updated_at alias (used by some migrations)
CREATE OR REPLACE FUNCTION public.tg_touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at := NOW();
RETURN NEW;
END;
$$;
-- judgments._set_updated_at for judgments.cases
CREATE OR REPLACE FUNCTION judgments._set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at := NOW();
RETURN NEW;
END;
$$;
-- ============================================================================
-- SECTION 5: CORE TABLES - judgments schema
-- ============================================================================
-- judgments.cases
CREATE TABLE IF NOT EXISTS judgments.cases (
    case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id uuid NOT NULL DEFAULT gen_random_uuid(),
    index_no text,
    case_number text,
    court text,
    county text,
    source text,
    title text,
    filed_at date,
    filing_date date,
    judgment_at date,
    judgment_date date,
    principal_amt numeric(14, 2) DEFAULT 0,
    amount_awarded numeric(14, 2),
    interest_rate numeric(6, 4) DEFAULT 0.0900,
    interest_from date,
    costs numeric(14, 2) DEFAULT 0,
    currency text DEFAULT 'USD',
    status judgments.case_status DEFAULT 'new',
    fingerprint_hash text,
    raw jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
-- Add missing columns if table pre-existed with partial schema
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS org_id uuid;
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS case_number text;
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS title text;
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS filing_date date;
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS judgment_date date;
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS amount_awarded numeric(14, 2);
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS currency text;
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS raw jsonb;
-- Set defaults for nullable columns that should have them
DO $$ BEGIN
UPDATE judgments.cases
SET org_id = gen_random_uuid()
WHERE org_id IS NULL;
UPDATE judgments.cases
SET currency = 'USD'
WHERE currency IS NULL;
UPDATE judgments.cases
SET raw = '{}'::jsonb
WHERE raw IS NULL;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Trigger for updated_at on judgments.cases
DROP TRIGGER IF EXISTS _bu_cases ON judgments.cases;
CREATE TRIGGER _bu_cases BEFORE
UPDATE ON judgments.cases FOR EACH ROW EXECUTE FUNCTION judgments._set_updated_at();
-- Indexes
CREATE INDEX IF NOT EXISTS idx_cases_county ON judgments.cases (county);
CREATE INDEX IF NOT EXISTS idx_cases_status ON judgments.cases (status);
-- judgments.enrichment_runs
CREATE TABLE IF NOT EXISTS judgments.enrichment_runs (
    id bigserial PRIMARY KEY,
    case_id uuid NOT NULL REFERENCES judgments.cases(case_id) ON DELETE CASCADE,
    status text NOT NULL,
    summary text,
    raw jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_judgments_enrichment_runs_case_id ON judgments.enrichment_runs (case_id);
CREATE INDEX IF NOT EXISTS idx_judgments_enrichment_runs_status ON judgments.enrichment_runs (status);
-- ============================================================================
-- SECTION 6: CORE TABLES - parties schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS parties.entities (
    entity_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name_raw text NOT NULL,
    name_norm text GENERATED ALWAYS AS (
        regexp_replace(lower(name_raw), '\s+', ' ', 'g')
    ) STORED,
    type parties.entity_type NOT NULL,
    ein_ssn_hash text,
    raw jsonb,
    created_at timestamptz DEFAULT now()
);
ALTER TABLE parties.entities
ADD COLUMN IF NOT EXISTS raw jsonb;
CREATE TABLE IF NOT EXISTS parties.roles (
    case_id uuid REFERENCES judgments.cases (case_id) ON DELETE CASCADE,
    entity_id uuid REFERENCES parties.entities (entity_id) ON DELETE CASCADE,
    role text CHECK (role IN ('plaintiff', 'defendant', 'attorney')),
    PRIMARY KEY (case_id, entity_id, role)
);
-- Create trigram index on name_norm if the column exists
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'parties'
        AND table_name = 'entities'
        AND column_name = 'name_norm'
) THEN CREATE INDEX IF NOT EXISTS idx_entities_name_norm_trgm ON parties.entities USING gin (name_norm gin_trgm_ops);
END IF;
END $$;
-- ============================================================================
-- SECTION 7: CORE TABLES - enrichment schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS enrichment.contacts (
    contact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id uuid NOT NULL REFERENCES parties.entities (entity_id) ON DELETE CASCADE,
    kind enrichment.contact_kind NOT NULL,
    value text NOT NULL,
    source text,
    validated_bool boolean DEFAULT false,
    score numeric(5, 2) DEFAULT 0,
    created_at timestamptz DEFAULT now(),
    UNIQUE (entity_id, kind, value)
);
CREATE TABLE IF NOT EXISTS enrichment.assets (
    asset_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id uuid NOT NULL REFERENCES parties.entities (entity_id) ON DELETE CASCADE,
    asset_type text CHECK (
        asset_type IN (
            'real_property',
            'bank_hint',
            'employment',
            'vehicle',
            'license',
            'ucc',
            'dba'
        )
    ),
    meta_json jsonb NOT NULL DEFAULT '{}'::jsonb,
    confidence numeric(5, 2) DEFAULT 0,
    source text,
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS enrichment.collectability (
    case_id uuid PRIMARY KEY REFERENCES judgments.cases (case_id) ON DELETE CASCADE,
    identity_score numeric(5, 2) DEFAULT 0,
    contactability_score numeric(5, 2) DEFAULT 0,
    asset_score numeric(5, 2) DEFAULT 0,
    recency_amount_score numeric(5, 2) DEFAULT 0,
    adverse_penalty numeric(5, 2) DEFAULT 0,
    total_score numeric(5, 2) GENERATED ALWAYS AS (
        greatest(
            0,
            identity_score * 0.30 + contactability_score * 0.25 + asset_score * 0.25 + recency_amount_score * 0.10 - adverse_penalty
        )
    ) STORED,
    tier text GENERATED ALWAYS AS (
        CASE
            WHEN greatest(
                0,
                identity_score * 0.30 + contactability_score * 0.25 + asset_score * 0.25 + recency_amount_score * 0.10 - adverse_penalty
            ) >= 80 THEN 'A'
            WHEN greatest(
                0,
                identity_score * 0.30 + contactability_score * 0.25 + asset_score * 0.25 + recency_amount_score * 0.10 - adverse_penalty
            ) >= 60 THEN 'B'
            WHEN greatest(
                0,
                identity_score * 0.30 + contactability_score * 0.25 + asset_score * 0.25 + recency_amount_score * 0.10 - adverse_penalty
            ) >= 40 THEN 'C'
            ELSE 'D'
        END
    ) STORED,
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_contacts_entity ON enrichment.contacts (entity_id);
CREATE INDEX IF NOT EXISTS idx_assets_entity ON enrichment.assets (entity_id);
-- ============================================================================
-- SECTION 8: CORE TABLES - outreach schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS outreach.cadences (
    cadence_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES judgments.cases (case_id) ON DELETE CASCADE,
    strategy text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    started_at timestamptz DEFAULT now(),
    completed_at timestamptz,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS outreach.attempts (
    attempt_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES judgments.cases (case_id) ON DELETE CASCADE,
    cadence_id uuid REFERENCES outreach.cadences (cadence_id) ON DELETE
    SET NULL,
        channel text NOT NULL,
        outcome text,
        notes text,
        attempted_at timestamptz DEFAULT now(),
        created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_attempts_case_time ON outreach.attempts (case_id, attempted_at);
-- ============================================================================
-- SECTION 9: CORE TABLES - intake schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS intake.esign (
    esign_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES judgments.cases (case_id) ON DELETE CASCADE,
    envelope_id text,
    status text NOT NULL DEFAULT 'pending',
    sent_at timestamptz,
    signed_at timestamptz,
    created_at timestamptz DEFAULT now()
);
-- ============================================================================
-- SECTION 10: CORE TABLES - enforcement schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS enforcement.actions (
    action_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES judgments.cases (case_id) ON DELETE CASCADE,
    action_type enforcement.action_type NOT NULL,
    filed_at date,
    status text,
    notes text,
    created_at timestamptz DEFAULT now()
);
-- ============================================================================
-- SECTION 11: CORE TABLES - finance schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS finance.trust_txns (
    txn_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid REFERENCES judgments.cases (case_id) ON DELETE CASCADE,
    amount numeric(14, 2) NOT NULL,
    txn_type text CHECK (txn_type IN ('credit', 'debit')),
    occurred_at timestamptz NOT NULL DEFAULT now(),
    reference text,
    memo text,
    created_at timestamptz DEFAULT now()
);
-- ============================================================================
-- SECTION 12: CORE TABLES - ops schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS ops.runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_name text NOT NULL,
    status text NOT NULL DEFAULT 'pending',
    started_at timestamptz DEFAULT now(),
    finished_at timestamptz,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE TABLE IF NOT EXISTS ops.ingest_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    filename text NOT NULL,
    row_count_raw integer NOT NULL DEFAULT 0,
    row_count_valid integer NOT NULL DEFAULT 0,
    row_count_invalid integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN ('pending', 'processing', 'completed', 'failed')
    ),
    error_summary text,
    stats jsonb DEFAULT '{}',
    started_at timestamptz,
    completed_at timestamptz,
    worker_id text,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    created_by text
);
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS stats jsonb;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS completed_at timestamptz;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS worker_id text;
CREATE INDEX IF NOT EXISTS idx_ingest_batches_status ON ops.ingest_batches(status)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_ingest_batches_created_at ON ops.ingest_batches(created_at DESC);
CREATE TABLE IF NOT EXISTS ops.intake_logs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id uuid NOT NULL REFERENCES ops.ingest_batches(id) ON DELETE CASCADE,
    row_index integer NOT NULL,
    status text NOT NULL CHECK (
        status IN ('success', 'error', 'skipped', 'duplicate')
    ),
    judgment_id uuid,
    error_code text,
    error_details text,
    processing_time_ms integer,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_intake_log_batch_row UNIQUE (batch_id, row_index)
);
CREATE INDEX IF NOT EXISTS idx_intake_logs_batch_id ON ops.intake_logs(batch_id);
CREATE INDEX IF NOT EXISTS idx_intake_logs_batch_status ON ops.intake_logs(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_intake_logs_status_created ON ops.intake_logs(status, created_at DESC)
WHERE status = 'error';
-- ============================================================================
-- SECTION 13: CORE TABLES - ingestion schema
-- ============================================================================
CREATE TABLE IF NOT EXISTS ingestion.runs (
    run_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    event text NOT NULL,
    ref_id uuid,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE ingestion.runs
ADD COLUMN IF NOT EXISTS event text;
ALTER TABLE ingestion.runs
ADD COLUMN IF NOT EXISTS ref_id uuid;
ALTER TABLE ingestion.runs
ADD COLUMN IF NOT EXISTS payload jsonb;
-- ============================================================================
-- SECTION 14: CORE TABLES - intelligence schema (graph)
-- ============================================================================
CREATE TABLE IF NOT EXISTS intelligence.entities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    type intelligence.entity_type NOT NULL,
    raw_name text NOT NULL,
    normalized_name text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_entities_normalized_name_type UNIQUE (normalized_name, type)
);
CREATE INDEX IF NOT EXISTS idx_entities_normalized_name ON intelligence.entities(normalized_name);
CREATE INDEX IF NOT EXISTS idx_entities_type ON intelligence.entities(type);
-- intelligence.relationships (only if public.judgments exists for FK)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
) THEN CREATE TABLE IF NOT EXISTS intelligence.relationships (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id uuid NOT NULL REFERENCES intelligence.entities(id) ON DELETE CASCADE,
    target_entity_id uuid NOT NULL REFERENCES intelligence.entities(id) ON DELETE CASCADE,
    relation intelligence.relation_type NOT NULL,
    source_judgment_id bigint REFERENCES public.judgments(id) ON DELETE CASCADE,
    confidence real NOT NULL DEFAULT 1.0,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_relationships_source_entity ON intelligence.relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target_entity ON intelligence.relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_source_judgment ON intelligence.relationships(source_judgment_id);
CREATE INDEX IF NOT EXISTS idx_relationships_relation ON intelligence.relationships(relation);
END IF;
END $$;
-- ============================================================================
-- SECTION 15: CORE TABLES - public schema
-- ============================================================================
-- public.judgments (primary dashboard table)
CREATE TABLE IF NOT EXISTS public.judgments (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    created_at timestamptz DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    case_number text,
    plaintiff_name text,
    defendant_name text,
    judgment_amount numeric(10, 2),
    entry_date date,
    source_file text,
    plaintiff_id uuid,
    enforcement_stage text NOT NULL DEFAULT 'pre_enforcement',
    enforcement_stage_updated_at timestamptz NOT NULL DEFAULT now(),
    collectability_score numeric(5, 2),
    court text,
    county text,
    judgment_date date,
    status text,
    CONSTRAINT unique_case_number UNIQUE (case_number)
);
-- Add missing columns
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS updated_at timestamptz;
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS plaintiff_id uuid;
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS enforcement_stage text;
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS enforcement_stage_updated_at timestamptz;
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS collectability_score numeric(5, 2);
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS court text;
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS county text;
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS judgment_date date;
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS status text;
-- Set defaults for columns that need them
DO $$ BEGIN
UPDATE public.judgments
SET updated_at = now()
WHERE updated_at IS NULL;
UPDATE public.judgments
SET enforcement_stage = 'pre_enforcement'
WHERE enforcement_stage IS NULL;
UPDATE public.judgments
SET enforcement_stage_updated_at = now()
WHERE enforcement_stage_updated_at IS NULL;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Trigger for updated_at
DROP TRIGGER IF EXISTS trg_public_judgments_touch ON public.judgments;
CREATE TRIGGER trg_public_judgments_touch BEFORE
UPDATE ON public.judgments FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
CREATE INDEX IF NOT EXISTS idx_defendant_name ON public.judgments (defendant_name);
CREATE INDEX IF NOT EXISTS idx_public_judgments_plaintiff_id ON public.judgments (plaintiff_id);
CREATE INDEX IF NOT EXISTS idx_judgments_collectability_score ON public.judgments(collectability_score DESC NULLS LAST);
-- public.plaintiffs
CREATE TABLE IF NOT EXISTS public.plaintiffs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    name text NOT NULL,
    name_normalized text GENERATED ALWAYS AS (
        regexp_replace(lower(trim(name)), '\s+', ' ', 'g')
    ) STORED,
    short_name text,
    firm_name text,
    status text,
    notes text,
    source_system text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS firm_name text;
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS source_system text;
-- Unique constraint on name_normalized (idempotent)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'plaintiffs_name_normalized_key'
) THEN
ALTER TABLE public.plaintiffs
ADD CONSTRAINT plaintiffs_name_normalized_key UNIQUE (name_normalized);
END IF;
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
DROP TRIGGER IF EXISTS trg_plaintiffs_touch ON public.plaintiffs;
CREATE TRIGGER trg_plaintiffs_touch BEFORE
UPDATE ON public.plaintiffs FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
-- public.plaintiff_contacts
CREATE TABLE IF NOT EXISTS public.plaintiff_contacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs (id) ON DELETE CASCADE,
    contact_type text NOT NULL CHECK (
        contact_type IN ('email', 'phone', 'address', 'website', 'other')
    ),
    contact_value text NOT NULL,
    label text,
    is_primary boolean NOT NULL DEFAULT false,
    notes text,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
DROP TRIGGER IF EXISTS trg_plaintiff_contacts_touch ON public.plaintiff_contacts;
CREATE TRIGGER trg_plaintiff_contacts_touch BEFORE
UPDATE ON public.plaintiff_contacts FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
CREATE UNIQUE INDEX IF NOT EXISTS plaintiff_contacts_unique_value ON public.plaintiff_contacts (plaintiff_id, contact_type, contact_value);
CREATE UNIQUE INDEX IF NOT EXISTS plaintiff_contacts_primary_per_type ON public.plaintiff_contacts (plaintiff_id, contact_type)
WHERE is_primary;
-- public.plaintiff_status_history
CREATE TABLE IF NOT EXISTS public.plaintiff_status_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs (id) ON DELETE CASCADE,
    status text NOT NULL,
    reason text,
    note text,
    recorded_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    changed_at timestamptz,
    recorded_by text,
    changed_by text
);
ALTER TABLE public.plaintiff_status_history
ADD COLUMN IF NOT EXISTS note text;
ALTER TABLE public.plaintiff_status_history
ADD COLUMN IF NOT EXISTS changed_at timestamptz;
ALTER TABLE public.plaintiff_status_history
ADD COLUMN IF NOT EXISTS changed_by text;
-- public.import_runs
CREATE TABLE IF NOT EXISTS public.import_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_kind text NOT NULL,
    source_system text NOT NULL,
    source_reference text,
    file_name text,
    storage_path text,
    status text NOT NULL DEFAULT 'pending',
    total_rows integer CHECK (
        total_rows IS NULL
        OR total_rows >= 0
    ),
    inserted_rows integer CHECK (
        inserted_rows IS NULL
        OR inserted_rows >= 0
    ),
    skipped_rows integer CHECK (
        skipped_rows IS NULL
        OR skipped_rows >= 0
    ),
    error_rows integer CHECK (
        error_rows IS NULL
        OR error_rows >= 0
    ),
    started_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    finished_at timestamptz,
    created_by text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX IF NOT EXISTS idx_import_runs_started_at ON public.import_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_import_runs_status ON public.import_runs (status);
-- public.outreach_log
CREATE TABLE IF NOT EXISTS public.outreach_log (
    id bigserial PRIMARY KEY,
    case_number text NOT NULL,
    channel text NOT NULL DEFAULT 'stub',
    template text NOT NULL DEFAULT 'welcome_v0',
    status text NOT NULL DEFAULT 'pending_provider',
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    metadata jsonb
);
CREATE INDEX IF NOT EXISTS outreach_log_case_number_idx ON public.outreach_log (case_number);
-- public.plaintiff_call_attempts
CREATE TABLE IF NOT EXISTS public.plaintiff_call_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid,
    task_id uuid,
    outcome text,
    interest_level text,
    notes text,
    next_follow_up_at timestamptz,
    attempted_at timestamptz DEFAULT timezone('utc', now()),
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
-- public.plaintiff_tasks
CREATE TABLE IF NOT EXISTS public.plaintiff_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid REFERENCES public.plaintiffs(id) ON DELETE CASCADE,
    task_type text NOT NULL,
    priority integer DEFAULT 0,
    status text NOT NULL DEFAULT 'pending',
    scheduled_at timestamptz,
    due_at timestamptz,
    completed_at timestamptz,
    closed_at timestamptz,
    result text,
    assignee text,
    metadata jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS closed_at timestamptz;
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS result text;
-- ============================================================================
-- SECTION 16: CORE VIEWS - judgments schema
-- ============================================================================
-- judgments.v_collectability_snapshot (base view)
CREATE OR REPLACE VIEW judgments.v_collectability_snapshot AS WITH latest_enrichment AS (
        SELECT er.case_id,
            er.created_at,
            er.status,
            row_number() OVER (
                PARTITION BY er.case_id
                ORDER BY er.created_at DESC,
                    er.id DESC
            ) AS row_num
        FROM judgments.enrichment_runs er
    )
SELECT c.case_id,
    c.case_number,
    c.amount_awarded AS judgment_amount,
    c.judgment_date,
    CASE
        WHEN c.judgment_date IS NOT NULL THEN (current_date - c.judgment_date)
    END AS age_days,
    le.created_at AS last_enriched_at,
    le.status AS last_enrichment_status,
    CASE
        WHEN COALESCE(c.amount_awarded, 0) >= 3000
        AND c.judgment_date IS NOT NULL
        AND (current_date - c.judgment_date) <= 365 THEN 'A'
        WHEN (
            COALESCE(c.amount_awarded, 0) BETWEEN 1000 AND 2999
        )
        OR (
            c.judgment_date IS NOT NULL
            AND (current_date - c.judgment_date) BETWEEN 366 AND 1095
        ) THEN 'B'
        ELSE 'C'
    END AS collectability_tier
FROM judgments.cases c
    LEFT JOIN latest_enrichment le ON c.case_id = le.case_id
    AND le.row_num = 1;
-- judgments.v_case_balance
CREATE OR REPLACE VIEW judgments.v_case_balance AS
SELECT c.case_id,
    c.index_no,
    c.court,
    c.county,
    c.status,
    c.principal_amt,
    c.costs,
    CASE
        WHEN COALESCE(
            c.interest_from,
            c.judgment_at,
            c.filed_at,
            c.created_at::date
        ) IS NOT NULL THEN (
            COALESCE(c.principal_amt, 0) * COALESCE(c.interest_rate, 0) * greatest(
                0,
                (
                    now()::date - COALESCE(
                        c.interest_from,
                        c.judgment_at,
                        c.filed_at,
                        c.created_at::date
                    )
                )::integer
            ) / 365.0
        )::numeric(14, 2)
        ELSE 0::numeric(14, 2)
    END AS interest_accrued,
    CASE
        WHEN COALESCE(
            c.interest_from,
            c.judgment_at,
            c.filed_at,
            c.created_at::date
        ) IS NOT NULL THEN (
            COALESCE(c.principal_amt, 0) + COALESCE(c.costs, 0) + (
                COALESCE(c.principal_amt, 0) * COALESCE(c.interest_rate, 0) * greatest(
                    0,
                    (
                        now()::date - COALESCE(
                            c.interest_from,
                            c.judgment_at,
                            c.filed_at,
                            c.created_at::date
                        )
                    )::integer
                ) / 365.0
            )
        )::numeric(14, 2)
        ELSE (
            COALESCE(c.principal_amt, 0) + COALESCE(c.costs, 0)
        )::numeric(14, 2)
    END AS balance_today,
    co.total_score,
    co.tier
FROM judgments.cases c
    LEFT JOIN enrichment.collectability co ON c.case_id = co.case_id;
-- ============================================================================
-- SECTION 17: CORE VIEWS - public schema (dashboard-critical)
-- ============================================================================
-- public.v_collectability_snapshot (wrapper for dashboard)
CREATE OR REPLACE VIEW public.v_collectability_snapshot AS
SELECT *
FROM judgments.v_collectability_snapshot;
-- public.v_plaintiffs_overview
CREATE OR REPLACE VIEW public.v_plaintiffs_overview AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount,
    COUNT(DISTINCT j.id) AS case_count
FROM public.plaintiffs p
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
GROUP BY p.id,
    p.name,
    p.firm_name,
    p.status;
-- public.v_enforcement_overview
CREATE OR REPLACE VIEW public.v_enforcement_overview AS
SELECT j.enforcement_stage,
    cs.collectability_tier,
    COUNT(*) AS case_count,
    COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount
FROM public.judgments j
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
GROUP BY j.enforcement_stage,
    cs.collectability_tier;
-- public.v_enforcement_recent
CREATE OR REPLACE VIEW public.v_enforcement_recent AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id::text AS plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
ORDER BY j.enforcement_stage_updated_at DESC,
    j.id DESC;
-- public.v_judgment_pipeline
CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id::text AS plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier,
    cs.age_days AS collectability_age_days,
    cs.last_enriched_at,
    cs.last_enrichment_status
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number;
-- public.v_plaintiff_call_queue
CREATE OR REPLACE VIEW public.v_plaintiff_call_queue AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    status_info.last_contacted_at,
    p.created_at,
    COALESCE(ov.total_judgment_amount, 0::numeric) AS total_judgment_amount,
    COALESCE(ov.case_count, 0) AS case_count
FROM public.plaintiffs p
    LEFT JOIN public.v_plaintiffs_overview ov ON p.id = ov.plaintiff_id
    LEFT JOIN LATERAL (
        SELECT MAX(psh.changed_at) AS last_contacted_at
        FROM public.plaintiff_status_history psh
        WHERE psh.plaintiff_id = p.id
            AND psh.status IN (
                'contacted',
                'qualified',
                'sent_agreement',
                'signed'
            )
    ) status_info ON true
WHERE p.status IN ('new', 'contacted', 'qualified')
ORDER BY COALESCE(ov.total_judgment_amount, 0::numeric) DESC,
    COALESCE(status_info.last_contacted_at, p.created_at) ASC;
-- ============================================================================
-- SECTION 18: CORE VIEWS - ops schema
-- ============================================================================
-- ops.v_intake_monitor
CREATE OR REPLACE VIEW ops.v_intake_monitor AS WITH batch_stats AS (
        SELECT b.id,
            b.filename,
            b.source,
            b.status,
            b.row_count_raw AS total_rows,
            b.row_count_valid AS valid_rows,
            b.row_count_invalid AS error_rows,
            b.stats,
            b.created_at,
            b.started_at,
            b.completed_at,
            b.created_by,
            b.worker_id,
            CASE
                WHEN b.row_count_raw > 0 THEN ROUND(
                    (b.row_count_valid::numeric / b.row_count_raw) * 100,
                    1
                )
                ELSE 0
            END AS success_rate,
            CASE
                WHEN b.completed_at IS NOT NULL
                AND b.started_at IS NOT NULL THEN EXTRACT(
                    EPOCH
                    FROM (b.completed_at - b.started_at)
                )::integer
                ELSE NULL
            END AS duration_seconds
        FROM ops.ingest_batches b
    ),
    error_preview AS (
        SELECT batch_id,
            jsonb_agg(
                jsonb_build_object(
                    'row',
                    row_index,
                    'code',
                    error_code,
                    'message',
                    LEFT(error_details, 100)
                )
                ORDER BY row_index
            ) FILTER (
                WHERE status = 'error'
            ) AS recent_errors
        FROM (
                SELECT batch_id,
                    row_index,
                    error_code,
                    error_details,
                    status
                FROM ops.intake_logs
                WHERE status = 'error'
                ORDER BY created_at DESC
                LIMIT 5
            ) sub
        GROUP BY batch_id
    )
SELECT bs.id,
    bs.filename,
    bs.source,
    bs.status,
    bs.total_rows,
    bs.valid_rows,
    bs.error_rows,
    bs.success_rate,
    bs.duration_seconds,
    bs.created_at,
    bs.started_at,
    bs.completed_at,
    bs.created_by,
    bs.worker_id,
    bs.stats,
    COALESCE(ep.recent_errors, '[]'::jsonb) AS recent_errors,
    CASE
        WHEN bs.status = 'failed' THEN 'critical'
        WHEN bs.error_rows > 0
        AND bs.success_rate < 90 THEN 'warning'
        WHEN bs.status = 'completed' THEN 'healthy'
        WHEN bs.status = 'processing' THEN 'running'
        ELSE 'pending'
    END AS health_status
FROM batch_stats bs
    LEFT JOIN error_preview ep ON bs.id = ep.batch_id
ORDER BY bs.created_at DESC;
-- ============================================================================
-- SECTION 19: CORE VIEWS - enforcement schema
-- ============================================================================
-- enforcement.v_radar
CREATE OR REPLACE VIEW enforcement.v_radar AS
SELECT j.id,
    j.case_number,
    j.plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.court,
    j.county,
    COALESCE(j.judgment_date, j.entry_date) AS judgment_date,
    j.collectability_score,
    j.status,
    j.enforcement_stage,
    CASE
        WHEN j.collectability_score >= 70
        AND j.judgment_amount >= 10000 THEN 'BUY_CANDIDATE'
        WHEN j.collectability_score >= 40 THEN 'CONTINGENCY'
        WHEN j.collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy,
    j.created_at,
    j.updated_at
FROM public.judgments j
WHERE COALESCE(j.status, '') NOT IN ('SATISFIED', 'EXPIRED')
ORDER BY j.collectability_score DESC NULLS LAST,
    j.judgment_amount DESC;
-- ============================================================================
-- SECTION 20: CORE VIEWS - intelligence schema
-- ============================================================================
CREATE OR REPLACE VIEW intelligence.v_entity_summary AS
SELECT e.id,
    e.type,
    e.raw_name,
    e.normalized_name,
    e.metadata,
    e.created_at,
    (
        SELECT COUNT(*)
        FROM intelligence.relationships r
        WHERE r.source_entity_id = e.id
    ) AS outgoing_relationships,
    (
        SELECT COUNT(*)
        FROM intelligence.relationships r
        WHERE r.target_entity_id = e.id
    ) AS incoming_relationships
FROM intelligence.entities e
ORDER BY e.created_at DESC;
-- ============================================================================
-- SECTION 21: ROW LEVEL SECURITY
-- ============================================================================
-- Enable RLS on all core tables
ALTER TABLE judgments.cases ENABLE ROW LEVEL SECURITY;
ALTER TABLE judgments.enrichment_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE parties.entities ENABLE ROW LEVEL SECURITY;
ALTER TABLE parties.roles ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrichment.contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrichment.assets ENABLE ROW LEVEL SECURITY;
ALTER TABLE enrichment.collectability ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach.cadences ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach.attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE intake.esign ENABLE ROW LEVEL SECURITY;
ALTER TABLE enforcement.actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE finance.trust_txns ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.ingest_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.intake_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.judgments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaintiffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaintiff_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaintiff_status_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.import_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.outreach_log ENABLE ROW LEVEL SECURITY;
-- ============================================================================
-- SECTION 22: RLS POLICIES (idempotent)
-- ============================================================================
-- Helper macro for policy creation
DO $$
DECLARE tbl RECORD;
BEGIN -- public.judgments policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'judgments'
        AND policyname = 'judgments_select_all'
) THEN CREATE POLICY judgments_select_all ON public.judgments FOR
SELECT USING (true);
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'judgments'
        AND policyname = 'judgments_insert_service'
) THEN CREATE POLICY judgments_insert_service ON public.judgments FOR
INSERT WITH CHECK (auth.role() = 'service_role');
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'judgments'
        AND policyname = 'judgments_update_service'
) THEN CREATE POLICY judgments_update_service ON public.judgments FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
-- public.plaintiffs policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'plaintiffs'
        AND policyname = 'plaintiffs_select_public'
) THEN CREATE POLICY plaintiffs_select_public ON public.plaintiffs FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'plaintiffs'
        AND policyname = 'plaintiffs_insert_service'
) THEN CREATE POLICY plaintiffs_insert_service ON public.plaintiffs FOR
INSERT WITH CHECK (auth.role() = 'service_role');
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'plaintiffs'
        AND policyname = 'plaintiffs_update_service'
) THEN CREATE POLICY plaintiffs_update_service ON public.plaintiffs FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
-- public.plaintiff_contacts policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'plaintiff_contacts'
        AND policyname = 'plaintiff_contacts_select_public'
) THEN CREATE POLICY plaintiff_contacts_select_public ON public.plaintiff_contacts FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'plaintiff_contacts'
        AND policyname = 'plaintiff_contacts_insert_service'
) THEN CREATE POLICY plaintiff_contacts_insert_service ON public.plaintiff_contacts FOR
INSERT WITH CHECK (auth.role() = 'service_role');
END IF;
-- public.plaintiff_status_history policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'plaintiff_status_history'
        AND policyname = 'plaintiff_status_select_public'
) THEN CREATE POLICY plaintiff_status_select_public ON public.plaintiff_status_history FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'plaintiff_status_history'
        AND policyname = 'plaintiff_status_insert_service'
) THEN CREATE POLICY plaintiff_status_insert_service ON public.plaintiff_status_history FOR
INSERT WITH CHECK (auth.role() = 'service_role');
END IF;
-- public.import_runs policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'import_runs'
        AND policyname = 'import_runs_service_rw'
) THEN CREATE POLICY import_runs_service_rw ON public.import_runs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
-- ops.ingest_batches policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'ops'
        AND tablename = 'ingest_batches'
        AND policyname = 'ingest_batches_service_rw'
) THEN CREATE POLICY ingest_batches_service_rw ON ops.ingest_batches FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
-- ops.intake_logs policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'ops'
        AND tablename = 'intake_logs'
        AND policyname = 'intake_logs_service_rw'
) THEN CREATE POLICY intake_logs_service_rw ON ops.intake_logs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
-- judgments.enrichment_runs policies
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'judgments'
        AND tablename = 'enrichment_runs'
        AND policyname = 'service_enrichment_runs_rw'
) THEN CREATE POLICY service_enrichment_runs_rw ON judgments.enrichment_runs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
END $$;
-- ============================================================================
-- SECTION 23: GRANTS
-- ============================================================================
-- Schema usage grants
GRANT USAGE ON SCHEMA public TO anon,
    authenticated,
    service_role;
GRANT USAGE ON SCHEMA judgments TO anon,
    authenticated,
    service_role;
GRANT USAGE ON SCHEMA parties TO anon,
    authenticated,
    service_role;
GRANT USAGE ON SCHEMA enrichment TO service_role;
GRANT USAGE ON SCHEMA outreach TO service_role;
GRANT USAGE ON SCHEMA intake TO service_role;
GRANT USAGE ON SCHEMA enforcement TO authenticated,
    service_role;
GRANT USAGE ON SCHEMA ops TO authenticated,
    service_role;
GRANT USAGE ON SCHEMA finance TO service_role;
GRANT USAGE ON SCHEMA ingestion TO service_role;
GRANT USAGE ON SCHEMA intelligence TO service_role;
-- public.judgments grants
GRANT SELECT ON public.judgments TO anon,
    authenticated;
GRANT SELECT,
    INSERT,
    UPDATE ON public.judgments TO service_role;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_sequences
    WHERE schemaname = 'public'
        AND sequencename = 'judgments_id_seq'
) THEN
GRANT USAGE,
    SELECT ON SEQUENCE public.judgments_id_seq TO anon,
    authenticated,
    service_role;
END IF;
END $$;
-- public.plaintiffs grants
GRANT SELECT ON public.plaintiffs TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE,
    DELETE ON public.plaintiffs TO service_role;
-- public.plaintiff_contacts grants
GRANT SELECT ON public.plaintiff_contacts TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE,
    DELETE ON public.plaintiff_contacts TO service_role;
-- public.plaintiff_status_history grants
GRANT SELECT ON public.plaintiff_status_history TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE,
    DELETE ON public.plaintiff_status_history TO service_role;
-- public.import_runs grants
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.import_runs TO service_role;
-- View grants
GRANT SELECT ON public.v_collectability_snapshot TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_plaintiffs_overview TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_enforcement_overview TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_enforcement_recent TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated,
    service_role;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
    authenticated,
    service_role;
GRANT SELECT ON judgments.v_collectability_snapshot TO service_role;
GRANT SELECT ON judgments.v_case_balance TO service_role;
GRANT SELECT ON ops.v_intake_monitor TO authenticated,
    service_role;
GRANT SELECT ON enforcement.v_radar TO authenticated,
    service_role;
GRANT SELECT ON intelligence.v_entity_summary TO service_role;
-- judgments schema table grants
GRANT SELECT,
    INSERT,
    UPDATE ON judgments.cases TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON judgments.enrichment_runs TO service_role;
-- parties schema grants
GRANT SELECT ON parties.entities TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE ON parties.entities TO service_role;
GRANT SELECT ON parties.roles TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE ON parties.roles TO service_role;
-- enrichment schema grants
GRANT SELECT,
    INSERT,
    UPDATE ON enrichment.contacts TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON enrichment.assets TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON enrichment.collectability TO service_role;
-- ops schema grants
GRANT SELECT,
    INSERT,
    UPDATE ON ops.runs TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON ops.ingest_batches TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON ops.intake_logs TO service_role;
-- intelligence schema grants
GRANT ALL ON intelligence.entities TO service_role;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'intelligence'
        AND table_name = 'relationships'
) THEN
GRANT ALL ON intelligence.relationships TO service_role;
END IF;
END $$;
-- ingestion schema grants
GRANT SELECT ON ingestion.runs TO service_role;
-- ============================================================================
-- SECTION 24: SANITY CHECKS (non-blocking)
-- ============================================================================
-- These SELECT statements confirm object existence without raising errors.
SELECT 'schema_judgments_exists' AS check,
    to_regnamespace('judgments') IS NOT NULL AS ok;
SELECT 'schema_parties_exists' AS check,
    to_regnamespace('parties') IS NOT NULL AS ok;
SELECT 'schema_enrichment_exists' AS check,
    to_regnamespace('enrichment') IS NOT NULL AS ok;
SELECT 'schema_outreach_exists' AS check,
    to_regnamespace('outreach') IS NOT NULL AS ok;
SELECT 'schema_intake_exists' AS check,
    to_regnamespace('intake') IS NOT NULL AS ok;
SELECT 'schema_enforcement_exists' AS check,
    to_regnamespace('enforcement') IS NOT NULL AS ok;
SELECT 'schema_ops_exists' AS check,
    to_regnamespace('ops') IS NOT NULL AS ok;
SELECT 'schema_finance_exists' AS check,
    to_regnamespace('finance') IS NOT NULL AS ok;
SELECT 'schema_intelligence_exists' AS check,
    to_regnamespace('intelligence') IS NOT NULL AS ok;
SELECT 'judgments.cases_exists' AS check,
    to_regclass('judgments.cases') IS NOT NULL AS ok;
SELECT 'judgments.enrichment_runs_exists' AS check,
    to_regclass('judgments.enrichment_runs') IS NOT NULL AS ok;
SELECT 'parties.entities_exists' AS check,
    to_regclass('parties.entities') IS NOT NULL AS ok;
SELECT 'parties.roles_exists' AS check,
    to_regclass('parties.roles') IS NOT NULL AS ok;
SELECT 'enrichment.contacts_exists' AS check,
    to_regclass('enrichment.contacts') IS NOT NULL AS ok;
SELECT 'enrichment.assets_exists' AS check,
    to_regclass('enrichment.assets') IS NOT NULL AS ok;
SELECT 'enrichment.collectability_exists' AS check,
    to_regclass('enrichment.collectability') IS NOT NULL AS ok;
SELECT 'outreach.cadences_exists' AS check,
    to_regclass('outreach.cadences') IS NOT NULL AS ok;
SELECT 'outreach.attempts_exists' AS check,
    to_regclass('outreach.attempts') IS NOT NULL AS ok;
SELECT 'intake.esign_exists' AS check,
    to_regclass('intake.esign') IS NOT NULL AS ok;
SELECT 'enforcement.actions_exists' AS check,
    to_regclass('enforcement.actions') IS NOT NULL AS ok;
SELECT 'finance.trust_txns_exists' AS check,
    to_regclass('finance.trust_txns') IS NOT NULL AS ok;
SELECT 'ops.runs_exists' AS check,
    to_regclass('ops.runs') IS NOT NULL AS ok;
SELECT 'ops.ingest_batches_exists' AS check,
    to_regclass('ops.ingest_batches') IS NOT NULL AS ok;
SELECT 'ops.intake_logs_exists' AS check,
    to_regclass('ops.intake_logs') IS NOT NULL AS ok;
SELECT 'intelligence.entities_exists' AS check,
    to_regclass('intelligence.entities') IS NOT NULL AS ok;
SELECT 'public.judgments_exists' AS check,
    to_regclass('public.judgments') IS NOT NULL AS ok;
SELECT 'public.plaintiffs_exists' AS check,
    to_regclass('public.plaintiffs') IS NOT NULL AS ok;
SELECT 'public.plaintiff_contacts_exists' AS check,
    to_regclass('public.plaintiff_contacts') IS NOT NULL AS ok;
SELECT 'public.plaintiff_status_history_exists' AS check,
    to_regclass('public.plaintiff_status_history') IS NOT NULL AS ok;
SELECT 'public.import_runs_exists' AS check,
    to_regclass('public.import_runs') IS NOT NULL AS ok;
SELECT 'v_collectability_snapshot_exists' AS check,
    to_regclass('public.v_collectability_snapshot') IS NOT NULL AS ok;
SELECT 'v_plaintiffs_overview_exists' AS check,
    to_regclass('public.v_plaintiffs_overview') IS NOT NULL AS ok;
SELECT 'v_enforcement_overview_exists' AS check,
    to_regclass('public.v_enforcement_overview') IS NOT NULL AS ok;
SELECT 'v_enforcement_recent_exists' AS check,
    to_regclass('public.v_enforcement_recent') IS NOT NULL AS ok;
SELECT 'v_judgment_pipeline_exists' AS check,
    to_regclass('public.v_judgment_pipeline') IS NOT NULL AS ok;
SELECT 'v_plaintiff_call_queue_exists' AS check,
    to_regclass('public.v_plaintiff_call_queue') IS NOT NULL AS ok;
SELECT 'ops.v_intake_monitor_exists' AS check,
    to_regclass('ops.v_intake_monitor') IS NOT NULL AS ok;
SELECT 'enforcement.v_radar_exists' AS check,
    to_regclass('enforcement.v_radar') IS NOT NULL AS ok;
-- Notify PostgREST to reload schema
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
