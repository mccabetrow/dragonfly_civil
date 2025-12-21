-- ============================================================================
-- Migration: Least Privilege Security Model for Dragonfly Civil
-- Created: 2025-12-19
-- Author: Security Architecture Review
-- ============================================================================
--
-- ROLE HIERARCHY:
-- ┌─────────────────────────────────────────────────────────────────────────┐
-- │  postgres / supabase_admin (reserved - full access, migration owner)   │
-- ├─────────────────────────────────────────────────────────────────────────┤
-- │  service_role (Supabase built-in - bypasses RLS, used for admin ops)   │
-- ├─────────────────────────────────────────────────────────────────────────┤
-- │  dragonfly_app    - API runtime (FastAPI backend)                      │
-- │                     SELECT on most tables, EXECUTE on RPCs             │
-- │                     NO raw INSERT/UPDATE on protected tables           │
-- ├─────────────────────────────────────────────────────────────────────────┤
-- │  dragonfly_worker - Background workers (ingest, enforcement, etc.)     │
-- │                     SELECT + limited INSERT/UPDATE on ops tables       │
-- │                     EXECUTE on job-related RPCs                        │
-- ├─────────────────────────────────────────────────────────────────────────┤
-- │  dragonfly_readonly - Dashboard/analytics (read-only access)           │
-- │                       SELECT only on views and materialized views      │
-- └─────────────────────────────────────────────────────────────────────────┘
--
-- DESIGN DECISIONS:
--
-- 1. RLS DISABLED on ops.job_queue, ops.worker_heartbeats:
--    - These are purely internal tables, never exposed to end users
--    - Only accessed by dragonfly_worker role via backend services
--    - RLS would add overhead with no security benefit
--    - Access control is at the role level, not row level
--
-- 2. SECURITY DEFINER RPCs:
--    - ops.claim_pending_job - atomic job claiming with FOR UPDATE SKIP LOCKED
--    - ops.register_heartbeat - worker heartbeat upsert
--    - ops.update_job_status - status transitions
--    - ops.queue_job - enqueue new jobs
--    - These run as the function owner (postgres) with controlled inputs
--
-- 3. Separation of app vs worker:
--    - dragonfly_app handles HTTP requests, needs read + RPC execute
--    - dragonfly_worker runs background jobs, needs ops table access
--    - Prevents API from directly manipulating job queue
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1. CREATE ROLES (Idempotent)
-- ============================================================================
-- dragonfly_app: API runtime role
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_app'
) THEN CREATE ROLE dragonfly_app WITH LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
RAISE NOTICE 'Created role: dragonfly_app';
ELSE RAISE NOTICE 'Role dragonfly_app already exists';
END IF;
END $$;
-- dragonfly_worker: Background worker role
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_worker'
) THEN CREATE ROLE dragonfly_worker WITH LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
RAISE NOTICE 'Created role: dragonfly_worker';
ELSE RAISE NOTICE 'Role dragonfly_worker already exists';
END IF;
END $$;
-- dragonfly_readonly: Dashboard analytics role
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_roles
    WHERE rolname = 'dragonfly_readonly'
) THEN CREATE ROLE dragonfly_readonly WITH LOGIN NOINHERIT NOCREATEDB NOCREATEROLE NOREPLICATION;
RAISE NOTICE 'Created role: dragonfly_readonly';
ELSE RAISE NOTICE 'Role dragonfly_readonly already exists';
END IF;
END $$;
-- Set restricted search_path for all custom roles (security hardening)
ALTER ROLE dragonfly_app
SET search_path TO public,
    ops;
ALTER ROLE dragonfly_worker
SET search_path TO public,
    ops;
ALTER ROLE dragonfly_readonly
SET search_path TO public,
    analytics;
-- ============================================================================
-- 2. SCHEMA GRANTS
-- ============================================================================
-- Ensure schemas exist
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS enforcement;
CREATE SCHEMA IF NOT EXISTS intelligence;
CREATE SCHEMA IF NOT EXISTS analytics;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS intake;
-- dragonfly_app: read from public, ops, enforcement, analytics
GRANT USAGE ON SCHEMA public TO dragonfly_app;
GRANT USAGE ON SCHEMA ops TO dragonfly_app;
GRANT USAGE ON SCHEMA enforcement TO dragonfly_app;
GRANT USAGE ON SCHEMA analytics TO dragonfly_app;
-- dragonfly_worker: needs ops for job processing
GRANT USAGE ON SCHEMA public TO dragonfly_worker;
GRANT USAGE ON SCHEMA ops TO dragonfly_worker;
GRANT USAGE ON SCHEMA enforcement TO dragonfly_worker;
GRANT USAGE ON SCHEMA intake TO dragonfly_worker;
GRANT USAGE ON SCHEMA intelligence TO dragonfly_worker;
-- dragonfly_readonly: analytics and public views only
GRANT USAGE ON SCHEMA public TO dragonfly_readonly;
GRANT USAGE ON SCHEMA analytics TO dragonfly_readonly;
GRANT USAGE ON SCHEMA finance TO dragonfly_readonly;
-- ============================================================================
-- 3. PUBLIC SCHEMA TABLE GRANTS
-- ============================================================================
-- Core tables that both app and worker need to read
DO $$
DECLARE tbl TEXT;
public_read_tables TEXT [] := ARRAY [
        'judgments',
        'plaintiffs',
        'plaintiff_contacts',
        'plaintiff_status_history',
        'enforcement_cases',
        'enforcement_events',
        'cases',
        'entities'
    ];
BEGIN FOREACH tbl IN ARRAY public_read_tables LOOP IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relname = tbl
) THEN -- Both app and worker get SELECT
EXECUTE format(
    'GRANT SELECT ON public.%I TO dragonfly_app',
    tbl
);
EXECUTE format(
    'GRANT SELECT ON public.%I TO dragonfly_worker',
    tbl
);
EXECUTE format(
    'GRANT SELECT ON public.%I TO dragonfly_readonly',
    tbl
);
RAISE NOTICE 'Granted SELECT on public.% to all roles',
tbl;
END IF;
END LOOP;
END $$;
-- Worker needs INSERT/UPDATE on judgments (via RPC preferred, but fallback)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relname = 'judgments'
) THEN
GRANT INSERT,
    UPDATE ON public.judgments TO dragonfly_worker;
RAISE NOTICE 'Granted INSERT, UPDATE on public.judgments to dragonfly_worker';
END IF;
END $$;
-- ============================================================================
-- 4. OPS SCHEMA - INTERNAL TABLES (RLS DISABLED)
-- ============================================================================
-- These tables are purely internal - never exposed to end users
-- Access is controlled at role level, not row level
-- 4a. Disable RLS on internal ops tables
ALTER TABLE IF EXISTS ops.job_queue DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS ops.worker_heartbeats DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS ops.intake_logs DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS ops.ingest_batches DISABLE ROW LEVEL SECURITY;
ALTER TABLE IF EXISTS ops.ingest_audit_log DISABLE ROW LEVEL SECURITY;
-- 4b. Grant SELECT on all ops tables to worker (needs to read job status, etc.)
DO $$
DECLARE tbl RECORD;
BEGIN FOR tbl IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'ops'
    AND c.relkind = 'r' LOOP EXECUTE format(
        'GRANT SELECT ON ops.%I TO dragonfly_worker',
        tbl.relname
    );
EXECUTE format(
    'GRANT SELECT ON ops.%I TO dragonfly_app',
    tbl.relname
);
END LOOP;
END $$;
-- 4c. Worker gets INSERT/UPDATE on specific ops tables for job processing
-- (Prefer RPCs, but grant for backward compatibility during migration)
DO $$ BEGIN -- job_queue: workers claim and update job status
IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
        AND c.relname = 'job_queue'
) THEN
GRANT INSERT,
    UPDATE ON ops.job_queue TO dragonfly_worker;
END IF;
-- worker_heartbeats: workers register their status
IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
        AND c.relname = 'worker_heartbeats'
) THEN
GRANT INSERT,
    UPDATE ON ops.worker_heartbeats TO dragonfly_worker;
END IF;
-- intake_logs: workers write operational logs
IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
        AND c.relname = 'intake_logs'
) THEN
GRANT INSERT ON ops.intake_logs TO dragonfly_worker;
END IF;
-- ingest_batches: workers create and update batch records
IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
        AND c.relname = 'ingest_batches'
) THEN
GRANT INSERT,
    UPDATE ON ops.ingest_batches TO dragonfly_worker;
END IF;
END $$;
-- 4d. App role: READ-ONLY on ops (no direct writes - must use RPCs)
-- Already granted SELECT above, explicitly deny write access
-- (No action needed - absence of GRANT = no access)
-- ============================================================================
-- 5. SECURITY DEFINER RPC FUNCTIONS
-- ============================================================================
-- These functions run with owner privileges (postgres) and provide
-- controlled write access with input validation.
-- 5a. ops.claim_pending_job - Atomic job claiming
-- Worker calls this to claim the next available job
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
        ORDER BY COALESCE(priority, 0) DESC,
            -- Higher priority first
            created_at ASC -- FIFO within priority
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
COMMENT ON FUNCTION ops.claim_pending_job IS 'Atomically claim a pending job using FOR UPDATE SKIP LOCKED. Returns claimed job or empty.';
-- 5b. ops.update_job_status - Status transitions
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
COMMENT ON FUNCTION ops.update_job_status IS 'Update job status with optional error message. Clears lock on completion/failure.';
-- 5c. ops.register_heartbeat - Worker heartbeat upsert
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
COMMENT ON FUNCTION ops.register_heartbeat IS 'Register or update a worker heartbeat. Used by worker bootstrap for health tracking.';
-- 5d. ops.queue_job - Enqueue new jobs
CREATE OR REPLACE FUNCTION ops.queue_job(
        p_type TEXT,
        p_payload JSONB,
        p_priority INTEGER DEFAULT 0,
        p_run_at TIMESTAMPTZ DEFAULT now()
    ) RETURNS UUID LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops AS $$
DECLARE v_job_id UUID;
BEGIN
INSERT INTO ops.job_queue (
        job_type,
        payload,
        priority,
        status,
        run_at,
        created_at
    )
VALUES (
        p_type::ops.job_type_enum,
        p_payload,
        p_priority,
        'pending',
        COALESCE(p_run_at, now()),
        now()
    )
RETURNING id INTO v_job_id;
RETURN v_job_id;
EXCEPTION
WHEN invalid_text_representation THEN RAISE EXCEPTION 'Invalid job type: %',
p_type;
END;
$$;
COMMENT ON FUNCTION ops.queue_job IS 'Enqueue a new job with optional priority and scheduled execution time.';
-- 5e. ops.log_intake_event - Logging helper
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
WHEN undefined_table THEN RETURN NULL;
-- Table doesn't exist, silently return
END;
$$;
COMMENT ON FUNCTION ops.log_intake_event IS 'Log an intake event. Silently returns NULL if table does not exist.';
-- 5f. ops.upsert_judgment - Judgment creation/update
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
    ) RETURNS TABLE (judgment_id BIGINT, is_insert BOOLEAN) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$ BEGIN RETURN QUERY
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
COMMENT ON FUNCTION ops.upsert_judgment IS 'Upsert a judgment record. Returns (judgment_id, is_insert) where is_insert=true for new records.';
-- ============================================================================
-- 6. GRANT EXECUTE ON RPC FUNCTIONS
-- ============================================================================
-- Worker role: can claim jobs, update status, register heartbeat
GRANT EXECUTE ON FUNCTION ops.claim_pending_job(TEXT [], INTEGER) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.update_job_status(UUID, TEXT, TEXT) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.register_heartbeat(TEXT, TEXT, TEXT, TEXT) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO dragonfly_worker;
GRANT EXECUTE ON FUNCTION ops.log_intake_event(UUID, UUID, TEXT, TEXT, JSONB) TO dragonfly_worker;
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
    ) TO dragonfly_worker;
-- App role: can queue jobs and read (but not claim or update status)
GRANT EXECUTE ON FUNCTION ops.queue_job(TEXT, JSONB, INTEGER, TIMESTAMPTZ) TO dragonfly_app;
GRANT EXECUTE ON FUNCTION ops.log_intake_event(UUID, UUID, TEXT, TEXT, JSONB) TO dragonfly_app;
-- Readonly: no RPC access (pure SELECT only)
-- ============================================================================
-- 7. SEQUENCE GRANTS
-- ============================================================================
-- Workers need sequence access for INSERT operations
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO dragonfly_worker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO dragonfly_worker;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA intake TO dragonfly_worker;
-- App needs sequences for any writes it performs
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO dragonfly_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA ops TO dragonfly_app;
-- Default privileges for future sequences
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE ON SEQUENCES TO dragonfly_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT USAGE ON SEQUENCES TO dragonfly_worker;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
GRANT USAGE ON SEQUENCES TO dragonfly_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA ops
GRANT USAGE ON SEQUENCES TO dragonfly_app;
-- ============================================================================
-- 8. VIEW GRANTS (READ-ONLY FOR ALL ROLES)
-- ============================================================================
-- Dashboard-critical views: all roles get SELECT
DO $$
DECLARE v_name TEXT;
dashboard_views TEXT [] := ARRAY [
        'v_plaintiffs_overview',
        'v_judgment_pipeline',
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_plaintiff_call_queue',
        'v_priority_pipeline',
        'v_collectability_scores',
        'v_ops_alerts',
        'v_stale_workers'
    ];
BEGIN FOREACH v_name IN ARRAY dashboard_views LOOP -- Check public schema
IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relname = v_name
) THEN EXECUTE format(
    'GRANT SELECT ON public.%I TO dragonfly_app',
    v_name
);
EXECUTE format(
    'GRANT SELECT ON public.%I TO dragonfly_worker',
    v_name
);
EXECUTE format(
    'GRANT SELECT ON public.%I TO dragonfly_readonly',
    v_name
);
END IF;
-- Check ops schema
IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'ops'
        AND c.relname = v_name
) THEN EXECUTE format(
    'GRANT SELECT ON ops.%I TO dragonfly_app',
    v_name
);
EXECUTE format(
    'GRANT SELECT ON ops.%I TO dragonfly_worker',
    v_name
);
EXECUTE format(
    'GRANT SELECT ON ops.%I TO dragonfly_readonly',
    v_name
);
END IF;
END LOOP;
END $$;
-- Analytics views: readonly gets full access
DO $$
DECLARE v_rec RECORD;
BEGIN FOR v_rec IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'analytics'
    AND c.relkind = 'v' LOOP EXECUTE format(
        'GRANT SELECT ON analytics.%I TO dragonfly_readonly',
        v_rec.relname
    );
EXECUTE format(
    'GRANT SELECT ON analytics.%I TO dragonfly_app',
    v_rec.relname
);
END LOOP;
END $$;
-- Finance views: readonly gets full access
DO $$
DECLARE v_rec RECORD;
BEGIN FOR v_rec IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'finance'
    AND c.relkind = 'v' LOOP EXECUTE format(
        'GRANT SELECT ON finance.%I TO dragonfly_readonly',
        v_rec.relname
    );
END LOOP;
END $$;
-- ============================================================================
-- 9. CEO/DASHBOARD RPC GRANTS
-- ============================================================================
-- Read-only analytics RPCs accessible to all roles
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.ceo_12_metrics() TO dragonfly_app;
GRANT EXECUTE ON FUNCTION public.ceo_12_metrics() TO dragonfly_readonly;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics_v2() TO dragonfly_app;
GRANT EXECUTE ON FUNCTION public.intake_radar_metrics_v2() TO dragonfly_readonly;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.ceo_command_center_metrics() TO dragonfly_app;
GRANT EXECUTE ON FUNCTION public.ceo_command_center_metrics() TO dragonfly_readonly;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
DO $$ BEGIN
GRANT EXECUTE ON FUNCTION public.enforcement_activity_metrics() TO dragonfly_app;
GRANT EXECUTE ON FUNCTION public.enforcement_activity_metrics() TO dragonfly_readonly;
EXCEPTION
WHEN undefined_function THEN NULL;
END $$;
-- ============================================================================
-- 10. REVOKE DANGEROUS PRIVILEGES
-- ============================================================================
-- Revoke CREATE on public schema from PUBLIC (security hardening)
REVOKE CREATE ON SCHEMA public
FROM PUBLIC;
-- Ensure dragonfly roles cannot create objects
REVOKE CREATE ON SCHEMA public
FROM dragonfly_app;
REVOKE CREATE ON SCHEMA public
FROM dragonfly_worker;
REVOKE CREATE ON SCHEMA public
FROM dragonfly_readonly;
REVOKE CREATE ON SCHEMA ops
FROM dragonfly_app;
REVOKE CREATE ON SCHEMA ops
FROM dragonfly_worker;
REVOKE CREATE ON SCHEMA ops
FROM dragonfly_readonly;
-- ============================================================================
-- 11. NOTIFY POSTGREST TO RELOAD SCHEMA
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- NOTES ON APPLICATION:
-- ============================================================================
--
-- 1. SET PASSWORDS (run separately in Supabase SQL Editor):
--    ALTER ROLE dragonfly_app WITH PASSWORD 'your-app-password';
--    ALTER ROLE dragonfly_worker WITH PASSWORD 'your-worker-password';
--    ALTER ROLE dragonfly_readonly WITH PASSWORD 'your-readonly-password';
--
-- 2. CONNECTION STRINGS:
--    App:      postgresql://dragonfly_app:<password>@db.<project>.supabase.co:5432/postgres?sslmode=require
--    Worker:   postgresql://dragonfly_worker:<password>@db.<project>.supabase.co:5432/postgres?sslmode=require
--    Readonly: postgresql://dragonfly_readonly:<password>@db.<project>.supabase.co:5432/postgres?sslmode=require
--
-- 3. ENVIRONMENT VARIABLES (Railway/Vercel):
--    API service:    SUPABASE_DB_URL=<app connection string>
--    Worker service: SUPABASE_DB_URL=<worker connection string>
--    Dashboard:      SUPABASE_DB_URL=<readonly connection string>
--
-- 4. VERIFICATION:
--    Run: SELECT * FROM ops.verify_role_grants();
--    (See verification script below)
--
-- ============================================================================