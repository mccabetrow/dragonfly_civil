-- Migration: Add 'enforcement_generate_packet' job type and enhance draft_packets
-- ═══════════════════════════════════════════════════════════════════════════════
-- 
-- Purpose: Enable the "Generate Packet" button in the Enforcement Action Center
-- to queue real background jobs that get processed by the enforcement_engine worker.
--
-- Changes:
--   1. Add 'enforcement_generate_packet' to ops.job_type_enum
--   2. Add job_id column to enforcement.draft_packets for job tracking
--   3. Ensure status column has proper values for job state tracking
--
-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. Extend ops.job_type_enum with the new packet generation type
DO $$ BEGIN ALTER TYPE ops.job_type_enum
ADD VALUE IF NOT EXISTS 'enforcement_generate_packet';
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
COMMENT ON TYPE ops.job_type_enum IS 'Job types: enrich_tlo, enrich_idicore, generate_pdf, ingest_csv, enforcement_strategy, enforcement_drafting, enforcement_generate_packet';
-- 2. Add job_id column to enforcement.draft_packets for tracking which job created it
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'enforcement'
        AND table_name = 'draft_packets'
        AND column_name = 'job_id'
) THEN
ALTER TABLE enforcement.draft_packets
ADD COLUMN job_id uuid REFERENCES ops.job_queue(id) ON DELETE
SET NULL;
COMMENT ON COLUMN enforcement.draft_packets.job_id IS 'Reference to the job that created this packet';
END IF;
END $$;
-- 3. Add judgment_id column to enforcement.draft_packets (the case_id is currently used, but judgment_id is clearer)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'enforcement'
        AND table_name = 'draft_packets'
        AND column_name = 'judgment_id'
) THEN
ALTER TABLE enforcement.draft_packets
ADD COLUMN judgment_id bigint REFERENCES public.judgments(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_draft_packets_judgment_id ON enforcement.draft_packets(judgment_id);
COMMENT ON COLUMN enforcement.draft_packets.judgment_id IS 'Judgment this packet is for';
END IF;
END $$;
-- 4. Add strategy column to enforcement.draft_packets
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'enforcement'
        AND table_name = 'draft_packets'
        AND column_name = 'strategy'
) THEN
ALTER TABLE enforcement.draft_packets
ADD COLUMN strategy text DEFAULT 'wage_garnishment';
COMMENT ON COLUMN enforcement.draft_packets.strategy IS 'Enforcement strategy: wage_garnishment, bank_levy, asset_seizure';
END IF;
END $$;
-- 5. Ensure status column uses appropriate values for job tracking
-- Valid statuses: pending, processing, completed, failed
COMMENT ON COLUMN enforcement.draft_packets.status IS 'Packet generation status: pending, processing, completed, failed';
-- 6. Create index on job_id for efficient lookups
CREATE INDEX IF NOT EXISTS idx_draft_packets_job_id ON enforcement.draft_packets(job_id)
WHERE job_id IS NOT NULL;
-- 7. Create index on status for efficient filtering
CREATE INDEX IF NOT EXISTS idx_draft_packets_status ON enforcement.draft_packets(status);
-- ═══════════════════════════════════════════════════════════════════════════════
-- Verification
-- ═══════════════════════════════════════════════════════════════════════════════
-- Run these queries to verify the migration:
-- 
-- SELECT enumlabel FROM pg_enum WHERE enumtypid = 'ops.job_type_enum'::regtype;
-- SELECT column_name, data_type FROM information_schema.columns WHERE table_schema = 'enforcement' AND table_name = 'draft_packets';
