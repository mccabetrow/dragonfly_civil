-- ============================================================================
-- Migration: Repair ops.worker_heartbeats (Idempotent + Grants)
-- Purpose: Ensure ops.worker_heartbeats table exists with correct grants.
--          Service-role-only access, no RLS required.
--
-- Note: This is a repair migration that ensures the table structure
--       matches what workers expect. Fully idempotent.
-- ============================================================================
-- Ensure schema exists
CREATE SCHEMA IF NOT EXISTS ops;
-- Ensure service_role can use schema
GRANT USAGE ON SCHEMA ops TO service_role;
-- Create table if missing (matches original schema from 20251227000000)
CREATE TABLE IF NOT EXISTS ops.worker_heartbeats (
    worker_id TEXT PRIMARY KEY,
    worker_type TEXT NOT NULL,
    hostname TEXT,
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    status TEXT NOT NULL DEFAULT 'running',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Ensure service_role can access table
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON ops.worker_heartbeats TO service_role;
-- Optional: index for dashboards (fast lookup by worker_type)
CREATE INDEX IF NOT EXISTS idx_worker_heartbeats_type_last_seen ON ops.worker_heartbeats (worker_type, last_seen_at DESC);
-- ============================================================================
-- Migration complete.
-- ============================================================================