-- =============================================================================
-- Golden Path Orchestration Schema (Refined)
-- =============================================================================
-- Strategic pivot: Native orchestration replacing n8n.
-- 
-- This migration defines:
--   1. enforcement.plaintiffs - Full entity table for plaintiffs
--   2. enforcement.judgments - Full entity table for judgments
--   3. Job type extensions: ENTITY_RESOLVE, JUDGMENT_CREATE, ENRICHMENT_REQUEST
--   4. Adds 'validated' status to intake.simplicity_batches for orchestrator trigger
--
-- Trigger Flow:
--   intake.simplicity_batches (status='validated')
--     → ENTITY_RESOLVE jobs enqueued
--     → JUDGMENT_CREATE jobs enqueued
--     → ENRICHMENT_REQUEST jobs enqueued
--
-- Apply via: scripts/db_push.ps1 -SupabaseEnv dev
-- =============================================================================
-- migrate:up
-- =============================================================================
-- PART 1: ENFORCEMENT SCHEMA ENTITY TABLES
-- =============================================================================
-- Ensure enforcement schema exists
CREATE SCHEMA IF NOT EXISTS enforcement;
-- enforcement.plaintiffs - Core plaintiff entity for enforcement workflows
CREATE TABLE IF NOT EXISTS enforcement.plaintiffs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK (
        status IN ('active', 'inactive', 'dormant', 'closed')
    ),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE enforcement.plaintiffs IS 'Core plaintiff entities for Golden Path enforcement workflows';
COMMENT ON COLUMN enforcement.plaintiffs.name IS 'Original plaintiff name from intake';
COMMENT ON COLUMN enforcement.plaintiffs.normalized_name IS 'Normalized/cleaned plaintiff name for deduplication';
COMMENT ON COLUMN enforcement.plaintiffs.status IS 'Enforcement status: active, inactive, dormant, closed';
-- Indexes for enforcement.plaintiffs
CREATE INDEX IF NOT EXISTS idx_enforcement_plaintiffs_normalized_name ON enforcement.plaintiffs(normalized_name);
CREATE INDEX IF NOT EXISTS idx_enforcement_plaintiffs_status ON enforcement.plaintiffs(status);
-- enforcement.judgments - Core judgment entity for enforcement workflows
CREATE TABLE IF NOT EXISTS enforcement.judgments (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id UUID NOT NULL REFERENCES enforcement.plaintiffs(id) ON DELETE CASCADE,
    file_number TEXT NOT NULL,
    defendant_name TEXT NOT NULL,
    amount NUMERIC(12, 2),
    batch_id UUID REFERENCES intake.simplicity_batches(id) ON DELETE
    SET NULL,
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
        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE enforcement.judgments IS 'Core judgment entities for Golden Path enforcement workflows';
COMMENT ON COLUMN enforcement.judgments.plaintiff_id IS 'FK to enforcement.plaintiffs';
COMMENT ON COLUMN enforcement.judgments.file_number IS 'Unique case/file number';
COMMENT ON COLUMN enforcement.judgments.defendant_name IS 'Defendant name from intake';
COMMENT ON COLUMN enforcement.judgments.amount IS 'Judgment amount';
COMMENT ON COLUMN enforcement.judgments.batch_id IS 'Source batch from intake.simplicity_batches';
COMMENT ON COLUMN enforcement.judgments.status IS 'Enforcement status: pending, active, served, collecting, satisfied, uncollectible';
-- Indexes for enforcement.judgments
CREATE INDEX IF NOT EXISTS idx_enforcement_judgments_plaintiff_id ON enforcement.judgments(plaintiff_id);
CREATE INDEX IF NOT EXISTS idx_enforcement_judgments_batch_id ON enforcement.judgments(batch_id);
CREATE INDEX IF NOT EXISTS idx_enforcement_judgments_status ON enforcement.judgments(status);
CREATE INDEX IF NOT EXISTS idx_enforcement_judgments_file_number ON enforcement.judgments(file_number);
-- Unique constraint: One file_number per plaintiff
CREATE UNIQUE INDEX IF NOT EXISTS uq_enforcement_judgments_plaintiff_file ON enforcement.judgments(plaintiff_id, file_number);
-- =============================================================================
-- PART 2: ADD 'validated' STATUS TO intake.simplicity_batches
-- =============================================================================
-- We need to alter the CHECK constraint to include 'validated' status.
-- Postgres requires dropping and recreating the constraint.
-- Drop the existing constraint
ALTER TABLE intake.simplicity_batches DROP CONSTRAINT IF EXISTS simplicity_batches_status_check;
-- Add the new constraint with 'validated' status
ALTER TABLE intake.simplicity_batches
ADD CONSTRAINT simplicity_batches_status_check CHECK (
        status IN (
            'pending',
            'staging',
            'transforming',
            'validated',
            'upserting',
            'completed',
            'failed'
        )
    );
-- Add index for orchestrator polling on validated batches
CREATE INDEX IF NOT EXISTS idx_simplicity_batches_validated ON intake.simplicity_batches(id)
WHERE status = 'validated';
COMMENT ON COLUMN intake.simplicity_batches.status IS 'Batch status: pending → staging → transforming → validated → upserting → completed/failed. Orchestrator triggers on validated.';
-- =============================================================================
-- PART 3: EXTEND JOB TYPE ENUM FOR GOLDEN PATH
-- =============================================================================
-- Add ENTITY_RESOLVE job type if not exists
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_enum
    WHERE enumtypid = 'ops.job_type_enum'::regtype
        AND enumlabel = 'entity_resolve'
) THEN ALTER TYPE ops.job_type_enum
ADD VALUE 'entity_resolve';
END IF;
END $$;
-- Add JUDGMENT_CREATE job type if not exists
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_enum
    WHERE enumtypid = 'ops.job_type_enum'::regtype
        AND enumlabel = 'judgment_create'
) THEN ALTER TYPE ops.job_type_enum
ADD VALUE 'judgment_create';
END IF;
END $$;
-- Add ENRICHMENT_REQUEST job type if not exists
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_enum
    WHERE enumtypid = 'ops.job_type_enum'::regtype
        AND enumlabel = 'enrichment_request'
) THEN ALTER TYPE ops.job_type_enum
ADD VALUE 'enrichment_request';
END IF;
END $$;
COMMENT ON TYPE ops.job_type_enum IS 'Job types including Golden Path: entity_resolve, judgment_create, enrichment_request';
-- =============================================================================
-- PART 4: GRANTS FOR ENFORCEMENT TABLES
-- =============================================================================
GRANT USAGE ON SCHEMA enforcement TO service_role;
GRANT ALL ON enforcement.plaintiffs TO service_role;
GRANT ALL ON enforcement.judgments TO service_role;
-- Enable RLS on enforcement tables (service_role bypass by default)
ALTER TABLE enforcement.plaintiffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE enforcement.judgments ENABLE ROW LEVEL SECURITY;
-- Service role bypass policies
CREATE POLICY enforcement_plaintiffs_service_all ON enforcement.plaintiffs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY enforcement_judgments_service_all ON enforcement.judgments FOR ALL TO service_role USING (true) WITH CHECK (true);
-- =============================================================================
-- PART 5: VIEW FOR ORCHESTRATOR POLLING
-- =============================================================================
-- View to find batches ready for Golden Path processing
CREATE OR REPLACE VIEW intake.v_batches_ready_for_orchestration AS
SELECT b.id AS batch_id,
    b.filename,
    b.source_reference,
    b.row_count_valid,
    b.status,
    b.created_at,
    b.transformed_at
FROM intake.simplicity_batches b
WHERE b.status = 'validated'
ORDER BY b.created_at ASC;
COMMENT ON VIEW intake.v_batches_ready_for_orchestration IS 'Batches that have completed validation and are ready for Golden Path orchestration';
GRANT SELECT ON intake.v_batches_ready_for_orchestration TO service_role;
-- =============================================================================
-- migrate:down (if needed for rollback)
-- =============================================================================
-- To rollback:
-- DROP VIEW IF EXISTS intake.v_batches_ready_for_orchestration;
-- DROP POLICY IF EXISTS enforcement_judgments_service_all ON enforcement.judgments;
-- DROP POLICY IF EXISTS enforcement_plaintiffs_service_all ON enforcement.plaintiffs;
-- DROP TABLE IF EXISTS enforcement.judgments;
-- DROP TABLE IF EXISTS enforcement.plaintiffs;
-- Note: Cannot easily remove enum values in Postgres