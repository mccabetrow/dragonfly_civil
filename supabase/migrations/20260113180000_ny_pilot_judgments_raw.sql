-- ============================================================================
-- NY Pilot Ingestion Worker: Database Contract
-- ============================================================================
-- Purpose: Landing zone for raw judgment records from NY court systems
-- 
-- Design principles:
--   1. Append-only with idempotent upsert (ON CONFLICT DO NOTHING)
--   2. Deterministic dedupe_key and content_hash for reproducibility
--   3. No business logic - raw data only
--   4. Full audit trail via ingest_runs
--
-- Dedupe strategy:
--   - dedupe_key = deterministic composite of source identifiers
--   - Formula: sha256(source_system || '|' || source_county || '|' || external_id || '|' || source_url)
--   - If external_id is NULL, use source_url as the identifier
--   - content_hash = sha256(raw_payload::text) for change detection
--
-- Idempotency guarantee:
--   - UNIQUE constraint on dedupe_key prevents duplicates
--   - Worker uses INSERT ... ON CONFLICT (dedupe_key) DO NOTHING
--   - Re-running the same ingest is safe and produces identical results
-- ============================================================================
-- ============================================================================
-- Table: ingest_runs
-- ============================================================================
-- Tracks each execution of the ingestion worker.
-- One row per worker run, regardless of success/failure.
CREATE TABLE IF NOT EXISTS public.ingest_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Worker identification
    worker_name text NOT NULL,
    -- e.g., 'ny_judgments_pilot'
    worker_version text,
    -- e.g., '1.0.0' for tracking deployments
    -- Source identification
    source_system text NOT NULL,
    -- e.g., 'ny_ecourts', 'ny_oca'
    source_county text,
    -- e.g., 'kings', 'queens' (nullable for statewide)
    -- Execution timing
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    duration_ms integer GENERATED ALWAYS AS (
        CASE
            WHEN finished_at IS NOT NULL THEN EXTRACT(
                EPOCH
                FROM (finished_at - started_at)
            ) * 1000
        END
    ) STORED,
    -- Execution metrics
    records_fetched integer NOT NULL DEFAULT 0,
    -- Total records retrieved from source
    records_inserted integer NOT NULL DEFAULT 0,
    -- New records inserted
    records_skipped integer NOT NULL DEFAULT 0,
    -- Duplicates skipped via ON CONFLICT
    records_errored integer NOT NULL DEFAULT 0,
    -- Records that failed validation/insert
    -- Execution status
    status text NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'completed', 'failed', 'partial')
    ),
    error_message text,
    -- Top-level error if status = 'failed'
    error_details jsonb,
    -- Structured error info for debugging
    -- Operational metadata
    hostname text,
    -- Machine that ran the worker
    environment text,
    -- 'dev', 'staging', 'prod'
    triggered_by text,
    -- 'scheduler', 'manual', 'backfill'
    -- Audit
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.ingest_runs IS 'Audit log of ingestion worker executions. One row per run.';
COMMENT ON COLUMN public.ingest_runs.records_skipped IS 'Count of records skipped due to dedupe_key conflict (already ingested).';
-- ============================================================================
-- Table: judgments_raw
-- ============================================================================
-- Landing zone for raw judgment records.
-- NO business logic, NO transformations, NO enrichment.
-- Downstream pipelines read from here and write to judgments (canonical).
CREATE TABLE IF NOT EXISTS public.judgments_raw (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Source identification
    source_system text NOT NULL,
    -- e.g., 'ny_ecourts', 'ny_oca', 'simplicity'
    source_county text,
    -- e.g., 'kings', 'queens', 'nassau'
    source_court text,
    -- e.g., 'civil_court', 'supreme_court'
    case_type text,
    -- e.g., 'money_judgment', 'small_claims'
    -- External identifiers
    external_id text,
    -- Source system's ID (index number, case number)
    source_url text NOT NULL,
    -- URL where record was retrieved
    -- Temporal data (as reported by source)
    judgment_entered_at timestamptz,
    -- When judgment was entered
    filed_at timestamptz,
    -- When case was filed
    -- Raw content
    raw_payload jsonb NOT NULL,
    -- Structured data from source (parsed)
    raw_text text,
    -- Unstructured text if applicable (HTML, PDF text)
    raw_html text,
    -- Original HTML if scraped (for debugging)
    -- Deduplication
    content_hash text NOT NULL,
    -- sha256(raw_payload::text) for change detection
    dedupe_key text NOT NULL,
    -- Deterministic composite key for idempotency
    -- Ingest tracking
    ingest_run_id uuid NOT NULL REFERENCES public.ingest_runs(id),
    captured_at timestamptz NOT NULL DEFAULT now(),
    -- Processing status
    status text NOT NULL DEFAULT 'pending' CHECK (
        status IN (
            'pending',
            'processing',
            'processed',
            'failed',
            'skipped'
        )
    ),
    processed_at timestamptz,
    -- When downstream pipeline processed this
    processed_by text,
    -- Which pipeline processed it
    -- Error tracking
    error_code text,
    -- Machine-readable error code
    error_message text,
    -- Human-readable error message
    error_details jsonb,
    -- Structured error context
    retry_count integer NOT NULL DEFAULT 0,
    -- Audit
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- Idempotency constraint
    CONSTRAINT judgments_raw_dedupe_key_unique UNIQUE (dedupe_key)
);
COMMENT ON TABLE public.judgments_raw IS 'Landing zone for raw judgment records. Append-only with idempotent upsert semantics.';
COMMENT ON COLUMN public.judgments_raw.dedupe_key IS 'Deterministic composite key: sha256(source_system || "|" || source_county || "|" || coalesce(external_id, source_url))';
COMMENT ON COLUMN public.judgments_raw.content_hash IS 'sha256(raw_payload::text) for detecting content changes on re-ingest.';
COMMENT ON COLUMN public.judgments_raw.status IS 'Processing status: pending (new), processing (in-flight), processed (done), failed (error), skipped (invalid).';
-- ============================================================================
-- Indexes
-- ============================================================================
-- Primary query patterns:
-- 1. Find pending records for processing pipeline
-- 2. Look up by source identifiers
-- 3. Track records by ingest run
-- 4. Content hash lookup for change detection
-- Processing pipeline: find pending records efficiently
CREATE INDEX IF NOT EXISTS idx_judgments_raw_status_pending ON public.judgments_raw (status, created_at)
WHERE status = 'pending';
-- Source lookup: find by external_id within source
CREATE INDEX IF NOT EXISTS idx_judgments_raw_source_external ON public.judgments_raw (source_system, source_county, external_id)
WHERE external_id IS NOT NULL;
-- Ingest run tracking: find all records from a run
CREATE INDEX IF NOT EXISTS idx_judgments_raw_ingest_run ON public.judgments_raw (ingest_run_id);
-- Content hash lookup: detect duplicates/changes
CREATE INDEX IF NOT EXISTS idx_judgments_raw_content_hash ON public.judgments_raw (content_hash);
-- Temporal queries: find by capture time
CREATE INDEX IF NOT EXISTS idx_judgments_raw_captured_at ON public.judgments_raw (captured_at DESC);
-- Source URL lookup: find by URL
CREATE INDEX IF NOT EXISTS idx_judgments_raw_source_url ON public.judgments_raw (source_url);
-- Ingest runs: find recent runs by worker
CREATE INDEX IF NOT EXISTS idx_ingest_runs_worker_started ON public.ingest_runs (worker_name, started_at DESC);
-- Ingest runs: find failed runs
CREATE INDEX IF NOT EXISTS idx_ingest_runs_status ON public.ingest_runs (status)
WHERE status IN ('failed', 'partial');
-- ============================================================================
-- Triggers
-- ============================================================================
-- Auto-update updated_at on judgments_raw
CREATE OR REPLACE FUNCTION public.set_updated_at() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_judgments_raw_updated_at ON public.judgments_raw;
CREATE TRIGGER trg_judgments_raw_updated_at BEFORE
UPDATE ON public.judgments_raw FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
-- ============================================================================
-- Row-Level Security (RLS)
-- ============================================================================
-- These are internal tables accessed only by workers with service_role.
-- RLS is enabled but permissive for service_role.
ALTER TABLE public.ingest_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.judgments_raw ENABLE ROW LEVEL SECURITY;
-- Service role has full access (workers run with service_role)
CREATE POLICY ingest_runs_service_role ON public.ingest_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY judgments_raw_service_role ON public.judgments_raw FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Anon/authenticated users cannot access these tables
-- (No policies = no access for non-service roles)
-- ============================================================================
-- Grants
-- ============================================================================
-- Workers use service_role, which has full access
GRANT ALL ON public.ingest_runs TO service_role;
GRANT ALL ON public.judgments_raw TO service_role;
-- Read-only access for authenticated users (for admin dashboards)
GRANT SELECT ON public.ingest_runs TO authenticated;
GRANT SELECT ON public.judgments_raw TO authenticated;