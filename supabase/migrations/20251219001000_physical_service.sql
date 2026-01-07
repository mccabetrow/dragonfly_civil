-- =============================================================================
-- Physical Service Module - Serve Jobs Table
-- Tracks process server dispatches via Proof.com
-- =============================================================================
-- Created: 2025-12-19
-- Purpose: Store serve job records for physical service of legal documents
-- =============================================================================
-- -----------------------------------------------------------------------------
-- Create serve_jobs table in enforcement schema
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS enforcement.serve_jobs (
    -- Primary key
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Foreign key to judgment being served
    judgment_id BIGINT NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    -- Proof.com job reference
    provider_job_id VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'proof.com',
    -- Job status tracking
    status VARCHAR(50) NOT NULL DEFAULT 'created' CHECK (
        status IN (
            'created',
            -- Job submitted to provider
            'assigned',
            -- Server assigned
            'out_for_service',
            -- Server en route
            'attempted',
            -- Service attempt made
            'served',
            -- Successfully served
            'failed',
            -- All attempts failed
            'cancelled' -- Job cancelled
        )
    ),
    -- Service details
    service_type VARCHAR(50) DEFAULT 'personal' CHECK (
        service_type IN ('personal', 'substituted', 'posting', 'other')
    ),
    priority VARCHAR(20) DEFAULT 'standard' CHECK (
        priority IN ('rush', 'standard', 'economy')
    ),
    attempts_made INTEGER DEFAULT 0,
    max_attempts INTEGER DEFAULT 3,
    -- Cost tracking
    estimated_cost NUMERIC(10, 2),
    actual_cost NUMERIC(10, 2),
    -- Proof of service
    proof_url TEXT,
    -- URL to affidavit/proof document
    served_at TIMESTAMPTZ,
    -- When service was completed
    served_to VARCHAR(255),
    -- Who received service
    service_notes TEXT,
    -- Notes from process server
    -- GPS/location data from service
    service_latitude NUMERIC(10, 7),
    service_longitude NUMERIC(10, 7),
    service_address TEXT,
    -- Webhook tracking
    last_webhook_at TIMESTAMPTZ,
    webhook_events JSONB DEFAULT '[]'::jsonb,
    -- Metadata
    metadata JSONB DEFAULT '{}'::jsonb,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Constraints
    CONSTRAINT unique_provider_job UNIQUE (provider, provider_job_id)
);
-- -----------------------------------------------------------------------------
-- Indexes for performance
-- -----------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS idx_serve_jobs_judgment_id ON enforcement.serve_jobs(judgment_id);
CREATE INDEX IF NOT EXISTS idx_serve_jobs_status ON enforcement.serve_jobs(status);
CREATE INDEX IF NOT EXISTS idx_serve_jobs_provider_job ON enforcement.serve_jobs(provider, provider_job_id);
CREATE INDEX IF NOT EXISTS idx_serve_jobs_created_at ON enforcement.serve_jobs(created_at DESC);
-- Partial index for active jobs
CREATE INDEX IF NOT EXISTS idx_serve_jobs_active ON enforcement.serve_jobs(status, created_at)
WHERE status NOT IN ('served', 'failed', 'cancelled');
-- -----------------------------------------------------------------------------
-- Trigger to update updated_at timestamp
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION enforcement.update_serve_jobs_timestamp() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trigger_serve_jobs_updated_at ON enforcement.serve_jobs;
CREATE TRIGGER trigger_serve_jobs_updated_at BEFORE
UPDATE ON enforcement.serve_jobs FOR EACH ROW EXECUTE FUNCTION enforcement.update_serve_jobs_timestamp();
-- -----------------------------------------------------------------------------
-- RLS Policies
-- -----------------------------------------------------------------------------
ALTER TABLE enforcement.serve_jobs ENABLE ROW LEVEL SECURITY;
-- Service role full access
DROP POLICY IF EXISTS "Service Role Full Access" ON enforcement.serve_jobs;
CREATE POLICY "Service Role Full Access" ON enforcement.serve_jobs FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated users can read
DROP POLICY IF EXISTS "Authenticated Read Access" ON enforcement.serve_jobs;
CREATE POLICY "Authenticated Read Access" ON enforcement.serve_jobs FOR
SELECT TO authenticated USING (true);
-- -----------------------------------------------------------------------------
-- Grants
-- -----------------------------------------------------------------------------
GRANT ALL PRIVILEGES ON enforcement.serve_jobs TO service_role;
GRANT SELECT ON enforcement.serve_jobs TO authenticated;
-- -----------------------------------------------------------------------------
-- View for active serve jobs with judgment details
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW enforcement.v_serve_jobs_active AS
SELECT sj.id,
    sj.judgment_id,
    sj.provider_job_id,
    sj.provider,
    sj.status,
    sj.service_type,
    sj.priority,
    sj.attempts_made,
    sj.max_attempts,
    sj.estimated_cost,
    sj.actual_cost,
    sj.created_at,
    sj.updated_at,
    -- Judgment details
    j.case_number,
    j.defendant_name,
    j.plaintiff_name,
    j.judgment_amount,
    j.court,
    j.county
FROM enforcement.serve_jobs sj
    JOIN public.judgments j ON j.id = sj.judgment_id
WHERE sj.status NOT IN ('served', 'failed', 'cancelled')
ORDER BY CASE
        sj.priority
        WHEN 'rush' THEN 1
        WHEN 'standard' THEN 2
        WHEN 'economy' THEN 3
    END,
    sj.created_at;
GRANT SELECT ON enforcement.v_serve_jobs_active TO authenticated;
GRANT SELECT ON enforcement.v_serve_jobs_active TO service_role;
-- -----------------------------------------------------------------------------
-- Comments
-- -----------------------------------------------------------------------------
COMMENT ON TABLE enforcement.serve_jobs IS 'Tracks process server dispatch jobs via Proof.com for physical service of legal documents';
COMMENT ON COLUMN enforcement.serve_jobs.provider_job_id IS 'External job ID from the service provider (Proof.com)';
COMMENT ON COLUMN enforcement.serve_jobs.proof_url IS 'URL to the affidavit of service or proof document';
COMMENT ON COLUMN enforcement.serve_jobs.webhook_events IS 'Array of webhook events received from provider for audit trail';
-- -----------------------------------------------------------------------------
-- Notify PostgREST to reload schema
-- -----------------------------------------------------------------------------
NOTIFY pgrst,
'reload schema';
