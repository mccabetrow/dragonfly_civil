-- =============================================================================
-- Migration: Plaintiff Targeting Infrastructure
-- Purpose: Collectability scoring function + plaintiff_leads table
-- Date: 2026-01-14
-- =============================================================================
BEGIN;
-- =============================================================================
-- STEP 1: Collectability Scoring Function
-- =============================================================================
-- Computes a 0-100 score predicting collection success likelihood.
-- See docs/COLLECTABILITY_SCORING_SPEC.md for full specification.
--
CREATE OR REPLACE FUNCTION public.compute_collectability_score(
        p_judgment_amount numeric,
        p_judgment_date date,
        p_debtor_name text,
        p_debtor_address text,
        p_plaintiff_phone text DEFAULT NULL,
        p_plaintiff_email text DEFAULT NULL,
        p_attorney_name text DEFAULT NULL,
        p_employer_name text DEFAULT NULL,
        p_raw_payload jsonb DEFAULT NULL
    ) RETURNS TABLE (
        total_score integer,
        amount_score integer,
        recency_score integer,
        debtor_type_score integer,
        address_score integer,
        contact_score integer,
        asset_signal_score integer,
        priority_tier text
    ) LANGUAGE plpgsql STABLE AS $$
DECLARE v_days_since integer;
v_amount_score integer := 0;
v_recency_score integer := 0;
v_debtor_type_score integer := 0;
v_address_score integer := 0;
v_contact_score integer := 0;
v_asset_signal_score integer := 0;
v_total integer := 0;
v_tier text;
BEGIN -- Days since judgment
v_days_since := COALESCE(CURRENT_DATE - p_judgment_date, 9999);
-- 1. Amount Score (30 max)
v_amount_score := CASE
    WHEN COALESCE(p_judgment_amount, 0) < 1000 THEN 0
    WHEN p_judgment_amount < 5000 THEN 10
    WHEN p_judgment_amount < 10000 THEN 15
    WHEN p_judgment_amount < 25000 THEN 20
    WHEN p_judgment_amount < 50000 THEN 25
    WHEN p_judgment_amount < 100000 THEN 28
    ELSE 30
END;
-- 2. Recency Score (20 max)
v_recency_score := CASE
    WHEN v_days_since <= 30 THEN 20
    WHEN v_days_since <= 90 THEN 18
    WHEN v_days_since <= 180 THEN 15
    WHEN v_days_since <= 365 THEN 12
    WHEN v_days_since <= 730 THEN 8
    WHEN v_days_since <= 1825 THEN 5
    WHEN v_days_since <= 3650 THEN 2
    ELSE 0
END;
-- 3. Debtor Type Score (15 max)
v_debtor_type_score := CASE
    WHEN COALESCE(p_debtor_name, '') ~* '\b(LLC|INC|CORP|LP|LLP|CORPORATION|LIMITED)\b' THEN 15
    WHEN p_debtor_name ~* '\b(DBA|D/B/A|TRADING AS)\b' THEN 12
    WHEN p_debtor_name ~* '\b(SERVICES|ENTERPRISES|HOLDINGS|MANAGEMENT|CONSTRUCTION|CONTRACTING|REALTY|PROPERTIES)\b' THEN 10
    WHEN p_debtor_name IS NOT NULL
    AND p_debtor_name != '' THEN 8
    ELSE 5
END;
-- 4. Address Score (15 max)
v_address_score := CASE
    WHEN COALESCE(p_debtor_address, '') ~* '\d+\s+\w+.*\b(NY|NJ|CT|PA|FL|CA|TX)\b.*\d{5}' THEN 15
    WHEN p_debtor_address ~* '\d+\s+\w+'
    AND p_debtor_address ~* '\d{5}' THEN 15
    WHEN p_debtor_address ~* '\d+\s+\w+'
    OR p_debtor_address ~* '\d{5}' THEN 10
    WHEN p_debtor_address IS NOT NULL
    AND LENGTH(p_debtor_address) > 5 THEN 5
    ELSE 0
END;
-- 5. Contact Score (10 max)
v_contact_score := CASE
    WHEN p_plaintiff_phone IS NOT NULL
    AND p_plaintiff_email IS NOT NULL THEN 10
    WHEN p_plaintiff_phone IS NOT NULL THEN 7
    WHEN p_plaintiff_email IS NOT NULL THEN 5
    WHEN p_attorney_name IS NOT NULL
    AND p_attorney_name != '' THEN 3
    ELSE 0
END;
-- 6. Asset Signal Score (10 max)
v_asset_signal_score := LEAST(
    10,
    CASE
        WHEN p_employer_name IS NOT NULL
        AND p_employer_name != '' THEN 5
        ELSE 0
    END + CASE
        WHEN COALESCE(p_debtor_address, '') ~* '\b(SUITE|STE|FLOOR|FL|UNIT|#)\b' THEN 3
        ELSE 0
    END + CASE
        WHEN p_raw_payload IS NOT NULL
        AND p_raw_payload::text ~* '\b(PROPERTY|REAL ESTATE|MORTGAGE|LIEN)\b' THEN 2
        ELSE 0
    END
);
-- Total
v_total := v_amount_score + v_recency_score + v_debtor_type_score + v_address_score + v_contact_score + v_asset_signal_score;
-- Priority Tier
v_tier := CASE
    WHEN v_total >= 80 THEN 'A'
    WHEN v_total >= 60 THEN 'B'
    WHEN v_total >= 40 THEN 'C'
    WHEN v_total >= 20 THEN 'D'
    ELSE 'F'
END;
RETURN QUERY
SELECT v_total,
    v_amount_score,
    v_recency_score,
    v_debtor_type_score,
    v_address_score,
    v_contact_score,
    v_asset_signal_score,
    v_tier;
END;
$$;
COMMENT ON FUNCTION public.compute_collectability_score(
    numeric,
    date,
    text,
    text,
    text,
    text,
    text,
    text,
    jsonb
) IS 'Computes collectability score (0-100) for a judgment. See docs/COLLECTABILITY_SCORING_SPEC.md';
-- =============================================================================
-- STEP 2: Create plaintiff_leads table
-- =============================================================================
-- Materialized output of the plaintiff_targeting worker.
-- Contains scored, prioritized leads ready for outreach.
--
CREATE TABLE IF NOT EXISTS public.plaintiff_leads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Source tracking
    source_judgment_id uuid REFERENCES public.judgments_raw(id),
    source_system text NOT NULL,
    source_county text,
    -- Case identification
    case_number text,
    -- Index number from court
    case_type text,
    -- money_judgment, small_claims, etc.
    -- Plaintiff information
    plaintiff_name text NOT NULL,
    plaintiff_name_normalized text GENERATED ALWAYS AS (
        regexp_replace(lower(trim(plaintiff_name)), '\s+', ' ', 'g')
    ) STORED,
    plaintiff_address text,
    plaintiff_phone text,
    plaintiff_email text,
    attorney_name text,
    attorney_phone text,
    attorney_email text,
    -- Debtor information (for targeting)
    debtor_name text NOT NULL,
    debtor_name_normalized text GENERATED ALWAYS AS (
        regexp_replace(lower(trim(debtor_name)), '\s+', ' ', 'g')
    ) STORED,
    debtor_address text,
    debtor_type text CHECK (
        debtor_type IN ('business', 'dba', 'individual', 'unknown')
    ),
    employer_name text,
    -- Judgment details
    judgment_amount numeric(15, 2),
    judgment_entered_at date,
    filed_at date,
    days_since_judgment integer GENERATED ALWAYS AS (
        CURRENT_DATE - judgment_entered_at
    ) STORED,
    -- Collectability scoring (denormalized for query performance)
    collectability_score integer NOT NULL DEFAULT 0,
    priority_tier text NOT NULL DEFAULT 'F' CHECK (priority_tier IN ('A', 'B', 'C', 'D', 'F')),
    -- Score components (for transparency)
    score_amount integer NOT NULL DEFAULT 0,
    score_recency integer NOT NULL DEFAULT 0,
    score_debtor_type integer NOT NULL DEFAULT 0,
    score_address integer NOT NULL DEFAULT 0,
    score_contact integer NOT NULL DEFAULT 0,
    score_asset_signals integer NOT NULL DEFAULT 0,
    -- Processing tracking
    targeting_run_id uuid,
    -- References targeting worker run
    scored_at timestamptz NOT NULL DEFAULT now(),
    -- Outreach status
    outreach_status text NOT NULL DEFAULT 'pending' CHECK (
        outreach_status IN (
            'pending',
            'contacted',
            'responded',
            'converted',
            'rejected',
            'archived'
        )
    ),
    outreach_attempts integer NOT NULL DEFAULT 0,
    last_outreach_at timestamptz,
    -- Raw data preservation
    raw_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Idempotency
    dedupe_key text NOT NULL,
    -- Same as source judgment dedupe_key
    content_hash text,
    -- For change detection
    -- Audit
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    -- Unique constraint for idempotency
    CONSTRAINT plaintiff_leads_dedupe_key_unique UNIQUE (dedupe_key)
);
COMMENT ON TABLE public.plaintiff_leads IS 'Scored, prioritized plaintiff leads ready for outreach. Output of plaintiff_targeting worker.';
COMMENT ON COLUMN public.plaintiff_leads.collectability_score IS '0-100 score predicting collection success. Higher = better.';
COMMENT ON COLUMN public.plaintiff_leads.priority_tier IS 'A=Platinum (80+), B=Gold (60-79), C=Silver (40-59), D=Bronze (20-39), F=Skip (<20)';
-- =============================================================================
-- STEP 3: Indexes for plaintiff_leads
-- =============================================================================
-- Primary query: Find high-priority pending leads
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_priority_pending ON public.plaintiff_leads (priority_tier, collectability_score DESC)
WHERE outreach_status = 'pending';
-- Query by tier for batch processing
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_tier ON public.plaintiff_leads (priority_tier);
-- Query by score for ranking
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_score ON public.plaintiff_leads (collectability_score DESC);
-- Find leads by source judgment
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_source_judgment ON public.plaintiff_leads (source_judgment_id);
-- Find leads by county
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_county ON public.plaintiff_leads (source_county, priority_tier);
-- Outreach tracking
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_outreach ON public.plaintiff_leads (outreach_status, last_outreach_at);
-- Targeting run tracking
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_targeting_run ON public.plaintiff_leads (targeting_run_id);
-- Judgment amount for filtering
CREATE INDEX IF NOT EXISTS idx_plaintiff_leads_amount ON public.plaintiff_leads (judgment_amount DESC)
WHERE judgment_amount >= 5000;
-- =============================================================================
-- STEP 4: Updated_at trigger
-- =============================================================================
DROP TRIGGER IF EXISTS trg_plaintiff_leads_updated_at ON public.plaintiff_leads;
CREATE TRIGGER trg_plaintiff_leads_updated_at BEFORE
UPDATE ON public.plaintiff_leads FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();
-- =============================================================================
-- STEP 5: Create targeting_runs table
-- =============================================================================
-- Tracks each execution of the plaintiff_targeting worker.
--
CREATE TABLE IF NOT EXISTS public.targeting_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Worker identification
    worker_name text NOT NULL DEFAULT 'plaintiff_targeting',
    worker_version text,
    -- Scope
    source_system text,
    -- Filter by source (null = all)
    source_county text,
    -- Filter by county (null = all)
    min_score_threshold integer,
    -- Only process above this score
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
    -- Metrics
    judgments_evaluated integer NOT NULL DEFAULT 0,
    leads_created integer NOT NULL DEFAULT 0,
    leads_updated integer NOT NULL DEFAULT 0,
    leads_skipped integer NOT NULL DEFAULT 0,
    -- Status
    status text NOT NULL DEFAULT 'running' CHECK (
        status IN ('running', 'completed', 'failed', 'partial')
    ),
    error_message text,
    error_details jsonb,
    -- Audit
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.targeting_runs IS 'Audit log of plaintiff_targeting worker executions.';
-- =============================================================================
-- STEP 6: View for operator dashboard
-- =============================================================================
CREATE OR REPLACE VIEW public.v_plaintiff_leads_dashboard AS
SELECT priority_tier,
    outreach_status,
    COUNT(*) as lead_count,
    ROUND(AVG(collectability_score), 1) as avg_score,
    ROUND(AVG(judgment_amount)::numeric, 2) as avg_judgment_amount,
    SUM(judgment_amount) as total_judgment_value,
    ROUND(AVG(days_since_judgment), 0) as avg_days_old,
    MIN(scored_at) as oldest_scored,
    MAX(scored_at) as newest_scored
FROM public.plaintiff_leads
GROUP BY priority_tier,
    outreach_status
ORDER BY CASE
        priority_tier
        WHEN 'A' THEN 1
        WHEN 'B' THEN 2
        WHEN 'C' THEN 3
        WHEN 'D' THEN 4
        ELSE 5
    END,
    outreach_status;
COMMENT ON VIEW public.v_plaintiff_leads_dashboard IS 'Summary dashboard for plaintiff leads by tier and outreach status.';
-- =============================================================================
-- STEP 7: View for top leads queue
-- =============================================================================
CREATE OR REPLACE VIEW public.v_plaintiff_leads_queue AS
SELECT pl.id,
    pl.priority_tier,
    pl.collectability_score,
    pl.plaintiff_name,
    pl.debtor_name,
    pl.debtor_type,
    pl.judgment_amount,
    pl.judgment_entered_at,
    pl.days_since_judgment,
    pl.plaintiff_phone,
    pl.plaintiff_email,
    pl.attorney_name,
    pl.source_county,
    pl.case_number,
    pl.outreach_status,
    pl.outreach_attempts,
    pl.scored_at
FROM public.plaintiff_leads pl
WHERE pl.outreach_status = 'pending'
    AND pl.priority_tier IN ('A', 'B', 'C')
ORDER BY CASE
        pl.priority_tier
        WHEN 'A' THEN 1
        WHEN 'B' THEN 2
        WHEN 'C' THEN 3
    END,
    pl.collectability_score DESC,
    pl.judgment_amount DESC;
COMMENT ON VIEW public.v_plaintiff_leads_queue IS 'Prioritized queue of actionable plaintiff leads (Tier A/B/C, pending outreach).';
-- =============================================================================
-- STEP 8: RLS
-- =============================================================================
ALTER TABLE public.plaintiff_leads ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.targeting_runs ENABLE ROW LEVEL SECURITY;
-- Service role has full access
CREATE POLICY plaintiff_leads_service_role ON public.plaintiff_leads FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY targeting_runs_service_role ON public.targeting_runs FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated users get read access (for dashboards)
GRANT SELECT ON public.plaintiff_leads TO authenticated;
GRANT SELECT ON public.targeting_runs TO authenticated;
GRANT SELECT ON public.v_plaintiff_leads_dashboard TO authenticated;
GRANT SELECT ON public.v_plaintiff_leads_queue TO authenticated;
-- =============================================================================
-- STEP 9: Grants for dragonfly_app
-- =============================================================================
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.plaintiff_leads TO dragonfly_app;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.targeting_runs TO dragonfly_app;
GRANT SELECT ON public.v_plaintiff_leads_dashboard TO dragonfly_app;
GRANT SELECT ON public.v_plaintiff_leads_queue TO dragonfly_app;
GRANT EXECUTE ON FUNCTION public.compute_collectability_score(
        numeric,
        date,
        text,
        text,
        text,
        text,
        text,
        text,
        jsonb
    ) TO dragonfly_app;
RAISE NOTICE '✓ Granted plaintiff_leads access to dragonfly_app';
END IF;
END $$;
-- Service role grants
GRANT ALL ON public.plaintiff_leads TO service_role;
GRANT ALL ON public.targeting_runs TO service_role;
GRANT EXECUTE ON FUNCTION public.compute_collectability_score(
        numeric,
        date,
        text,
        text,
        text,
        text,
        text,
        text,
        jsonb
    ) TO service_role;
-- =============================================================================
-- VERIFICATION
-- =============================================================================
DO $$ BEGIN RAISE NOTICE '✅ Plaintiff Targeting Infrastructure complete';
RAISE NOTICE '';
RAISE NOTICE 'New tables:';
RAISE NOTICE '  • public.plaintiff_leads (scored leads with priority tiers)';
RAISE NOTICE '  • public.targeting_runs (worker execution audit)';
RAISE NOTICE '';
RAISE NOTICE 'New functions:';
RAISE NOTICE '  • public.compute_collectability_score() - 0-100 score calculation';
RAISE NOTICE '';
RAISE NOTICE 'New views:';
RAISE NOTICE '  • public.v_plaintiff_leads_dashboard - Summary by tier';
RAISE NOTICE '  • public.v_plaintiff_leads_queue - Prioritized action queue';
END $$;
COMMIT;
-- =============================================================================
-- USAGE EXAMPLES
-- =============================================================================
/*
 -- Test the scoring function
 SELECT * FROM compute_collectability_score(
 75000,              -- judgment_amount
 '2026-01-01'::date, -- judgment_date
 'ABC Construction LLC',  -- debtor_name
 '123 Main St Suite 400, Brooklyn, NY 11201',  -- debtor_address
 '555-123-4567',     -- plaintiff_phone
 'john@law.com',     -- plaintiff_email
 'John Smith, Esq.', -- attorney_name
 'XYZ Corp',         -- employer_name
 NULL                -- raw_payload
 );
 
 -- View dashboard
 SELECT * FROM v_plaintiff_leads_dashboard;
 
 -- Get top leads queue
 SELECT * FROM v_plaintiff_leads_queue LIMIT 20;
 
 -- Distribution by tier
 SELECT priority_tier, COUNT(*), ROUND(AVG(collectability_score), 1)
 FROM plaintiff_leads
 GROUP BY priority_tier
 ORDER BY 1;
 */