-- =============================================================================
-- Golden Path Orchestration Schema
-- =============================================================================
-- Strategic pivot: Native orchestration replacing n8n.
-- This migration defines the core entities and extends the job queue for
-- the Golden Path workflow: Import → Entity Resolve → Judgment Create → Enrich
--
-- NOTE: This is an additive migration. Existing plaintiffs/judgments tables
-- in public schema are already defined. This migration:
--   1. Adds enforcement schema versions for clarity (if not exists)
--   2. Extends ops.job_type_enum with orchestration job types
--   3. Adds batch orchestration tracking
--
-- Apply via: scripts/db_push.ps1 -SupabaseEnv dev
-- =============================================================================
-- migrate:up
-- =============================================================================
-- PART 1: ENFORCEMENT SCHEMA (idempotent creation)
-- =============================================================================
-- Ensure enforcement schema exists
CREATE SCHEMA IF NOT EXISTS enforcement;
-- enforcement.plaintiffs - Links to public.plaintiffs but adds enforcement context
-- This is a reference/linking table if needed; primary data stays in public.plaintiffs
CREATE TABLE IF NOT EXISTS enforcement.plaintiff_enforcement (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id UUID NOT NULL REFERENCES public.plaintiffs(id) ON DELETE CASCADE,
    tier TEXT NOT NULL DEFAULT 'standard' CHECK (
        tier IN ('priority', 'standard', 'passive', 'dormant')
    ),
    score NUMERIC(5, 2),
    last_action_at TIMESTAMPTZ,
    next_action_due TIMESTAMPTZ,
    strategy JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_plaintiff_enforcement UNIQUE (plaintiff_id)
);
COMMENT ON TABLE enforcement.plaintiff_enforcement IS 'Enforcement context for plaintiffs - ties public.plaintiffs to enforcement strategy';
-- enforcement.judgment_enforcement - Links to public.judgments with enforcement context
CREATE TABLE IF NOT EXISTS enforcement.judgment_enforcement (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id BIGINT NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    plaintiff_enforcement_id UUID REFERENCES enforcement.plaintiff_enforcement(id),
    status TEXT NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'active',
            'served',
            'collecting',
            'satisfied',
            'uncollectible'
        )
    ),
    defendant_enriched BOOLEAN NOT NULL DEFAULT FALSE,
    enrichment_data JSONB,
    priority_score NUMERIC(5, 2),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_judgment_enforcement UNIQUE (judgment_id)
);
COMMENT ON TABLE enforcement.judgment_enforcement IS 'Enforcement context for judgments - tracks enforcement status and enrichment';
-- Indexes for enforcement tables
CREATE INDEX IF NOT EXISTS idx_plaintiff_enforcement_tier ON enforcement.plaintiff_enforcement(tier);
CREATE INDEX IF NOT EXISTS idx_plaintiff_enforcement_next_action ON enforcement.plaintiff_enforcement(next_action_due)
WHERE next_action_due IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_judgment_enforcement_status ON enforcement.judgment_enforcement(status);
CREATE INDEX IF NOT EXISTS idx_judgment_enforcement_plaintiff ON enforcement.judgment_enforcement(plaintiff_enforcement_id);
-- =============================================================================
-- PART 2: EXTEND JOB TYPE ENUM FOR GOLDEN PATH
-- =============================================================================
-- Add new job types for Golden Path orchestration
-- These are idempotent (ADD VALUE IF NOT EXISTS requires PG 9.3+, we use DO block)
DO $$ BEGIN -- entity_resolve: Maps raw intake rows to normalized plaintiffs/defendants
IF NOT EXISTS (
    SELECT 1
    FROM pg_enum
    WHERE enumtypid = 'ops.job_type_enum'::regtype
        AND enumlabel = 'entity_resolve'
) THEN ALTER TYPE ops.job_type_enum
ADD VALUE 'entity_resolve';
END IF;
END $$;
DO $$ BEGIN -- create_judgment: Creates judgment records from resolved entities
IF NOT EXISTS (
    SELECT 1
    FROM pg_enum
    WHERE enumtypid = 'ops.job_type_enum'::regtype
        AND enumlabel = 'create_judgment'
) THEN ALTER TYPE ops.job_type_enum
ADD VALUE 'create_judgment';
END IF;
END $$;
DO $$ BEGIN -- enrich_defendant: External API enrichment for defendant data
IF NOT EXISTS (
    SELECT 1
    FROM pg_enum
    WHERE enumtypid = 'ops.job_type_enum'::regtype
        AND enumlabel = 'enrich_defendant'
) THEN ALTER TYPE ops.job_type_enum
ADD VALUE 'enrich_defendant';
END IF;
END $$;
DO $$ BEGIN -- orchestrator_tick: Heartbeat job for the orchestrator to check batch progress
IF NOT EXISTS (
    SELECT 1
    FROM pg_enum
    WHERE enumtypid = 'ops.job_type_enum'::regtype
        AND enumlabel = 'orchestrator_tick'
) THEN ALTER TYPE ops.job_type_enum
ADD VALUE 'orchestrator_tick';
END IF;
END $$;
COMMENT ON TYPE ops.job_type_enum IS 'Job types: enrich_tlo, enrich_idicore, generate_pdf, ingest_csv, enforcement_strategy, enforcement_drafting, entity_resolve, create_judgment, enrich_defendant, orchestrator_tick';
-- =============================================================================
-- PART 3: BATCH ORCHESTRATION TRACKING
-- =============================================================================
-- Track batch progress through the Golden Path pipeline
CREATE TABLE IF NOT EXISTS ops.batch_orchestration (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    batch_id UUID NOT NULL REFERENCES ops.import_batches(id) ON DELETE CASCADE,
    stage TEXT NOT NULL DEFAULT 'validated' CHECK (
        stage IN (
            'validated',
            -- Batch completed validation, ready for orchestration
            'entity_resolving',
            -- Entity resolution jobs enqueued
            'entity_resolved',
            -- All entity resolution complete
            'judgment_creating',
            -- Judgment creation jobs enqueued
            'judgment_created',
            -- All judgments created
            'enriching',
            -- Enrichment jobs enqueued
            'enriched',
            -- All enrichment complete
            'complete',
            -- Full pipeline complete
            'failed' -- Pipeline failed
        )
    ),
    jobs_total INT NOT NULL DEFAULT 0,
    jobs_completed INT NOT NULL DEFAULT 0,
    jobs_failed INT NOT NULL DEFAULT 0,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_batch_orchestration UNIQUE (batch_id)
);
COMMENT ON TABLE ops.batch_orchestration IS 'Tracks batch progress through Golden Path pipeline stages';
CREATE INDEX IF NOT EXISTS idx_batch_orchestration_stage ON ops.batch_orchestration(stage);
CREATE INDEX IF NOT EXISTS idx_batch_orchestration_pending ON ops.batch_orchestration(stage, created_at)
WHERE stage NOT IN ('complete', 'failed');
-- Trigger to update updated_at
CREATE OR REPLACE FUNCTION ops.touch_batch_orchestration_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_batch_orchestration_updated_at ON ops.batch_orchestration;
CREATE TRIGGER trg_batch_orchestration_updated_at BEFORE
UPDATE ON ops.batch_orchestration FOR EACH ROW EXECUTE FUNCTION ops.touch_batch_orchestration_updated_at();
-- =============================================================================
-- PART 4: RLS POLICIES
-- =============================================================================
-- enforcement.plaintiff_enforcement
ALTER TABLE enforcement.plaintiff_enforcement ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service Role Full Access" ON enforcement.plaintiff_enforcement;
CREATE POLICY "Service Role Full Access" ON enforcement.plaintiff_enforcement FOR ALL TO service_role USING (true) WITH CHECK (true);
-- enforcement.judgment_enforcement  
ALTER TABLE enforcement.judgment_enforcement ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service Role Full Access" ON enforcement.judgment_enforcement;
CREATE POLICY "Service Role Full Access" ON enforcement.judgment_enforcement FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ops.batch_orchestration
ALTER TABLE ops.batch_orchestration ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Service Role Full Access" ON ops.batch_orchestration;
CREATE POLICY "Service Role Full Access" ON ops.batch_orchestration FOR ALL TO service_role USING (true) WITH CHECK (true);
-- =============================================================================
-- PART 5: GRANTS
-- =============================================================================
GRANT ALL ON enforcement.plaintiff_enforcement TO service_role;
GRANT ALL ON enforcement.judgment_enforcement TO service_role;
GRANT ALL ON ops.batch_orchestration TO service_role;
-- =============================================================================
-- PART 6: HELPER VIEW FOR ORCHESTRATOR
-- =============================================================================
CREATE OR REPLACE VIEW ops.v_batches_ready_for_orchestration AS
SELECT b.id AS batch_id,
    b.filename,
    b.source,
    b.row_count_valid,
    b.completed_at AS validation_completed_at,
    COALESCE(o.stage, 'validated') AS orchestration_stage,
    o.jobs_total,
    o.jobs_completed,
    o.jobs_failed
FROM ops.import_batches b
    LEFT JOIN ops.batch_orchestration o ON o.batch_id = b.id
WHERE b.status = 'complete'
    AND (
        o.id IS NULL
        OR o.stage NOT IN ('complete', 'failed')
    )
ORDER BY b.completed_at;
COMMENT ON VIEW ops.v_batches_ready_for_orchestration IS 'Batches that have completed validation and are ready for or in-progress through orchestration';
-- Notify PostgREST
NOTIFY pgrst,
'reload schema';
-- migrate:down
DROP VIEW IF EXISTS ops.v_batches_ready_for_orchestration;
DROP TABLE IF EXISTS ops.batch_orchestration;
DROP TABLE IF EXISTS enforcement.judgment_enforcement;
DROP TABLE IF EXISTS enforcement.plaintiff_enforcement;
-- Note: Cannot remove enum values in PostgreSQL, they remain but are unused