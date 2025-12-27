-- =============================================================================
-- Migration: Universal Event Log Schema
-- =============================================================================
-- Generalizes logging from ingest-only to cover all domains:
-- - ingest: Data ingestion pipeline
-- - enforcement: Enforcement actions, wage garnishments, etc.
-- - pdf: PDF generation and delivery
-- - external: Third-party API integrations
-- - system: System-level events (workers, reaper, etc.)
--
-- Note: This uses ops.event_log (not audit_log) since audit_log is for entity changes.
-- =============================================================================
-- Create the universal event log table
CREATE TABLE IF NOT EXISTS ops.event_log (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Tracing identifiers
    correlation_id uuid,
    -- End-to-end trace ID
    batch_id uuid,
    -- Optional batch context (for ingest)
    -- Event classification
    domain text NOT NULL,
    -- 'ingest', 'enforcement', 'pdf', 'external', 'system'
    stage text NOT NULL,
    -- Domain-specific stage (e.g., 'validate', 'generate', 'deliver')
    event text NOT NULL,
    -- Event type: 'started', 'completed', 'failed', 'retried', 'skipped'
    -- Event details
    metadata jsonb NOT NULL DEFAULT '{}',
    -- Structured event data
    -- Timestamps
    created_at timestamptz NOT NULL DEFAULT now(),
    -- Constraints
    CONSTRAINT event_log_domain_check CHECK (
        domain IN (
            'ingest',
            'enforcement',
            'pdf',
            'external',
            'system',
            'api',
            'worker'
        )
    ),
    CONSTRAINT event_log_event_check CHECK (
        event IN (
            'started',
            'completed',
            'failed',
            'retried',
            'skipped',
            'warning',
            'info'
        )
    )
);
-- Add comments for documentation
COMMENT ON TABLE ops.event_log IS 'Universal event log for all operational events across all domains';
COMMENT ON COLUMN ops.event_log.correlation_id IS 'End-to-end trace ID for request correlation';
COMMENT ON COLUMN ops.event_log.batch_id IS 'Optional batch ID for ingest domain events';
COMMENT ON COLUMN ops.event_log.domain IS 'Event domain: ingest, enforcement, pdf, external, system, api, worker';
COMMENT ON COLUMN ops.event_log.stage IS 'Domain-specific processing stage';
COMMENT ON COLUMN ops.event_log.event IS 'Event type: started, completed, failed, retried, skipped, warning, info';
COMMENT ON COLUMN ops.event_log.metadata IS 'Structured JSON event data (counts, errors, timing, etc.)';
-- =============================================================================
-- Indices for efficient querying
-- =============================================================================
-- Primary query pattern: domain + time range
CREATE INDEX IF NOT EXISTS idx_event_log_domain_created ON ops.event_log(domain, created_at DESC);
-- Correlation trace lookup
CREATE INDEX IF NOT EXISTS idx_event_log_correlation_id ON ops.event_log(correlation_id)
WHERE correlation_id IS NOT NULL;
-- Batch-specific lookups (for ingest domain)
CREATE INDEX IF NOT EXISTS idx_event_log_batch_id ON ops.event_log(batch_id)
WHERE batch_id IS NOT NULL;
-- Failed event monitoring
CREATE INDEX IF NOT EXISTS idx_event_log_failed_events ON ops.event_log(domain, created_at DESC)
WHERE event = 'failed';
-- =============================================================================
-- Migrate data from existing ingest_event_log (if exists)
-- =============================================================================
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'ops'
        AND table_name = 'ingest_event_log'
) THEN
INSERT INTO ops.event_log (
        id,
        correlation_id,
        batch_id,
        domain,
        stage,
        event,
        metadata,
        created_at
    )
SELECT id,
    correlation_id,
    batch_id,
    'ingest' AS domain,
    stage,
    event,
    metadata,
    created_at
FROM ops.ingest_event_log ON CONFLICT (id) DO NOTHING;
RAISE NOTICE 'Migrated data from ops.ingest_event_log to ops.event_log';
END IF;
END $$;
-- =============================================================================
-- SLO Metrics View for Dashboard
-- =============================================================================
CREATE OR REPLACE VIEW ops.v_event_metrics_24h AS WITH metrics AS (
        SELECT domain,
            COUNT(*) FILTER (
                WHERE event = 'completed'
            ) AS completed_count,
            COUNT(*) FILTER (
                WHERE event = 'failed'
            ) AS failed_count,
            COUNT(*) AS total_count,
            MAX(created_at) AS last_event_at
        FROM ops.event_log
        WHERE created_at >= now() - INTERVAL '24 hours'
        GROUP BY domain
    ),
    error_codes AS (
        SELECT domain,
            (metadata->>'error_code') AS error_code,
            COUNT(*) AS error_count
        FROM ops.event_log
        WHERE created_at >= now() - INTERVAL '24 hours'
            AND event = 'failed'
            AND metadata->>'error_code' IS NOT NULL
        GROUP BY domain,
            metadata->>'error_code'
    ),
    ranked_errors AS (
        SELECT domain,
            error_code,
            error_count,
            ROW_NUMBER() OVER (
                PARTITION BY domain
                ORDER BY error_count DESC
            ) as rn
        FROM error_codes
    )
SELECT m.domain,
    m.completed_count,
    m.failed_count,
    m.total_count,
    CASE
        WHEN m.total_count > 0 THEN ROUND(
            (m.completed_count::numeric / m.total_count) * 100,
            2
        )
        ELSE 100.0
    END AS success_rate_pct,
    m.last_event_at,
    (
        SELECT jsonb_agg(
                jsonb_build_object('code', e.error_code, 'count', e.error_count)
            )
        FROM ranked_errors e
        WHERE e.domain = m.domain
            AND e.rn <= 5
    ) AS top_errors
FROM metrics m;
COMMENT ON VIEW ops.v_event_metrics_24h IS 'Rolling 24-hour metrics by domain for ops dashboard';
-- =============================================================================
-- Burn Rate Tracking View (for alerting)
-- =============================================================================
CREATE OR REPLACE VIEW ops.v_event_burn_rate AS WITH current_window AS (
        SELECT domain,
            COUNT(*) FILTER (
                WHERE event = 'failed'
            ) AS failures_now
        FROM ops.event_log
        WHERE created_at >= now() - INTERVAL '5 minutes'
        GROUP BY domain
    ),
    previous_window AS (
        SELECT domain,
            COUNT(*) FILTER (
                WHERE event = 'failed'
            ) AS failures_prev
        FROM ops.event_log
        WHERE created_at >= now() - INTERVAL '10 minutes'
            AND created_at < now() - INTERVAL '5 minutes'
        GROUP BY domain
    )
SELECT COALESCE(c.domain, p.domain) AS domain,
    COALESCE(c.failures_now, 0) AS failures_last_5min,
    COALESCE(p.failures_prev, 0) AS failures_prev_5min,
    CASE
        WHEN COALESCE(p.failures_prev, 0) = 0
        AND COALESCE(c.failures_now, 0) > 0 THEN 100.0
        WHEN COALESCE(p.failures_prev, 0) = 0 THEN 0.0
        ELSE ROUND(
            (
                (c.failures_now - p.failures_prev)::numeric / NULLIF(p.failures_prev, 0)
            ) * 100,
            2
        )
    END AS burn_rate_pct,
    now() AS calculated_at
FROM current_window c
    FULL OUTER JOIN previous_window p ON c.domain = p.domain;
COMMENT ON VIEW ops.v_event_burn_rate IS 'Failure burn rate by domain (current 5min vs previous 5min)';
-- =============================================================================
-- Security: RLS + Grants
-- =============================================================================
ALTER TABLE ops.event_log ENABLE ROW LEVEL SECURITY;
-- Service role has full access
DROP POLICY IF EXISTS "service_role_event_log" ON ops.event_log;
CREATE POLICY "service_role_event_log" ON ops.event_log FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Dragonfly app role can read/write
DROP POLICY IF EXISTS "dragonfly_app_event_log" ON ops.event_log;
CREATE POLICY "dragonfly_app_event_log" ON ops.event_log FOR ALL TO dragonfly_app USING (true) WITH CHECK (true);
-- Grant access
GRANT SELECT,
    INSERT ON ops.event_log TO service_role;
GRANT SELECT,
    INSERT ON ops.event_log TO dragonfly_app;
GRANT SELECT ON ops.v_event_metrics_24h TO service_role,
    dragonfly_app;
GRANT SELECT ON ops.v_event_burn_rate TO service_role,
    dragonfly_app;
-- =============================================================================
-- Backward Compatibility: Alias views (so old code still works)
-- =============================================================================
-- Create alias view for ops.v_audit_metrics_24h
CREATE OR REPLACE VIEW ops.v_audit_metrics_24h AS
SELECT *
FROM ops.v_event_metrics_24h;
GRANT SELECT ON ops.v_audit_metrics_24h TO service_role,
    dragonfly_app;
-- Create alias view for ops.v_audit_burn_rate  
CREATE OR REPLACE VIEW ops.v_audit_burn_rate AS
SELECT *
FROM ops.v_event_burn_rate;
GRANT SELECT ON ops.v_audit_burn_rate TO service_role,
    dragonfly_app;