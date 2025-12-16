-- ============================================================================
-- Migration: Worker Heartbeats & System Health
-- Purpose: Enable UI to report "Workers Online" based on actual database
--          activity (heartbeats), not just process existence.
-- 
-- PR-5: Worker Heartbeats & System Status
-- ============================================================================
-- ============================================================================
-- SECTION 1: ops.worker_heartbeats TABLE
-- ============================================================================
-- Workers upsert to this table every ~30 seconds while running.
-- UI queries v_system_health to determine online/offline status.
CREATE TABLE IF NOT EXISTS ops.worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    -- e.g., "ingest-abc123" (unique per instance)
    worker_type TEXT NOT NULL,
    -- "ingest_processor" | "enforcement_engine"
    hostname TEXT,
    -- Machine hostname for debugging
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'stopped', 'error')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Index for fast lookup by worker_type when calculating system health
CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_type_last_seen ON ops.worker_heartbeats (worker_type, last_seen_at DESC);
-- Comment for documentation
COMMENT ON TABLE ops.worker_heartbeats IS 'Tracks worker process heartbeats. Workers upsert every 30s. ' 'v_system_health calculates online/offline based on last_seen_at.';
COMMENT ON COLUMN ops.worker_heartbeats.worker_id IS 'Unique identifier per worker instance (e.g., ingest-abc123)';
COMMENT ON COLUMN ops.worker_heartbeats.worker_type IS 'Type of worker: ingest_processor, enforcement_engine';
COMMENT ON COLUMN ops.worker_heartbeats.last_seen_at IS 'Last heartbeat timestamp. Workers update every ~30 seconds.';
-- Trigger to update updated_at on modification
CREATE OR REPLACE FUNCTION ops.touch_worker_heartbeats_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_worker_heartbeats_updated_at ON ops.worker_heartbeats;
CREATE TRIGGER trg_worker_heartbeats_updated_at BEFORE
UPDATE ON ops.worker_heartbeats FOR EACH ROW EXECUTE FUNCTION ops.touch_worker_heartbeats_updated_at();
-- ============================================================================
-- SECTION 2: ops.v_system_health VIEW
-- ============================================================================
-- Single-row view summarizing system health for the UI.
-- Calculates worker status based on heartbeat freshness.
CREATE OR REPLACE VIEW ops.v_system_health AS WITH ingest_status AS (
        SELECT CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM ops.worker_heartbeats
                    WHERE worker_type = 'ingest_processor'
                        AND last_seen_at > now() - INTERVAL '60 seconds'
                        AND status = 'running'
                ) THEN 'online'
                ELSE 'offline'
            END AS status,
            (
                SELECT last_seen_at
                FROM ops.worker_heartbeats
                WHERE worker_type = 'ingest_processor'
                ORDER BY last_seen_at DESC
                LIMIT 1
            ) AS last_heartbeat
    ),
    enforcement_status AS (
        SELECT CASE
                WHEN EXISTS (
                    SELECT 1
                    FROM ops.worker_heartbeats
                    WHERE worker_type = 'enforcement_engine'
                        AND last_seen_at > now() - INTERVAL '60 seconds'
                        AND status = 'running'
                ) THEN 'online'
                ELSE 'offline'
            END AS status,
            (
                SELECT last_seen_at
                FROM ops.worker_heartbeats
                WHERE worker_type = 'enforcement_engine'
                ORDER BY last_seen_at DESC
                LIMIT 1
            ) AS last_heartbeat
    ),
    queue_stats AS (
        SELECT COUNT(*) FILTER (
                WHERE status::text = 'pending'
            ) AS pending_count,
            COUNT(*) FILTER (
                WHERE status::text = 'processing'
            ) AS processing_count
        FROM ops.job_queue
    )
SELECT (
        SELECT status
        FROM ingest_status
    ) AS ingest_status,
    (
        SELECT last_heartbeat
        FROM ingest_status
    ) AS ingest_last_heartbeat,
    (
        SELECT status
        FROM enforcement_status
    ) AS enforcement_status,
    (
        SELECT last_heartbeat
        FROM enforcement_status
    ) AS enforcement_last_heartbeat,
    COALESCE(
        (
            SELECT pending_count
            FROM queue_stats
        ),
        0
    ) AS queue_depth,
    COALESCE(
        (
            SELECT processing_count
            FROM queue_stats
        ),
        0
    ) AS queue_processing,
    now() AS checked_at;
COMMENT ON VIEW ops.v_system_health IS 'Single-row view of system health for UI. ' 'ingest_status/enforcement_status: online if heartbeat < 60s ago, else offline.';
-- ============================================================================
-- SECTION 3: GRANTS (Security)
-- ============================================================================
-- Ensure service_role can read/write, authenticated users can read view
-- Table grants
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats TO service_role;
GRANT SELECT ON ops.worker_heartbeats TO authenticated;
-- View grants
GRANT SELECT ON ops.v_system_health TO service_role;
GRANT SELECT ON ops.v_system_health TO authenticated;
-- RLS: Enable but allow service_role full access
ALTER TABLE ops.worker_heartbeats ENABLE ROW LEVEL SECURITY;
-- Service role can do everything
DROP POLICY IF EXISTS worker_heartbeats_service_role ON ops.worker_heartbeats;
CREATE POLICY worker_heartbeats_service_role ON ops.worker_heartbeats FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated users can read only
DROP POLICY IF EXISTS worker_heartbeats_authenticated_read ON ops.worker_heartbeats;
CREATE POLICY worker_heartbeats_authenticated_read ON ops.worker_heartbeats FOR
SELECT TO authenticated USING (true);
-- ============================================================================
-- SECTION 4: RPC for worker heartbeat (optional, direct SQL is fine too)
-- ============================================================================
-- Simple RPC that workers can call to register heartbeat
CREATE OR REPLACE FUNCTION ops.worker_heartbeat(
        p_worker_id TEXT,
        p_worker_type TEXT,
        p_hostname TEXT DEFAULT NULL,
        p_status TEXT DEFAULT 'running'
    ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$ BEGIN
INSERT INTO ops.worker_heartbeats (
        worker_id,
        worker_type,
        hostname,
        last_seen_at,
        status
    )
VALUES (
        p_worker_id,
        p_worker_type,
        p_hostname,
        now(),
        p_status
    ) ON CONFLICT (worker_id) DO
UPDATE
SET last_seen_at = now(),
    hostname = COALESCE(
        EXCLUDED.hostname,
        ops.worker_heartbeats.hostname
    ),
    status = EXCLUDED.status,
    updated_at = now();
END;
$$;
GRANT EXECUTE ON FUNCTION ops.worker_heartbeat TO service_role;
COMMENT ON FUNCTION ops.worker_heartbeat IS 'Upsert worker heartbeat. Workers call this every ~30 seconds.';