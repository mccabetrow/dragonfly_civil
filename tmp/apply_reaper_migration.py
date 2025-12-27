"""Apply the reaper heartbeat migration manually."""

import os

import psycopg
from psycopg.rows import dict_row

dsn = os.environ.get("SUPABASE_MIGRATE_DB_URL")
if not dsn:
    print("❌ SUPABASE_MIGRATE_DB_URL not set")
    exit(1)

conn = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

# 1. Create the reaper_heartbeat table
print("Creating ops.reaper_heartbeat table...")
conn.execute(
    """
    CREATE TABLE IF NOT EXISTS ops.reaper_heartbeat (
        id              INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        last_run_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        jobs_reaped     INT NOT NULL DEFAULT 0,
        run_count       BIGINT NOT NULL DEFAULT 0,
        status          TEXT NOT NULL DEFAULT 'healthy',
        error_message   TEXT,
        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
    )
"""
)
print("✅ Table created")

# 2. Add comment
conn.execute(
    """
    COMMENT ON TABLE ops.reaper_heartbeat IS 
    'Single-row heartbeat tracker for pg_cron reaper. Watchdog monitors this for staleness.'
"""
)
print("✅ Table comment added")

# 3. Insert initial row
conn.execute(
    """
    INSERT INTO ops.reaper_heartbeat (id, status)
    VALUES (1, 'initializing')
    ON CONFLICT (id) DO NOTHING
"""
)
print("✅ Initial row inserted")

# 4. Create record_reaper_heartbeat function
print("Creating ops.record_reaper_heartbeat function...")
conn.execute(
    """
    CREATE OR REPLACE FUNCTION ops.record_reaper_heartbeat(
        p_jobs_reaped INT DEFAULT 0,
        p_status TEXT DEFAULT 'healthy',
        p_error_message TEXT DEFAULT NULL
    )
    RETURNS VOID
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = ops, public
    AS $$
    BEGIN
        INSERT INTO ops.reaper_heartbeat (id, last_run_at, jobs_reaped, run_count, status, error_message, updated_at)
        VALUES (1, NOW(), p_jobs_reaped, 1, p_status, p_error_message, NOW())
        ON CONFLICT (id) DO UPDATE SET
            last_run_at = NOW(),
            jobs_reaped = EXCLUDED.jobs_reaped,
            run_count = ops.reaper_heartbeat.run_count + 1,
            status = EXCLUDED.status,
            error_message = EXCLUDED.error_message,
            updated_at = NOW();
    END;
    $$
"""
)
print("✅ record_reaper_heartbeat function created")

# 5. Drop the old reap_stuck_jobs function if it exists
print("Dropping old reap_stuck_jobs function...")
conn.execute("DROP FUNCTION IF EXISTS ops.reap_stuck_jobs(integer)")
print("✅ Old function dropped")

# 6. Create new reap_stuck_jobs function with INTERVAL parameter
print("Creating ops.reap_stuck_jobs function...")
conn.execute(
    """
    CREATE OR REPLACE FUNCTION ops.reap_stuck_jobs(
        p_stuck_threshold INTERVAL DEFAULT INTERVAL '10 minutes'
    )
    RETURNS INT
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = ops, public
    AS $$
    DECLARE
        v_reaped_count INT := 0;
    BEGIN
        -- Reap jobs stuck in 'processing' state
        WITH reaped AS (
            UPDATE ops.job_queue
            SET 
                status = 'failed',
                error_message = format(
                    'Reaped: stuck in processing for > %s (started_at: %s)',
                    p_stuck_threshold,
                    started_at
                ),
                completed_at = NOW(),
                updated_at = NOW()
            WHERE 
                status = 'processing'
                AND started_at < NOW() - p_stuck_threshold
            RETURNING id
        )
        SELECT COUNT(*) INTO v_reaped_count FROM reaped;
        
        -- Also fail jobs that have been pending for too long (24h)
        WITH stale_pending AS (
            UPDATE ops.job_queue
            SET 
                status = 'failed',
                error_message = format(
                    'Reaped: pending for > 24 hours (created_at: %s)',
                    created_at
                ),
                completed_at = NOW(),
                updated_at = NOW()
            WHERE 
                status = 'pending'
                AND created_at < NOW() - INTERVAL '24 hours'
            RETURNING id
        )
        SELECT v_reaped_count + COUNT(*) INTO v_reaped_count FROM stale_pending;
        
        -- Log the reap event (if table exists)
        BEGIN
            IF v_reaped_count > 0 THEN
                INSERT INTO ops.ingest_event_log (event_type, payload)
                VALUES (
                    'reaper_run',
                    jsonb_build_object(
                        'jobs_reaped', v_reaped_count,
                        'stuck_threshold', p_stuck_threshold::TEXT,
                        'timestamp', NOW()
                    )
                );
            END IF;
        EXCEPTION WHEN undefined_table THEN
            -- ingest_event_log doesn't exist yet, skip
            NULL;
        END;
        
        -- HEARTBEAT: Record that the reaper ran successfully
        PERFORM ops.record_reaper_heartbeat(
            p_jobs_reaped := v_reaped_count,
            p_status := 'healthy'
        );
        
        RETURN v_reaped_count;
        
    EXCEPTION WHEN OTHERS THEN
        -- Record failure in heartbeat
        PERFORM ops.record_reaper_heartbeat(
            p_jobs_reaped := 0,
            p_status := 'error',
            p_error_message := SQLERRM
        );
        RAISE;
    END;
    $$
"""
)
print("✅ reap_stuck_jobs function created")

# 7. Add function comment
conn.execute(
    """
    COMMENT ON FUNCTION ops.reap_stuck_jobs(INTERVAL) IS 
    'Reaps stuck jobs and records heartbeat. Monitored by watchdog for staleness.'
"""
)
print("✅ Function comment added")

# 8. Create v_reaper_status view
print("Creating ops.v_reaper_status view...")
conn.execute(
    """
    CREATE OR REPLACE VIEW ops.v_reaper_status AS
    SELECT
        last_run_at,
        jobs_reaped,
        run_count,
        status,
        error_message,
        EXTRACT(EPOCH FROM (NOW() - last_run_at)) / 60 AS minutes_since_last_run,
        CASE
            WHEN last_run_at > NOW() - INTERVAL '10 minutes' THEN 'healthy'
            WHEN last_run_at > NOW() - INTERVAL '20 minutes' THEN 'warning'
            ELSE 'critical'
        END AS health_status,
        updated_at
    FROM ops.reaper_heartbeat
    WHERE id = 1
"""
)
print("✅ v_reaper_status view created")

# 9. Grant permissions
print("Granting permissions...")
conn.execute("GRANT SELECT ON ops.reaper_heartbeat TO service_role")
conn.execute("GRANT SELECT ON ops.v_reaper_status TO service_role")
conn.execute("GRANT EXECUTE ON FUNCTION ops.record_reaper_heartbeat TO postgres")
conn.execute("GRANT EXECUTE ON FUNCTION ops.reap_stuck_jobs(INTERVAL) TO postgres")
print("✅ Permissions granted")

# 10. Mark migration as applied
print("Marking migration as applied...")
conn.execute(
    """
    INSERT INTO supabase_migrations.schema_migrations (version, name, statements)
    VALUES ('20251231200000', '20251231200000_reaper_heartbeat.sql', 8)
    ON CONFLICT (version) DO NOTHING
"""
)
print("✅ Migration marked as applied")

# 11. Verify
print("\n=== Verification ===")
result = conn.execute("SELECT * FROM ops.reaper_heartbeat")
row = result.fetchone()
print(f"ops.reaper_heartbeat: {row}")

result = conn.execute("SELECT * FROM ops.v_reaper_status")
row = result.fetchone()
print(f"ops.v_reaper_status: {dict(row) if row else 'empty'}")

conn.close()
print("\n✅ All done!")
