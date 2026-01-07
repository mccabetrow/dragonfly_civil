-- ============================================================================
-- Migration: World Class Security - Least Privilege Enforcement
-- Created: 2025-12-30
-- Purpose: Lock down public schema, enforce RPC-only writes, revoke raw access
-- ============================================================================
--
-- This migration implements enterprise-grade database security:
--
--   1. REVOKE CREATE on public schema from PUBLIC
--   2. REVOKE ALL on database postgres from PUBLIC
--   3. Set restricted search_path for dragonfly_app
--   4. Create SECURITY DEFINER RPCs for all write operations
--   5. Grant SELECT-only on base tables, EXECUTE on RPCs
--   6. NO raw INSERT/UPDATE/DELETE grants (except via RPCs)
--
-- After applying this migration:
--   - Set the role password: ALTER ROLE dragonfly_app WITH PASSWORD '...';
--   - Update SUPABASE_DB_URL to use dragonfly_app credentials
--   - Run scripts/audit_privileges.py to verify lockdown
--
-- ============================================================================
-- ROLLBACK SECTION AT BOTTOM OF FILE
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. ENSURE dragonfly_app ROLE EXISTS (idempotent)
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN CREATE ROLE dragonfly_app WITH LOGIN NOINHERIT NOCREATEDB NOCREATEROLE;
RAISE NOTICE 'Created role dragonfly_app';
ELSE RAISE NOTICE 'Role dragonfly_app already exists';
END IF;
END $$;
-- ============================================================================
-- 2. PUBLIC SCHEMA LOCKDOWN
-- ============================================================================
-- Revoke the ability for PUBLIC to create objects in public schema
-- This prevents accidental table creation or SQL injection attacks
REVOKE CREATE ON SCHEMA public
FROM PUBLIC;
-- Revoke all default privileges on the database from PUBLIC
REVOKE ALL ON DATABASE postgres
FROM PUBLIC;
-- Set restricted search_path for dragonfly_app (no pg_catalog first)
ALTER ROLE dragonfly_app
SET search_path TO public,
    ops,
    enforcement;
-- ============================================================================
-- 3. DEFAULT PRIVILEGES FOR FUTURE OBJECTS
-- ============================================================================
-- Ensure dragonfly_app automatically gets SELECT on new tables and
-- EXECUTE on new functions created by postgres role
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
GRANT SELECT ON TABLES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA ops
GRANT SELECT ON TABLES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA enforcement
GRANT SELECT ON TABLES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
GRANT EXECUTE ON ROUTINES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA ops
GRANT EXECUTE ON ROUTINES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA enforcement
GRANT EXECUTE ON ROUTINES TO dragonfly_app;
-- ============================================================================
-- 4. CREATE SECURITY DEFINER RPCs
-- ============================================================================
-- These functions run as the owner (postgres/superuser) and allow controlled
-- writes to tables without granting raw INSERT/UPDATE to dragonfly_app.
-- Create ai schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS ai;
GRANT USAGE ON SCHEMA ai TO dragonfly_app;
-- ---------------------------------------------------------------------------
-- 4a. ops.upsert_judgment - Replace raw INSERT INTO public.judgments
-- ---------------------------------------------------------------------------
-- Used by ingest_processor.py for CSV imports
CREATE OR REPLACE FUNCTION ops.upsert_judgment(
        p_case_number TEXT,
        p_plaintiff_name TEXT,
        p_defendant_name TEXT,
        p_judgment_amount NUMERIC,
        p_filing_date DATE DEFAULT NULL,
        p_county TEXT DEFAULT NULL,
        p_collectability_score INTEGER DEFAULT NULL,
        p_source_file TEXT DEFAULT NULL,
        p_status TEXT DEFAULT 'pending'
    ) RETURNS TABLE (
        judgment_id BIGINT,
        is_insert BOOLEAN
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    ops AS $$ BEGIN RETURN QUERY
INSERT INTO public.judgments (
        case_number,
        plaintiff_name,
        defendant_name,
        judgment_amount,
        entry_date,
        county,
        collectability_score,
        source_file,
        status,
        created_at
    )
VALUES (
        p_case_number,
        p_plaintiff_name,
        p_defendant_name,
        p_judgment_amount,
        p_filing_date,
        p_county,
        p_collectability_score,
        p_source_file,
        p_status,
        now()
    ) ON CONFLICT (case_number) DO
UPDATE
SET plaintiff_name = EXCLUDED.plaintiff_name,
    defendant_name = EXCLUDED.defendant_name,
    judgment_amount = EXCLUDED.judgment_amount,
    entry_date = EXCLUDED.entry_date,
    county = EXCLUDED.county,
    collectability_score = EXCLUDED.collectability_score,
    updated_at = now()
RETURNING id,
    (xmax = 0);
END;
$$;
COMMENT ON FUNCTION ops.upsert_judgment IS 'Securely upsert a judgment record. Used by ingest_processor for CSV imports.';
-- ---------------------------------------------------------------------------
-- 4b. ops.log_intake_event - Replace raw INSERT INTO ops.intake_logs
-- ---------------------------------------------------------------------------
-- Used by enforcement_engine.py and ingest_processor.py for observability
CREATE OR REPLACE FUNCTION ops.log_intake_event(
        p_batch_id UUID DEFAULT NULL,
        p_job_id UUID DEFAULT NULL,
        p_level TEXT DEFAULT 'INFO',
        p_message TEXT DEFAULT NULL,
        p_raw_payload JSONB DEFAULT NULL
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$
DECLARE v_log_id UUID;
BEGIN
INSERT INTO ops.intake_logs (
        batch_id,
        job_id,
        level,
        message,
        raw_payload,
        created_at
    )
VALUES (
        p_batch_id,
        p_job_id,
        p_level,
        LEFT(p_message, 1000),
        p_raw_payload,
        now()
    )
RETURNING id INTO v_log_id;
RETURN v_log_id;
EXCEPTION
WHEN undefined_table THEN -- Table doesn't exist, silently return NULL
RETURN NULL;
END;
$$;
COMMENT ON FUNCTION ops.log_intake_event IS 'Securely log an intake event to ops.intake_logs. Returns log_id or NULL if table missing.';
-- ---------------------------------------------------------------------------
-- 4c. ops.register_heartbeat - Replace raw heartbeat writes
-- ---------------------------------------------------------------------------
-- Used by heartbeat.py for worker health monitoring
-- Note: Returns worker_id (TEXT) since worker_heartbeats uses worker_id as PK
DROP FUNCTION IF EXISTS ops.register_heartbeat(text, text, text, text);
CREATE OR REPLACE FUNCTION ops.register_heartbeat(
        p_worker_id TEXT,
        p_worker_type TEXT,
        p_hostname TEXT DEFAULT NULL,
        p_status TEXT DEFAULT 'running'
    ) RETURNS TEXT LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN
INSERT INTO ops.worker_heartbeats (
        worker_id,
        worker_type,
        hostname,
        status,
        last_seen_at
    )
VALUES (
        p_worker_id,
        p_worker_type,
        p_hostname,
        p_status,
        now()
    ) ON CONFLICT (worker_id) DO
UPDATE
SET status = EXCLUDED.status,
    last_seen_at = now(),
    updated_at = now();
RETURN p_worker_id;
END;
$$;
COMMENT ON FUNCTION ops.register_heartbeat IS 'Securely register or update a worker heartbeat. Used by worker bootstrap.';
-- ---------------------------------------------------------------------------
-- 4d. ops.update_job_status - Replace raw UPDATE on ops.job_queue
-- ---------------------------------------------------------------------------
-- Used by workers to update job status without raw UPDATE grant
CREATE OR REPLACE FUNCTION ops.update_job_status(
        p_job_id UUID,
        p_status TEXT,
        p_error TEXT DEFAULT NULL
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN
UPDATE ops.job_queue
SET status = p_status,
    locked_at = CASE
        WHEN p_status IN ('completed', 'failed') THEN NULL
        ELSE locked_at
    END,
    last_error = COALESCE(LEFT(p_error, 2000), last_error),
    updated_at = now()
WHERE id = p_job_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION ops.update_job_status IS 'Securely update job queue status. Used by workers to mark jobs completed/failed.';
-- ---------------------------------------------------------------------------
-- 4e. ops.claim_pending_job - Replace raw UPDATE FOR SKIP LOCKED
-- ---------------------------------------------------------------------------
-- Secure job claiming for workers
CREATE OR REPLACE FUNCTION ops.claim_pending_job(
        p_job_types TEXT [],
        p_lock_timeout_minutes INTEGER DEFAULT 30
    ) RETURNS TABLE (
        job_id UUID,
        job_type TEXT,
        payload JSONB,
        attempts INTEGER,
        created_at TIMESTAMPTZ
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN RETURN QUERY
UPDATE ops.job_queue jq
SET status = 'processing',
    locked_at = now(),
    attempts = jq.attempts + 1
WHERE jq.id = (
        SELECT id
        FROM ops.job_queue
        WHERE job_type::text = ANY(p_job_types)
            AND status::text = 'pending'
            AND (
                locked_at IS NULL
                OR locked_at < now() - (p_lock_timeout_minutes || ' minutes')::interval
            )
        ORDER BY created_at ASC
        LIMIT 1 FOR
        UPDATE SKIP LOCKED
    )
RETURNING jq.id,
    jq.job_type::text,
    jq.payload,
    jq.attempts,
    jq.created_at;
END;
$$;
COMMENT ON FUNCTION ops.claim_pending_job IS 'Securely claim a pending job from the queue using FOR UPDATE SKIP LOCKED.';
-- ---------------------------------------------------------------------------
-- 4f. enforcement.record_outcome - Replace raw INSERT for enforcement results
-- ---------------------------------------------------------------------------
-- Used by enforcement_engine.py to log outcomes
CREATE OR REPLACE FUNCTION enforcement.record_outcome(
        p_judgment_id UUID,
        p_outcome_type TEXT,
        p_strategy_type TEXT DEFAULT NULL,
        p_strategy_reason TEXT DEFAULT NULL,
        p_plan_id UUID DEFAULT NULL,
        p_packet_id UUID DEFAULT NULL,
        p_success BOOLEAN DEFAULT TRUE,
        p_error_message TEXT DEFAULT NULL,
        p_metadata JSONB DEFAULT NULL
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = enforcement,
    public AS $$
DECLARE v_event_id UUID;
BEGIN -- Insert into enforcement_events for timeline tracking
INSERT INTO public.enforcement_events (
        judgment_id,
        event_type,
        details,
        created_at
    )
VALUES (
        p_judgment_id::bigint,
        p_outcome_type,
        jsonb_build_object(
            'strategy_type',
            p_strategy_type,
            'strategy_reason',
            p_strategy_reason,
            'plan_id',
            p_plan_id,
            'packet_id',
            p_packet_id,
            'success',
            p_success,
            'error_message',
            p_error_message,
            'metadata',
            p_metadata
        ),
        now()
    )
RETURNING id INTO v_event_id;
RETURN v_event_id;
EXCEPTION
WHEN undefined_table THEN -- Fallback: Try logging to ops.intake_logs
INSERT INTO ops.intake_logs (level, message, raw_payload, created_at)
VALUES (
        CASE
            WHEN p_success THEN 'INFO'
            ELSE 'ERROR'
        END,
        'Enforcement outcome: ' || p_outcome_type,
        jsonb_build_object(
            'judgment_id',
            p_judgment_id,
            'strategy_type',
            p_strategy_type,
            'success',
            p_success,
            'error_message',
            p_error_message
        ),
        now()
    );
RETURN NULL;
END;
$$;
COMMENT ON FUNCTION enforcement.record_outcome IS 'Securely record enforcement outcome events. Used by enforcement_engine.';
-- ---------------------------------------------------------------------------
-- 4g. ops.create_ingest_batch - Replace raw INSERT INTO ops.ingest_batches
-- ---------------------------------------------------------------------------
-- Used by ingest_processor.py to create batch records
CREATE OR REPLACE FUNCTION ops.create_ingest_batch(
        p_source TEXT,
        p_file_path TEXT,
        p_file_hash TEXT DEFAULT NULL,
        p_metadata JSONB DEFAULT NULL
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$
DECLARE v_batch_id UUID;
BEGIN
INSERT INTO ops.ingest_batches (
        source,
        file_path,
        file_hash,
        metadata,
        status,
        created_at
    )
VALUES (
        p_source,
        p_file_path,
        p_file_hash,
        p_metadata,
        'pending',
        now()
    )
RETURNING id INTO v_batch_id;
RETURN v_batch_id;
END;
$$;
COMMENT ON FUNCTION ops.create_ingest_batch IS 'Securely create an ingest batch record. Used by ingest_processor.';
-- ---------------------------------------------------------------------------
-- 4h. ops.finalize_ingest_batch - Update batch completion
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION ops.finalize_ingest_batch(
        p_batch_id UUID,
        p_status TEXT,
        p_rows_processed INTEGER DEFAULT 0,
        p_rows_failed INTEGER DEFAULT 0,
        p_file_hash TEXT DEFAULT NULL
    ) RETURNS BOOLEAN LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$ BEGIN
UPDATE ops.ingest_batches
SET status = p_status,
    rows_processed = p_rows_processed,
    rows_failed = p_rows_failed,
    file_hash = COALESCE(p_file_hash, file_hash),
    completed_at = CASE
        WHEN p_status IN ('completed', 'failed') THEN now()
        ELSE NULL
    END,
    updated_at = now()
WHERE id = p_batch_id;
RETURN FOUND;
END;
$$;
COMMENT ON FUNCTION ops.finalize_ingest_batch IS 'Securely finalize an ingest batch with completion status.';
-- ============================================================================
-- 5. REVOKE RAW TABLE ACCESS, GRANT SELECT ONLY
-- ============================================================================
-- dragonfly_app gets SELECT on tables, but NO INSERT/UPDATE/DELETE
-- All writes go through SECURITY DEFINER RPCs
-- Revoke any existing write grants on critical tables
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.judgments
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.plaintiffs
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.enforcement_cases
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON public.enforcement_events
FROM dragonfly_app;
-- Revoke on ops tables
DO $$ BEGIN REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.job_queue
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.ingest_batches
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.intake_logs
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats
FROM dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- Revoke on enforcement tables
DO $$ BEGIN REVOKE
INSERT,
    UPDATE,
    DELETE ON enforcement.offers
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON enforcement.draft_packets
FROM dragonfly_app;
REVOKE
INSERT,
    UPDATE,
    DELETE ON enforcement.serve_jobs
FROM dragonfly_app;
EXCEPTION
WHEN undefined_table THEN NULL;
END $$;
-- ============================================================================
-- 6. GRANT SCHEMA USAGE
-- ============================================================================
GRANT USAGE ON SCHEMA public TO dragonfly_app;
GRANT USAGE ON SCHEMA ops TO dragonfly_app;
GRANT USAGE ON SCHEMA enforcement TO dragonfly_app;
GRANT USAGE ON SCHEMA ai TO dragonfly_app;
-- Create other schemas if needed
DO $$ BEGIN CREATE SCHEMA IF NOT EXISTS intelligence;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS finance;
END $$;
GRANT USAGE ON SCHEMA intelligence TO dragonfly_app;
GRANT USAGE ON SCHEMA analytics TO dragonfly_app;
GRANT USAGE ON SCHEMA finance TO dragonfly_app;
-- ============================================================================
-- 7. GRANT SELECT ON ALL TABLES
-- ============================================================================
GRANT SELECT ON ALL TABLES IN SCHEMA public TO dragonfly_app;
GRANT SELECT ON ALL TABLES IN SCHEMA ops TO dragonfly_app;
GRANT SELECT ON ALL TABLES IN SCHEMA enforcement TO dragonfly_app;
GRANT SELECT ON ALL TABLES IN SCHEMA intelligence TO dragonfly_app;
GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO dragonfly_app;
GRANT SELECT ON ALL TABLES IN SCHEMA finance TO dragonfly_app;
-- ============================================================================
-- 8. GRANT EXECUTE ON RPCs
-- ============================================================================
-- Core security definer RPCs
GRANT EXECUTE ON FUNCTION ops.upsert_judgment(
        TEXT,
        TEXT,
        TEXT,
        NUMERIC,
        DATE,
        TEXT,
        INTEGER,
        TEXT,
        TEXT
    ) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.log_intake_event(UUID, UUID, TEXT, TEXT, JSONB) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.create_ingest_batch(TEXT, TEXT, TEXT, JSONB) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.finalize_ingest_batch(UUID, TEXT, INTEGER, INTEGER, TEXT) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION enforcement.record_outcome(
        UUID,
        TEXT,
        TEXT,
        TEXT,
        UUID,
        UUID,
        BOOLEAN,
        TEXT,
        JSONB
    ) TO dragonfly_app;
-- Existing RPCs that should remain accessible
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.worker_heartbeat(TEXT, TEXT, TEXT, TEXT) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.check_batch_integrity(UUID) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION ops.check_duplicate_file_hash(TEXT, TEXT) TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.ceo_12_metrics() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics_v2() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.ceo_command_center_metrics() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.enforcement_activity_metrics() TO dragonfly_app;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
-- ============================================================================
-- 9. SEQUENCE GRANTS (for RPCs that need nextval)
-- ============================================================================
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO dragonfly_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO dragonfly_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA enforcement TO dragonfly_app;
-- ============================================================================
-- 10. NOTIFY POSTGREST TO RELOAD SCHEMA
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- ROLLBACK STATEMENTS
-- ============================================================================
-- Run these manually to revert the lockdown:
--
-- BEGIN;
--
-- -- Restore CREATE on public schema
-- GRANT CREATE ON SCHEMA public TO PUBLIC;
--
-- -- Restore raw table access
-- GRANT SELECT, INSERT, UPDATE ON public.judgments TO dragonfly_app;
-- GRANT SELECT, INSERT, UPDATE ON public.plaintiffs TO dragonfly_app;
-- GRANT SELECT, INSERT, UPDATE ON ops.job_queue TO dragonfly_app;
-- GRANT SELECT, INSERT, UPDATE ON ops.ingest_batches TO dragonfly_app;
-- GRANT SELECT, INSERT ON ops.intake_logs TO dragonfly_app;
-- GRANT SELECT, INSERT, UPDATE ON ops.worker_heartbeats TO dragonfly_app;
--
-- -- Drop SECURITY DEFINER functions
-- DROP FUNCTION IF EXISTS ops.upsert_judgment(TEXT, TEXT, TEXT, NUMERIC, DATE, TEXT, INTEGER, TEXT, TEXT);
-- DROP FUNCTION IF EXISTS ops.log_intake_event(UUID, UUID, TEXT, TEXT, JSONB);
-- DROP FUNCTION IF EXISTS ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT);
-- DROP FUNCTION IF EXISTS ops.update_job_status(UUID, TEXT, TEXT);
-- DROP FUNCTION IF EXISTS ops.claim_pending_job(TEXT[], INTEGER);
-- DROP FUNCTION IF EXISTS ops.create_ingest_batch(TEXT, TEXT, TEXT, JSONB);
-- DROP FUNCTION IF EXISTS ops.finalize_ingest_batch(UUID, TEXT, INTEGER, INTEGER, TEXT);
-- DROP FUNCTION IF EXISTS enforcement.record_outcome(UUID, TEXT, TEXT, TEXT, UUID, UUID, BOOLEAN, TEXT, JSONB);
--
-- -- Reset search_path
-- ALTER ROLE dragonfly_app RESET search_path;
--
-- NOTIFY pgrst, 'reload schema';
--
-- COMMIT;
-- ============================================================================
-- ============================================================================
-- POST-MIGRATION CHECKLIST
-- ============================================================================
-- 1. Set the password in Supabase SQL Editor:
--    ALTER ROLE dragonfly_app WITH PASSWORD 'Norwaykmt99!!';
--
-- 2. Update Railway SUPABASE_DB_URL:
--    postgresql://dragonfly_app:Norwaykmt99!!@db.<project>.supabase.co:5432/postgres?sslmode=require
--
-- 3. Run the audit script:
--    python scripts/audit_privileges.py
--
-- 4. Verify with tools.doctor:
--    python -m tools.doctor --env prod
-- ============================================================================
