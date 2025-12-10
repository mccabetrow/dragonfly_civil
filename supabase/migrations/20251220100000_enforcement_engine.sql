-- ============================================================================
-- Migration: Enforcement Engine Worker Support
-- Created: 2025-12-09
-- Purpose: Add job types for AI agent pipeline and analytics view for activity
-- ============================================================================
-- This migration:
--   1. Adds 'enforcement_strategy' and 'enforcement_drafting' to ops.job_type_enum
--   2. Creates analytics.v_enforcement_activity view for monitoring
--   3. Grants appropriate permissions
-- ============================================================================
-- ============================================================================
-- 1. Extend ops.job_type_enum with new agent job types
-- ============================================================================
-- Add 'enforcement_strategy' for Strategist Agent
ALTER TYPE ops.job_type_enum
ADD VALUE IF NOT EXISTS 'enforcement_strategy';
-- Add 'enforcement_drafting' for Drafter Agent  
ALTER TYPE ops.job_type_enum
ADD VALUE IF NOT EXISTS 'enforcement_drafting';
-- Update comment
COMMENT ON TYPE ops.job_type_enum IS 'Job types: enrich_tlo, enrich_idicore, generate_pdf, ingest_csv, enforcement_strategy, enforcement_drafting';
-- ============================================================================
-- 2. Create analytics.v_enforcement_activity view
-- ============================================================================
-- Single-row summary of enforcement engine activity for dashboards.
-- Uses CTEs for efficient aggregation.
-- ============================================================================
-- Ensure analytics schema exists
CREATE SCHEMA IF NOT EXISTS analytics;
GRANT USAGE ON SCHEMA analytics TO authenticated,
    service_role;
-- Drop if exists (allows column changes)
DROP VIEW IF EXISTS analytics.v_enforcement_activity CASCADE;
CREATE VIEW analytics.v_enforcement_activity AS WITH plan_stats AS (
    -- Count enforcement plans created in last 24h
    SELECT COALESCE(
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) AS plans_created_24h,
        COALESCE(
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '7 days'
            ),
            0
        ) AS plans_created_7d,
        COUNT(*) AS total_plans
    FROM enforcement.enforcement_plans
),
packet_stats AS (
    -- Count draft packets generated in last 24h
    SELECT COALESCE(
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) AS packets_generated_24h,
        COALESCE(
            COUNT(*) FILTER (
                WHERE created_at >= NOW() - INTERVAL '7 days'
            ),
            0
        ) AS packets_generated_7d,
        COUNT(*) AS total_packets
    FROM enforcement.draft_packets
),
worker_stats AS (
    -- Count jobs by status for enforcement job types
    SELECT COALESCE(
            COUNT(*) FILTER (
                WHERE status::text = 'processing'
                    AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting')
            ),
            0
        ) AS active_workers,
        COALESCE(
            COUNT(*) FILTER (
                WHERE status::text = 'pending'
                    AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting')
            ),
            0
        ) AS pending_jobs,
        COALESCE(
            COUNT(*) FILTER (
                WHERE status::text = 'completed'
                    AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting')
                    AND updated_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) AS completed_24h,
        COALESCE(
            COUNT(*) FILTER (
                WHERE status::text = 'failed'
                    AND job_type::text IN ('enforcement_strategy', 'enforcement_drafting')
                    AND updated_at >= NOW() - INTERVAL '24 hours'
            ),
            0
        ) AS failed_24h
    FROM ops.job_queue
)
SELECT -- Plan metrics
    ps.plans_created_24h::INTEGER AS plans_created_24h,
    ps.plans_created_7d::INTEGER AS plans_created_7d,
    ps.total_plans::INTEGER AS total_plans,
    -- Packet metrics
    pk.packets_generated_24h::INTEGER AS packets_generated_24h,
    pk.packets_generated_7d::INTEGER AS packets_generated_7d,
    pk.total_packets::INTEGER AS total_packets,
    -- Worker metrics
    ws.active_workers::INTEGER AS active_workers,
    ws.pending_jobs::INTEGER AS pending_jobs,
    ws.completed_24h::INTEGER AS completed_24h,
    ws.failed_24h::INTEGER AS failed_24h,
    -- Timestamp
    NOW() AS generated_at
FROM plan_stats ps
    CROSS JOIN packet_stats pk
    CROSS JOIN worker_stats ws;
COMMENT ON VIEW analytics.v_enforcement_activity IS 'Single-row summary of enforcement engine activity: plans created, packets generated, worker status.';
-- ============================================================================
-- 3. RPC Function for REST API access
-- ============================================================================
CREATE OR REPLACE FUNCTION public.enforcement_activity_metrics() RETURNS TABLE (
        plans_created_24h INTEGER,
        plans_created_7d INTEGER,
        total_plans INTEGER,
        packets_generated_24h INTEGER,
        packets_generated_7d INTEGER,
        total_packets INTEGER,
        active_workers INTEGER,
        pending_jobs INTEGER,
        completed_24h INTEGER,
        failed_24h INTEGER,
        generated_at TIMESTAMPTZ
    ) LANGUAGE SQL STABLE SECURITY DEFINER AS $$
SELECT plans_created_24h,
    plans_created_7d,
    total_plans,
    packets_generated_24h,
    packets_generated_7d,
    total_packets,
    active_workers,
    pending_jobs,
    completed_24h,
    failed_24h,
    generated_at
FROM analytics.v_enforcement_activity
LIMIT 1;
$$;
COMMENT ON FUNCTION public.enforcement_activity_metrics() IS 'RPC wrapper for analytics.v_enforcement_activity - returns enforcement engine activity metrics.';
-- ============================================================================
-- 4. Grants
-- ============================================================================
-- View grants
GRANT SELECT ON analytics.v_enforcement_activity TO authenticated;
GRANT SELECT ON analytics.v_enforcement_activity TO service_role;
-- RPC function grants
GRANT EXECUTE ON FUNCTION public.enforcement_activity_metrics() TO authenticated;
GRANT EXECUTE ON FUNCTION public.enforcement_activity_metrics() TO service_role;
-- Ensure service_role can read/write job_queue for worker operation
GRANT ALL ON ops.job_queue TO service_role;
-- ============================================================================
-- 5. Extend ops.intake_logs for worker observability
-- ============================================================================
-- The table may already exist with different columns from ingest_processor.
-- Add the columns needed for enforcement_engine observability.
-- Add job_id column if missing
ALTER TABLE ops.intake_logs
ADD COLUMN IF NOT EXISTS job_id UUID;
-- Add level column if missing
ALTER TABLE ops.intake_logs
ADD COLUMN IF NOT EXISTS level TEXT;
-- Add message column if missing
ALTER TABLE ops.intake_logs
ADD COLUMN IF NOT EXISTS message TEXT;
-- Add raw_payload column if missing
ALTER TABLE ops.intake_logs
ADD COLUMN IF NOT EXISTS raw_payload JSONB;
-- Make old columns nullable so enforcement worker can insert without them
ALTER TABLE ops.intake_logs
ALTER COLUMN batch_id DROP NOT NULL;
ALTER TABLE ops.intake_logs
ALTER COLUMN row_index DROP NOT NULL;
ALTER TABLE ops.intake_logs
ALTER COLUMN status DROP NOT NULL;
ALTER TABLE ops.intake_logs
ALTER COLUMN judgment_id DROP NOT NULL;
ALTER TABLE ops.intake_logs
ALTER COLUMN error_code DROP NOT NULL;
ALTER TABLE ops.intake_logs
ALTER COLUMN error_details DROP NOT NULL;
ALTER TABLE ops.intake_logs
ALTER COLUMN processing_time_ms DROP NOT NULL;
COMMENT ON TABLE ops.intake_logs IS 'Operational logs for ingest and enforcement workers';
CREATE INDEX IF NOT EXISTS idx_intake_logs_job_id ON ops.intake_logs(job_id);
GRANT ALL ON ops.intake_logs TO service_role;
-- ============================================================================
-- Verification (run manually)
-- ============================================================================
-- SELECT * FROM analytics.v_enforcement_activity;
-- SELECT * FROM public.enforcement_activity_metrics();
-- SELECT enumlabel FROM pg_enum WHERE enumtypid = 'ops.job_type_enum'::regtype;