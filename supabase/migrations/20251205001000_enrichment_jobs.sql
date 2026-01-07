-- ============================================================================
-- Migration: 20251205001000_enrichment_jobs.sql
-- Dragonfly Enrichment Engine: Job Queue for Background Workers
-- ============================================================================
-- PURPOSE:
--   1. Create ops.job_queue for durable, resumable background jobs
--   2. Support TLOxp, idiCORE enrichment, and PDF generation
--   3. Implement FOR UPDATE SKIP LOCKED pattern for safe concurrent workers
-- ============================================================================
-- ============================================================================
-- 1. Ensure ops schema exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ops;
-- ============================================================================
-- 2. Create enum types (idempotent via DO blocks)
-- ============================================================================
-- Job type enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'job_type_enum'
) THEN CREATE TYPE ops.job_type_enum AS ENUM (
    'enrich_tlo',
    'enrich_idicore',
    'generate_pdf'
);
END IF;
END $$;
COMMENT ON TYPE ops.job_type_enum IS 'Types of background jobs: TLO enrichment, idiCORE enrichment, PDF generation';
-- Job status enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'job_status_enum'
) THEN CREATE TYPE ops.job_status_enum AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed'
);
END IF;
END $$;
COMMENT ON TYPE ops.job_status_enum IS 'Job lifecycle status: pending -> processing -> completed/failed';
-- ============================================================================
-- 3. Create ops.job_queue table
-- ============================================================================
CREATE TABLE IF NOT EXISTS ops.job_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type ops.job_type_enum NOT NULL,
    payload jsonb NOT NULL,
    status ops.job_status_enum NOT NULL DEFAULT 'pending',
    attempts int NOT NULL DEFAULT 0,
    locked_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE ops.job_queue IS 'Durable job queue for background enrichment and PDF generation tasks';
COMMENT ON COLUMN ops.job_queue.job_type IS 'Type of job: enrich_tlo, enrich_idicore, generate_pdf';
COMMENT ON COLUMN ops.job_queue.payload IS 'Job arguments as JSONB, e.g. {"judgment_id": "...", "amount": 12345.67}';
COMMENT ON COLUMN ops.job_queue.status IS 'Job status: pending, processing, completed, failed';
COMMENT ON COLUMN ops.job_queue.attempts IS 'Number of processing attempts (for retry logic)';
COMMENT ON COLUMN ops.job_queue.locked_at IS 'Timestamp when job was locked by a worker; null = unlocked';
COMMENT ON COLUMN ops.job_queue.last_error IS 'Error message from most recent failed attempt';
-- ============================================================================
-- 4. Create indexes for efficient job picking
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_job_queue_pending_pickup ON ops.job_queue (status, locked_at, created_at)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_job_queue_status ON ops.job_queue (status);
CREATE INDEX IF NOT EXISTS idx_job_queue_created_at ON ops.job_queue (created_at DESC);
-- ============================================================================
-- 5. Create trigger function for updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.touch_job_queue_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
COMMENT ON FUNCTION ops.touch_job_queue_updated_at() IS 'Auto-update updated_at timestamp on row modification';
-- ============================================================================
-- 6. Attach trigger to ops.job_queue
-- ============================================================================
DROP TRIGGER IF EXISTS trg_job_queue_updated_at ON ops.job_queue;
CREATE TRIGGER trg_job_queue_updated_at BEFORE
UPDATE ON ops.job_queue FOR EACH ROW EXECUTE FUNCTION ops.touch_job_queue_updated_at();
-- ============================================================================
-- 7. Grant permissions
-- ============================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT ALL ON ops.job_queue TO service_role;
-- ============================================================================
-- 8. Notify PostgREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
