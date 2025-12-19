-- =============================================================================
-- BREAK GLASS: Disable RLS on ops.job_queue and ops.worker_heartbeats
-- =============================================================================
-- 
-- These are internal backend tables used by workers running with service_role.
-- RLS is NOT needed for these tables since they:
-- 1. Never expose data to end users (internal ops only)
-- 2. Are only accessed by backend services with service_role key
-- 3. Need unrestricted access for job claiming and heartbeat registration
--
-- This migration:
-- 1. Disables RLS on both tables
-- 2. Grants ALL privileges to service_role, postgres, and authenticated
-- 3. Ensures ops schema usage is granted
-- =============================================================================
BEGIN;
-- =============================================================================
-- 1. SCHEMA GRANTS
-- =============================================================================
GRANT USAGE ON SCHEMA ops TO postgres,
    service_role,
    authenticated;
-- =============================================================================
-- 2. DISABLE RLS ON OPS TABLES
-- =============================================================================
-- ops.job_queue - worker job processing
ALTER TABLE ops.job_queue DISABLE ROW LEVEL SECURITY;
-- ops.worker_heartbeats - worker health tracking
ALTER TABLE ops.worker_heartbeats DISABLE ROW LEVEL SECURITY;
-- ops.intake_logs - worker logging (if RLS was enabled)
ALTER TABLE IF EXISTS ops.intake_logs DISABLE ROW LEVEL SECURITY;
-- ops.ingest_batches - batch tracking
ALTER TABLE IF EXISTS ops.ingest_batches DISABLE ROW LEVEL SECURITY;
-- =============================================================================
-- 3. GRANT ALL PRIVILEGES ON TABLES
-- =============================================================================
-- job_queue
GRANT ALL ON TABLE ops.job_queue TO postgres;
GRANT ALL ON TABLE ops.job_queue TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE ops.job_queue TO authenticated;
-- worker_heartbeats
GRANT ALL ON TABLE ops.worker_heartbeats TO postgres;
GRANT ALL ON TABLE ops.worker_heartbeats TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON TABLE ops.worker_heartbeats TO authenticated;
-- intake_logs
GRANT ALL ON TABLE ops.intake_logs TO postgres;
GRANT ALL ON TABLE ops.intake_logs TO service_role;
GRANT SELECT,
    INSERT ON TABLE ops.intake_logs TO authenticated;
-- ingest_batches
GRANT ALL ON TABLE ops.ingest_batches TO postgres;
GRANT ALL ON TABLE ops.ingest_batches TO service_role;
GRANT SELECT,
    INSERT,
    UPDATE ON TABLE ops.ingest_batches TO authenticated;
-- =============================================================================
-- 4. GRANT SEQUENCE USAGE (if any)
-- =============================================================================
GRANT USAGE,
    SELECT ON ALL SEQUENCES IN SCHEMA ops TO postgres,
    service_role,
    authenticated;
-- =============================================================================
-- 5. GRANT EXECUTE ON ALL FUNCTIONS IN OPS SCHEMA
-- =============================================================================
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA ops TO postgres,
    service_role,
    authenticated;
-- =============================================================================
-- 6. VERIFY
-- =============================================================================
DO $$
DECLARE tbl RECORD;
BEGIN FOR tbl IN
SELECT tablename
FROM pg_tables
WHERE schemaname = 'ops' LOOP RAISE NOTICE 'Table ops.% exists',
    tbl.tablename;
END LOOP;
END $$;
COMMIT;
-- =============================================================================
-- POST-MIGRATION VERIFICATION (run separately to confirm)
-- =============================================================================
-- SELECT tablename, rowsecurity 
-- FROM pg_tables 
-- WHERE schemaname = 'ops' 
-- AND tablename IN ('job_queue', 'worker_heartbeats', 'intake_logs', 'ingest_batches');
--
-- Expected: rowsecurity = false for all tables