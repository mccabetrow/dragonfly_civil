-- Migration: Stale Workers View and TTL Semantics
-- Purpose: Enable monitoring of worker health via stale detection
--
-- This migration adds:
-- 1. v_stale_workers view: Returns workers whose last_seen_at > threshold
-- 2. f_get_stale_workers function: Parameterized stale detection
-- 3. status enum update: Add 'starting' and 'degraded' states
-- 4. Grants for dashboard and service roles
-- ==============================================================================
-- 1. Update worker_heartbeats status check constraint
-- ==============================================================================
-- Drop old constraint if exists
ALTER TABLE ops.worker_heartbeats DROP CONSTRAINT IF EXISTS worker_heartbeats_status_check;
-- Add updated constraint with new status values
ALTER TABLE ops.worker_heartbeats
ADD CONSTRAINT worker_heartbeats_status_check CHECK (
        status IN (
            'starting',
            'running',
            'degraded',
            'stopped',
            'error'
        )
    );
-- Add comment documenting status semantics
COMMENT ON COLUMN ops.worker_heartbeats.status IS 'Worker status: starting (init), running (healthy), degraded (transient issue), stopped (graceful shutdown), error (unrecoverable)';
-- ==============================================================================
-- 2. Add stale_threshold_seconds column with default
-- ==============================================================================
-- This allows per-worker customization of stale thresholds
-- Default: 90 seconds (3x the 30s heartbeat interval)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'worker_heartbeats'
        AND column_name = 'stale_threshold_seconds'
) THEN
ALTER TABLE ops.worker_heartbeats
ADD COLUMN stale_threshold_seconds integer NOT NULL DEFAULT 90;
END IF;
END $$;
COMMENT ON COLUMN ops.worker_heartbeats.stale_threshold_seconds IS 'Seconds after last_seen_at before worker is considered stale. Default 90s (3x heartbeat interval).';
-- ==============================================================================
-- 3. Create v_stale_workers view
-- ==============================================================================
CREATE OR REPLACE VIEW ops.v_stale_workers AS
SELECT worker_id,
    worker_type,
    hostname,
    status,
    last_seen_at,
    stale_threshold_seconds,
    -- Calculate seconds since last heartbeat
    EXTRACT(
        EPOCH
        FROM (now() - last_seen_at)
    )::integer AS seconds_since_heartbeat,
    -- Is this worker currently stale?
    CASE
        WHEN status IN ('stopped', 'error') THEN false -- Intentionally offline
        WHEN last_seen_at IS NULL THEN true
        WHEN EXTRACT(
            EPOCH
            FROM (now() - last_seen_at)
        ) > stale_threshold_seconds THEN true
        ELSE false
    END AS is_stale,
    -- Human-readable staleness
    CASE
        WHEN status = 'stopped' THEN 'Stopped (graceful)'
        WHEN status = 'error' THEN 'Error (unrecoverable)'
        WHEN last_seen_at IS NULL THEN 'Never seen'
        WHEN EXTRACT(
            EPOCH
            FROM (now() - last_seen_at)
        ) > stale_threshold_seconds THEN 'Stale (' || EXTRACT(
            EPOCH
            FROM (now() - last_seen_at)
        )::integer || 's ago)'
        ELSE 'Healthy (' || EXTRACT(
            EPOCH
            FROM (now() - last_seen_at)
        )::integer || 's ago)'
    END AS health_status,
    created_at,
    updated_at
FROM ops.worker_heartbeats
ORDER BY -- Prioritize: stale running workers first, then by last_seen_at desc
    CASE
        WHEN status IN ('running', 'starting', 'degraded')
        AND EXTRACT(
            EPOCH
            FROM (now() - last_seen_at)
        ) > stale_threshold_seconds THEN 0
        ELSE 1
    END,
    last_seen_at DESC NULLS LAST;
COMMENT ON VIEW ops.v_stale_workers IS 'View showing all workers with staleness detection. Use WHERE is_stale = true to find unhealthy workers.';
-- ==============================================================================
-- 4. Create f_get_stale_workers function
-- ==============================================================================
CREATE OR REPLACE FUNCTION ops.f_get_stale_workers(
        p_threshold_seconds integer DEFAULT NULL,
        p_worker_type text DEFAULT NULL
    ) RETURNS TABLE (
        worker_id text,
        worker_type text,
        hostname text,
        status text,
        last_seen_at timestamptz,
        seconds_since_heartbeat integer,
        health_status text
    ) LANGUAGE sql STABLE AS $$
SELECT wh.worker_id,
    wh.worker_type,
    wh.hostname,
    wh.status,
    wh.last_seen_at,
    EXTRACT(
        EPOCH
        FROM (now() - wh.last_seen_at)
    )::integer AS seconds_since_heartbeat,
    CASE
        WHEN wh.status = 'stopped' THEN 'Stopped (graceful)'
        WHEN wh.status = 'error' THEN 'Error (unrecoverable)'
        WHEN wh.last_seen_at IS NULL THEN 'Never seen'
        ELSE 'Stale (' || EXTRACT(
            EPOCH
            FROM (now() - wh.last_seen_at)
        )::integer || 's ago)'
    END AS health_status
FROM ops.worker_heartbeats wh
WHERE -- Only check running/starting/degraded workers
    wh.status NOT IN ('stopped', 'error') -- Filter by worker type if specified
    AND (
        p_worker_type IS NULL
        OR wh.worker_type = p_worker_type
    ) -- Check staleness against threshold
    AND (
        wh.last_seen_at IS NULL
        OR EXTRACT(
            EPOCH
            FROM (now() - wh.last_seen_at)
        ) > COALESCE(p_threshold_seconds, wh.stale_threshold_seconds)
    )
ORDER BY wh.last_seen_at ASC NULLS FIRST;
$$;
COMMENT ON FUNCTION ops.f_get_stale_workers IS 'Returns workers that have not sent a heartbeat within the threshold.
Parameters:
  p_threshold_seconds: Override stale threshold (uses per-worker default if NULL)
  p_worker_type: Filter by worker type (all types if NULL)

Examples:
  SELECT * FROM ops.f_get_stale_workers();           -- All stale workers
  SELECT * FROM ops.f_get_stale_workers(60);         -- Stale > 60s
  SELECT * FROM ops.f_get_stale_workers(NULL, ''ingest_processor'');  -- Stale ingest workers
';
-- ==============================================================================
-- 5. Create v_worker_status_summary view for dashboard
-- ==============================================================================
CREATE OR REPLACE VIEW ops.v_worker_status_summary AS
SELECT worker_type,
    COUNT(*) AS total_workers,
    COUNT(*) FILTER (
        WHERE status = 'running'
            AND NOT (
                EXTRACT(
                    EPOCH
                    FROM (now() - last_seen_at)
                ) > stale_threshold_seconds
            )
    ) AS healthy_count,
    COUNT(*) FILTER (
        WHERE status = 'starting'
    ) AS starting_count,
    COUNT(*) FILTER (
        WHERE status = 'degraded'
    ) AS degraded_count,
    COUNT(*) FILTER (
        WHERE status = 'stopped'
    ) AS stopped_count,
    COUNT(*) FILTER (
        WHERE status = 'error'
    ) AS error_count,
    COUNT(*) FILTER (
        WHERE status NOT IN ('stopped', 'error')
            AND (
                last_seen_at IS NULL
                OR EXTRACT(
                    EPOCH
                    FROM (now() - last_seen_at)
                ) > stale_threshold_seconds
            )
    ) AS stale_count,
    MAX(last_seen_at) AS last_heartbeat,
    MIN(
        CASE
            WHEN status NOT IN ('stopped', 'error') THEN last_seen_at
        END
    ) AS oldest_active_heartbeat
FROM ops.worker_heartbeats
GROUP BY worker_type
ORDER BY worker_type;
COMMENT ON VIEW ops.v_worker_status_summary IS 'Aggregated worker health summary by worker type. Shows counts of healthy, degraded, stale, etc.';
-- ==============================================================================
-- 6. Grants
-- ==============================================================================
-- Grant select on views to authenticated users (dashboard)
GRANT SELECT ON ops.v_stale_workers TO authenticated;
GRANT SELECT ON ops.v_worker_status_summary TO authenticated;
-- Grant execute on function to authenticated users
GRANT EXECUTE ON FUNCTION ops.f_get_stale_workers TO authenticated;
-- Grant to service_role for API access
GRANT SELECT ON ops.v_stale_workers TO service_role;
GRANT SELECT ON ops.v_worker_status_summary TO service_role;
GRANT EXECUTE ON FUNCTION ops.f_get_stale_workers TO service_role;
-- ==============================================================================
-- 7. Indexes for performance
-- ==============================================================================
-- Index for stale worker queries
CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_stale_check ON ops.worker_heartbeats (status, last_seen_at)
WHERE status NOT IN ('stopped', 'error');
COMMENT ON INDEX ops.idx_worker_heartbeats_stale_check IS 'Optimizes stale worker detection queries by filtering active workers';