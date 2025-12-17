-- ============================================================================
-- Migration: ops.worker_heartbeats (Idempotent Re-Creation)
-- Purpose: Ensure ops.worker_heartbeats table exists in production.
--          This migration is fully idempotent - safe to run multiple times.
--
-- Context: Production database may be missing this table, causing workers
--          to spam error logs when attempting to send heartbeats.
-- ============================================================================
-- ============================================================================
-- SECTION 1: Create ops schema if not exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ops;
-- ============================================================================
-- SECTION 2: Create ops.worker_heartbeats table
-- ============================================================================
-- Workers upsert to this table every ~30 seconds while running.
-- UI queries v_system_health to determine online/offline status.
CREATE TABLE IF NOT EXISTS ops.worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    -- Unique per worker instance (e.g., "ingest-abc123")
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
-- Documentation
COMMENT ON TABLE ops.worker_heartbeats IS 'Tracks worker process heartbeats. Workers upsert every 30s. v_system_health calculates online/offline based on last_seen_at.';
COMMENT ON COLUMN ops.worker_heartbeats.worker_id IS 'Unique identifier per worker instance (e.g., ingest-abc123)';
COMMENT ON COLUMN ops.worker_heartbeats.worker_type IS 'Type of worker: ingest_processor, enforcement_engine';
COMMENT ON COLUMN ops.worker_heartbeats.last_seen_at IS 'Last heartbeat timestamp. Workers update every ~30 seconds.';
COMMENT ON COLUMN ops.worker_heartbeats.hostname IS 'Machine hostname where worker is running';
COMMENT ON COLUMN ops.worker_heartbeats.status IS 'Worker status: running, stopped, or error';
-- ============================================================================
-- SECTION 3: Trigger for updated_at
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.touch_worker_heartbeats_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_worker_heartbeats_updated_at ON ops.worker_heartbeats;
CREATE TRIGGER trg_worker_heartbeats_updated_at BEFORE
UPDATE ON ops.worker_heartbeats FOR EACH ROW EXECUTE FUNCTION ops.touch_worker_heartbeats_updated_at();
-- ============================================================================
-- SECTION 4: RLS Policies (Enable RLS, allow service_role full access)
-- ============================================================================
ALTER TABLE ops.worker_heartbeats ENABLE ROW LEVEL SECURITY;
-- Service role can do everything (SELECT, INSERT, UPDATE, DELETE)
DROP POLICY IF EXISTS worker_heartbeats_service_role ON ops.worker_heartbeats;
CREATE POLICY worker_heartbeats_service_role ON ops.worker_heartbeats FOR ALL TO service_role USING (true) WITH CHECK (true);
-- Authenticated users can read only
DROP POLICY IF EXISTS worker_heartbeats_authenticated_read ON ops.worker_heartbeats;
CREATE POLICY worker_heartbeats_authenticated_read ON ops.worker_heartbeats FOR
SELECT TO authenticated USING (true);
-- ============================================================================
-- SECTION 5: Grants (service_role gets full access)
-- ============================================================================
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT USAGE ON SCHEMA ops TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats TO service_role;
GRANT SELECT ON ops.worker_heartbeats TO authenticated;
-- ============================================================================
-- SECTION 6: RPC for worker heartbeat (upsert function)
-- ============================================================================
CREATE OR REPLACE FUNCTION ops.worker_heartbeat(
        p_worker_id TEXT,
        p_worker_type TEXT,
        p_hostname TEXT DEFAULT NULL,
        p_status TEXT DEFAULT 'running'
    ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN
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
SET worker_type = EXCLUDED.worker_type,
    hostname = EXCLUDED.hostname,
    last_seen_at = now(),
    status = EXCLUDED.status;
END;
$$;
COMMENT ON FUNCTION ops.worker_heartbeat IS 'Upsert worker heartbeat. Call every 30s from worker processes.';
-- Grant execute to service_role
GRANT EXECUTE ON FUNCTION ops.worker_heartbeat TO service_role;
-- ============================================================================
-- Migration complete. Workers should now be able to send heartbeats.
-- ============================================================================