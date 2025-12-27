-- =============================================================================
-- Reaper Heartbeat & Hardening
-- =============================================================================
-- Purpose: Make pg_cron reaper accountable by tracking heartbeats
-- 
-- The reaper (ops.reap_stuck_jobs) must write a heartbeat every run.
-- Watchdog monitors the heartbeat and alerts if reaper goes stale (>20 min).
--
-- Tables:
--   ops.reaper_heartbeat - Single-row heartbeat tracker
--
-- Functions:
--   ops.record_reaper_heartbeat() - Called by reaper after each run
--
-- Depends on: 20250104_ops_foundation.sql (ops schema)
-- =============================================================================
BEGIN;
-- -----------------------------------------------------------------------------
-- 1. Create Reaper Heartbeat Table
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS ops.reaper_heartbeat (
    id INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    -- Single row
    last_run_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    jobs_reaped INT NOT NULL DEFAULT 0,
    run_count BIGINT NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'healthy',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE ops.reaper_heartbeat IS 'Single-row heartbeat tracker for pg_cron reaper. Watchdog monitors this for staleness.';
-- Insert initial row if not exists
INSERT INTO ops.reaper_heartbeat (id, status)
VALUES (1, 'initializing') ON CONFLICT (id) DO NOTHING;
-- -----------------------------------------------------------------------------
-- 2. Create Heartbeat Recording Function
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.record_reaper_heartbeat(
        p_jobs_reaped INT DEFAULT 0,
        p_status TEXT DEFAULT 'healthy',
        p_error_message TEXT DEFAULT NULL
    ) RETURNS VOID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$ BEGIN
INSERT INTO ops.reaper_heartbeat (
        id,
        last_run_at,
        jobs_reaped,
        run_count,
        status,
        error_message,
        updated_at
    )
VALUES (
        1,
        NOW(),
        p_jobs_reaped,
        1,
        p_status,
        p_error_message,
        NOW()
    ) ON CONFLICT (id) DO
UPDATE
SET last_run_at = NOW(),
    jobs_reaped = EXCLUDED.jobs_reaped,
    run_count = ops.reaper_heartbeat.run_count + 1,
    status = EXCLUDED.status,
    error_message = EXCLUDED.error_message,
    updated_at = NOW();
END;
$$;
COMMENT ON FUNCTION ops.record_reaper_heartbeat IS 'Records a reaper heartbeat. Called at the end of each reap_stuck_jobs run.';
-- -----------------------------------------------------------------------------
-- 3. Update reap_stuck_jobs to Record Heartbeat
-- -----------------------------------------------------------------------------
-- 
-- This updates the existing function to call record_reaper_heartbeat at the end.
-- The function reaps jobs stuck in 'processing' state for too long.
CREATE OR REPLACE FUNCTION ops.reap_stuck_jobs(
        p_stuck_threshold INTERVAL DEFAULT INTERVAL '10 minutes'
    ) RETURNS INT LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_reaped_count INT := 0;
BEGIN -- Reap jobs stuck in 'processing' state
WITH reaped AS (
    UPDATE ops.job_queue
    SET status = 'failed',
        error_message = format(
            'Reaped: stuck in processing for > %s (started_at: %s)',
            p_stuck_threshold,
            started_at
        ),
        completed_at = NOW(),
        updated_at = NOW()
    WHERE status = 'processing'
        AND started_at < NOW() - p_stuck_threshold
    RETURNING id
)
SELECT COUNT(*) INTO v_reaped_count
FROM reaped;
-- Also fail jobs that have been pending for too long (24h)
WITH stale_pending AS (
    UPDATE ops.job_queue
    SET status = 'failed',
        error_message = format(
            'Reaped: pending for > 24 hours (created_at: %s)',
            created_at
        ),
        completed_at = NOW(),
        updated_at = NOW()
    WHERE status = 'pending'
        AND created_at < NOW() - INTERVAL '24 hours'
    RETURNING id
)
SELECT v_reaped_count + COUNT(*) INTO v_reaped_count
FROM stale_pending;
-- Log the reap event
IF v_reaped_count > 0 THEN
INSERT INTO ops.ingest_event_log (event_type, payload)
VALUES (
        'reaper_run',
        jsonb_build_object(
            'jobs_reaped',
            v_reaped_count,
            'stuck_threshold',
            p_stuck_threshold::TEXT,
            'timestamp',
            NOW()
        )
    );
END IF;
-- =========================================================================
-- HEARTBEAT: Record that the reaper ran successfully
-- =========================================================================
PERFORM ops.record_reaper_heartbeat(
    p_jobs_reaped := v_reaped_count,
    p_status := 'healthy'
);
RETURN v_reaped_count;
EXCEPTION
WHEN OTHERS THEN -- Record failure in heartbeat
PERFORM ops.record_reaper_heartbeat(
    p_jobs_reaped := 0,
    p_status := 'error',
    p_error_message := SQLERRM
);
RAISE;
END;
$$;
COMMENT ON FUNCTION ops.reap_stuck_jobs IS 'Reaps stuck jobs and records heartbeat. Monitored by watchdog for staleness.';
-- -----------------------------------------------------------------------------
-- 4. View for Monitoring Reaper Health
-- -----------------------------------------------------------------------------
CREATE OR REPLACE VIEW ops.v_reaper_status AS
SELECT last_run_at,
    jobs_reaped,
    run_count,
    status,
    error_message,
    EXTRACT(
        EPOCH
        FROM (NOW() - last_run_at)
    ) / 60 AS minutes_since_last_run,
    CASE
        WHEN last_run_at > NOW() - INTERVAL '10 minutes' THEN 'healthy'
        WHEN last_run_at > NOW() - INTERVAL '20 minutes' THEN 'warning'
        ELSE 'critical'
    END AS health_status,
    updated_at
FROM ops.reaper_heartbeat
WHERE id = 1;
COMMENT ON VIEW ops.v_reaper_status IS 'Real-time view of reaper health for watchdog monitoring.';
-- -----------------------------------------------------------------------------
-- 5. Grant Permissions
-- -----------------------------------------------------------------------------
-- Allow service_role to read heartbeat status
GRANT SELECT ON ops.reaper_heartbeat TO service_role;
GRANT SELECT ON ops.v_reaper_status TO service_role;
-- Allow postgres (pg_cron) to execute reaper functions
GRANT EXECUTE ON FUNCTION ops.record_reaper_heartbeat TO postgres;
GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs TO postgres;
COMMIT;