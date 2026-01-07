-- ============================================================================
-- Migration: 20251208000000_rls_hardening.sql
-- Dragonfly Engine - Production RLS Hardening
-- ============================================================================
-- PURPOSE:
--   1. Enable RLS on all sensitive tables in ops.*, intelligence.*, enforcement.*
--   2. Create policies that restrict access to service_role only
--   3. Allow authenticated users read-only access ONLY to specific dashboard views
--   4. Block direct table access for enforcement.offers (API only)
-- ============================================================================
-- SECURITY PHILOSOPHY:
--   - All base tables: service_role ONLY (no authenticated access)
--   - Views for dashboard: authenticated can SELECT, service_role can SELECT
--   - PostgREST uses service_role, so API controls all access
--   - Prevents any rogue authenticated client from reading PII
-- ============================================================================
-- ============================================================================
-- 1. INTELLIGENCE SCHEMA - Lock down completely
-- ============================================================================
-- 1.1 Enable RLS on intelligence.entities
ALTER TABLE intelligence.entities ENABLE ROW LEVEL SECURITY;
-- Drop existing policies if any
DROP POLICY IF EXISTS rls_entities_service_role ON intelligence.entities;
DROP POLICY IF EXISTS rls_entities_block_public ON intelligence.entities;
-- Service role has full access
CREATE POLICY rls_entities_service_role ON intelligence.entities FOR ALL USING (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
) WITH CHECK (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
);
-- Block all other roles
CREATE POLICY rls_entities_block_public ON intelligence.entities FOR ALL USING (false);
COMMENT ON POLICY rls_entities_service_role ON intelligence.entities IS 'Service role has full access to entity data';
COMMENT ON POLICY rls_entities_block_public ON intelligence.entities IS 'Block all non-service roles from direct table access';
-- 1.2 Enable RLS on intelligence.relationships
ALTER TABLE intelligence.relationships ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_relationships_service_role ON intelligence.relationships;
DROP POLICY IF EXISTS rls_relationships_block_public ON intelligence.relationships;
CREATE POLICY rls_relationships_service_role ON intelligence.relationships FOR ALL USING (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
) WITH CHECK (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
);
CREATE POLICY rls_relationships_block_public ON intelligence.relationships FOR ALL USING (false);
COMMENT ON POLICY rls_relationships_service_role ON intelligence.relationships IS 'Service role has full access to relationship data';
-- 1.3 Enable RLS on intelligence.events
ALTER TABLE intelligence.events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_events_service_role ON intelligence.events;
DROP POLICY IF EXISTS rls_events_block_public ON intelligence.events;
CREATE POLICY rls_events_service_role ON intelligence.events FOR ALL USING (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
) WITH CHECK (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
);
CREATE POLICY rls_events_block_public ON intelligence.events FOR ALL USING (false);
COMMENT ON POLICY rls_events_service_role ON intelligence.events IS 'Service role has full access to event log (append-only)';
-- ============================================================================
-- 2. OPS SCHEMA - Job queue is internal only
-- ============================================================================
-- 2.1 Enable RLS on ops.job_queue
ALTER TABLE ops.job_queue ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_job_queue_service_role ON ops.job_queue;
DROP POLICY IF EXISTS rls_job_queue_block_public ON ops.job_queue;
CREATE POLICY rls_job_queue_service_role ON ops.job_queue FOR ALL USING (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
) WITH CHECK (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
);
CREATE POLICY rls_job_queue_block_public ON ops.job_queue FOR ALL USING (false);
COMMENT ON POLICY rls_job_queue_service_role ON ops.job_queue IS 'Only service_role (workers) can access job queue';
COMMENT ON POLICY rls_job_queue_block_public ON ops.job_queue IS 'Block authenticated users from job queue entirely';
-- ============================================================================
-- 3. ENFORCEMENT SCHEMA - Offers are API-controlled only
-- ============================================================================
-- 3.1 Enable RLS on enforcement.offers
ALTER TABLE enforcement.offers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS rls_offers_service_role ON enforcement.offers;
DROP POLICY IF EXISTS rls_offers_block_authenticated ON enforcement.offers;
CREATE POLICY rls_offers_service_role ON enforcement.offers FOR ALL USING (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
) WITH CHECK (
    current_setting('request.jwt.claims', true)::json->>'role' = 'service_role'
);
-- IMPORTANT: Revoke direct SELECT that was granted previously
-- Authenticated users must go through the API
REVOKE
SELECT ON enforcement.offers
FROM authenticated;
COMMENT ON POLICY rls_offers_service_role ON enforcement.offers IS 'Only API (service_role) can read/write offers - prevents unauthorized access to transaction data';
-- ============================================================================
-- 4. DASHBOARD VIEWS - Explicit read access for authenticated users
-- ============================================================================
-- These views are safe for the dashboard to consume directly.
-- They aggregate data and don't expose raw PII.
-- 4.1 enforcement.v_offer_stats (aggregated offer counts per judgment)
GRANT SELECT ON enforcement.v_offer_stats TO authenticated;
-- 4.2 enforcement.v_offer_metrics (global offer KPIs)
GRANT SELECT ON enforcement.v_offer_metrics TO authenticated;
-- 4.3 Revoke direct authenticated access to intelligence views (API only)
-- Views inherit security from base tables, but we want explicit control
REVOKE
SELECT ON intelligence.v_entity_summary
FROM authenticated;
REVOKE
SELECT ON intelligence.v_recent_events
FROM authenticated;
-- Keep service_role access
GRANT SELECT ON intelligence.v_entity_summary TO service_role;
GRANT SELECT ON intelligence.v_recent_events TO service_role;
-- ============================================================================
-- 5. VERIFY GRANTS HAVEN'T LEAKED
-- ============================================================================
-- Ensure ops schema is not accessible to authenticated
REVOKE ALL ON SCHEMA ops
FROM authenticated;
-- Grant usage on enforcement schema (for views only)
GRANT USAGE ON SCHEMA enforcement TO authenticated;
-- intelligence schema: service_role only
REVOKE ALL ON SCHEMA intelligence
FROM authenticated;
-- ============================================================================
-- 6. AUDIT LOG COMMENT
-- ============================================================================
COMMENT ON SCHEMA intelligence IS 'Judgment intelligence graph (entities, relationships, events). Service role ONLY.';
COMMENT ON SCHEMA ops IS 'Operational schema (job queue, background tasks). Service role ONLY.';
COMMENT ON SCHEMA enforcement IS 'Enforcement workflow (offers, packets). Base tables: service role. Views: authenticated SELECT.';
-- ============================================================================
-- 7. NOTIFY POSTGREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
