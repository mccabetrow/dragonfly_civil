-- ============================================================================
-- Migration: 20251211000000_intake_rest_views.sql
-- Purpose: Expose ops schema views to Supabase REST via public shim views
-- ============================================================================
--
-- This migration creates public "shim" views that proxy to ops schema views,
-- enabling the Ops Command Center dashboard to read intake and enrichment
-- health data via Supabase REST API.
--
-- Views created:
--   1. public.v_intake_monitor   → ops.v_intake_monitor
--   2. public.v_enrichment_health → ops.v_enrichment_health
--
-- Both views are granted SELECT to authenticated and service_role.
-- ============================================================================
-- ============================================================================
-- 1. Intake Monitor Shim View
-- ============================================================================
CREATE OR REPLACE VIEW public.v_intake_monitor AS
SELECT *
FROM ops.v_intake_monitor;
COMMENT ON VIEW public.v_intake_monitor IS 'Public shim for ops.v_intake_monitor. Exposes intake batch monitoring to Supabase REST.';
-- Grant SELECT (idempotent via DO block)
DO $$ BEGIN
GRANT SELECT ON public.v_intake_monitor TO authenticated;
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
GRANT SELECT ON public.v_intake_monitor TO service_role;
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- ============================================================================
-- 2. Enrichment Health Shim View
-- ============================================================================
CREATE OR REPLACE VIEW public.v_enrichment_health AS
SELECT *
FROM ops.v_enrichment_health;
COMMENT ON VIEW public.v_enrichment_health IS 'Public shim for ops.v_enrichment_health. Exposes enrichment queue health to Supabase REST.';
-- Grant SELECT (idempotent via DO block)
DO $$ BEGIN
GRANT SELECT ON public.v_enrichment_health TO authenticated;
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
DO $$ BEGIN
GRANT SELECT ON public.v_enrichment_health TO service_role;
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- ============================================================================
-- Done
-- ============================================================================