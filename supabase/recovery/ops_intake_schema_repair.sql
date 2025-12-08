-- ============================================================================
-- MASTER REPAIR SCRIPT: ops + intake schema objects
-- ============================================================================
-- File: /supabase/recovery/ops_intake_schema_repair.sql
-- Purpose: Ensure all ops.* tables and views required by /backend exist in prod
-- 
-- Usage: Paste into Supabase SQL Editor when prod drifts from dev
-- 
-- Objects created/repaired:
--   TABLES:
--     - ops.ingest_batches      (canonical intake batch tracking)
--     - ops.intake_logs         (row-level processing audit)
--     - ops.job_queue           (background job queue)
--   VIEWS:
--     - ops.intake_batches      (alias view for backwards compat)
--     - ops.v_intake_monitor    (batch monitoring dashboard)
--     - ops.v_enrichment_health (enrichment queue health)
--   ENUMS:
--     - ops.job_type_enum       (enrich_tlo, enrich_idicore, generate_pdf)
--     - ops.job_status_enum     (pending, processing, completed, failed)
--     - ops.intake_source_type  (simplicity, jbi, manual, csv_upload, api)
--   FUNCTIONS:
--     - ops.touch_job_queue_updated_at()
--
-- Safe to run multiple times (fully idempotent)
-- ============================================================================
BEGIN;
-- ============================================================================
-- SECTION 1: SCHEMA SETUP
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ops;
-- ============================================================================
-- SECTION 2: ENUM TYPES (idempotent via DO blocks)
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
-- Intake source type enum
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
-- ============================================================================
-- SECTION 3: ops.ingest_batches TABLE
-- ============================================================================
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
    updated_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    created_by text
);
-- Add missing columns (idempotent)
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS stats jsonb DEFAULT '{}';
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS started_at timestamptz;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS completed_at timestamptz;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS worker_id text;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS processed_at timestamptz;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS created_by text;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS error_summary text;
ALTER TABLE ops.ingest_batches
ADD COLUMN IF NOT EXISTS updated_at timestamptz DEFAULT now();
-- Indexes
CREATE INDEX IF NOT EXISTS idx_ingest_batches_status ON ops.ingest_batches(status)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_ingest_batches_created_at ON ops.ingest_batches(created_at DESC);
-- ============================================================================
-- SECTION 4: ops.intake_batches VIEW (alias for backwards compat)
-- ============================================================================
-- Some backend code (intake_guardian.py) references ops.intake_batches
-- This view aliases the canonical ops.ingest_batches table
CREATE OR REPLACE VIEW ops.intake_batches AS
SELECT *
FROM ops.ingest_batches;
COMMENT ON VIEW ops.intake_batches IS 'Alias view for ops.ingest_batches - backwards compatibility';
-- ============================================================================
-- SECTION 5: ops.intake_logs TABLE
-- ============================================================================
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
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Unique constraint (idempotent via DO block)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_constraint
    WHERE conname = 'uq_intake_log_batch_row'
) THEN
ALTER TABLE ops.intake_logs
ADD CONSTRAINT uq_intake_log_batch_row UNIQUE (batch_id, row_index);
END IF;
END $$;
-- Indexes
CREATE INDEX IF NOT EXISTS idx_intake_logs_batch_id ON ops.intake_logs(batch_id);
CREATE INDEX IF NOT EXISTS idx_intake_logs_batch_status ON ops.intake_logs(batch_id, status);
CREATE INDEX IF NOT EXISTS idx_intake_logs_status_created ON ops.intake_logs(status, created_at DESC)
WHERE status = 'error';
-- ============================================================================
-- SECTION 6: ops.job_queue TABLE
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
-- Indexes
CREATE INDEX IF NOT EXISTS idx_job_queue_pending_pickup ON ops.job_queue (status, locked_at, created_at)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_job_queue_status ON ops.job_queue (status);
CREATE INDEX IF NOT EXISTS idx_job_queue_created_at ON ops.job_queue (created_at DESC);
-- Trigger function for updated_at
CREATE OR REPLACE FUNCTION ops.touch_job_queue_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
-- Attach trigger
DROP TRIGGER IF EXISTS trg_job_queue_updated_at ON ops.job_queue;
CREATE TRIGGER trg_job_queue_updated_at BEFORE
UPDATE ON ops.job_queue FOR EACH ROW EXECUTE FUNCTION ops.touch_job_queue_updated_at();
-- ============================================================================
-- SECTION 7: ops.v_intake_monitor VIEW
-- ============================================================================
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
COMMENT ON VIEW ops.v_intake_monitor IS 'Real-time batch monitoring dashboard with health status';
-- ============================================================================
-- SECTION 8: ops.v_enrichment_health VIEW
-- ============================================================================
-- This view ALWAYS returns exactly one row (even if job_queue is empty)
-- to prevent 406 errors from .single() calls in the frontend
CREATE OR REPLACE VIEW ops.v_enrichment_health AS
SELECT COALESCE(
        SUM(
            CASE
                WHEN status = 'pending'::ops.job_status_enum THEN 1
                ELSE 0
            END
        ),
        0
    )::bigint AS pending_jobs,
    COALESCE(
        SUM(
            CASE
                WHEN status = 'processing'::ops.job_status_enum THEN 1
                ELSE 0
            END
        ),
        0
    )::bigint AS processing_jobs,
    COALESCE(
        SUM(
            CASE
                WHEN status = 'failed'::ops.job_status_enum THEN 1
                ELSE 0
            END
        ),
        0
    )::bigint AS failed_jobs,
    COALESCE(
        SUM(
            CASE
                WHEN status = 'completed'::ops.job_status_enum THEN 1
                ELSE 0
            END
        ),
        0
    )::bigint AS completed_jobs,
    MAX(created_at) AS last_job_created_at,
    MAX(updated_at) AS last_job_updated_at,
    EXTRACT(
        EPOCH
        FROM (
                NOW() AT TIME ZONE 'utc' - COALESCE(MAX(updated_at), NOW() AT TIME ZONE 'utc')
            )
    )::integer AS time_since_last_activity
FROM ops.job_queue;
COMMENT ON VIEW ops.v_enrichment_health IS 'Enrichment queue health metrics - always returns exactly one row';
-- ============================================================================
-- SECTION 9: ROW LEVEL SECURITY
-- ============================================================================
-- Enable RLS on tables
ALTER TABLE ops.ingest_batches ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.intake_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ops.job_queue ENABLE ROW LEVEL SECURITY;
-- Drop existing policies if they exist (idempotent)
DO $$ BEGIN DROP POLICY IF EXISTS "ingest_batches_service_rw" ON ops.ingest_batches;
DROP POLICY IF EXISTS "Service Role Full Access" ON ops.ingest_batches;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
DO $$ BEGIN DROP POLICY IF EXISTS "intake_logs_service_rw" ON ops.intake_logs;
DROP POLICY IF EXISTS "Service Role Full Access" ON ops.intake_logs;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
DO $$ BEGIN DROP POLICY IF EXISTS "job_queue_service_rw" ON ops.job_queue;
DROP POLICY IF EXISTS "Service Role Full Access" ON ops.job_queue;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Create service_role policies
CREATE POLICY "Service Role Full Access" ON ops.ingest_batches FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service Role Full Access" ON ops.intake_logs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "Service Role Full Access" ON ops.job_queue FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated read access policies
DO $$ BEGIN DROP POLICY IF EXISTS "Authenticated Read Access" ON ops.ingest_batches;
CREATE POLICY "Authenticated Read Access" ON ops.ingest_batches FOR
SELECT TO authenticated USING (true);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN DROP POLICY IF EXISTS "Authenticated Read Access" ON ops.intake_logs;
CREATE POLICY "Authenticated Read Access" ON ops.intake_logs FOR
SELECT TO authenticated USING (true);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- ============================================================================
-- SECTION 10: PERMISSIONS
-- ============================================================================
-- Schema usage
GRANT USAGE ON SCHEMA ops TO authenticated,
    service_role;
-- Table permissions
GRANT SELECT ON ops.ingest_batches TO authenticated;
GRANT ALL ON ops.ingest_batches TO service_role;
GRANT SELECT ON ops.intake_logs TO authenticated;
GRANT ALL ON ops.intake_logs TO service_role;
GRANT ALL ON ops.job_queue TO service_role;
-- View permissions
GRANT SELECT ON ops.intake_batches TO authenticated,
    service_role;
GRANT SELECT ON ops.v_intake_monitor TO authenticated,
    service_role;
GRANT SELECT ON ops.v_enrichment_health TO authenticated,
    service_role;
-- ============================================================================
-- SECTION 11: VALIDATION QUERIES
-- ============================================================================
-- Verify objects exist
SELECT 'ops.ingest_batches' AS object,
    to_regclass('ops.ingest_batches') IS NOT NULL AS exists;
SELECT 'ops.intake_batches' AS object,
    to_regclass('ops.intake_batches') IS NOT NULL AS exists;
SELECT 'ops.intake_logs' AS object,
    to_regclass('ops.intake_logs') IS NOT NULL AS exists;
SELECT 'ops.job_queue' AS object,
    to_regclass('ops.job_queue') IS NOT NULL AS exists;
SELECT 'ops.v_intake_monitor' AS object,
    to_regclass('ops.v_intake_monitor') IS NOT NULL AS exists;
SELECT 'ops.v_enrichment_health' AS object,
    to_regclass('ops.v_enrichment_health') IS NOT NULL AS exists;
-- ============================================================================
-- SECTION 12: NOTIFY POSTGREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- END OF REPAIR SCRIPT
-- ============================================================================