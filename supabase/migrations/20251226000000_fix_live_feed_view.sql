-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration: Fix v_live_feed_events enum type casting
-- ═══════════════════════════════════════════════════════════════════════════════
-- Problem: Original view in 20251224000000_enable_realtime.sql failed on prod with:
--   "invalid input value for enum ops.job_type_enum: processing"
--   "UNION types ops.job_status_enum and text cannot be matched"
--
-- This happened because:
--   1. COALESCE(job_type, 'processing') tries to match 'processing' to the enum
--   2. status column was enum in recent_jobs but text in recent_judgments
--
-- Fix: Cast ALL enum columns to text:
--   - job_type::text
--   - status::text (in all CTEs for UNION compatibility)
--   - packet_type::text
-- ═══════════════════════════════════════════════════════════════════════════════
-- Drop the existing (possibly broken) view first
DROP VIEW IF EXISTS public.v_live_feed_events;
-- Recreate with proper type casting for all enum columns
CREATE OR REPLACE VIEW public.v_live_feed_events AS WITH recent_jobs AS (
        SELECT 'job' AS event_type,
            id::text AS event_id,
            CASE
                WHEN status = 'completed' THEN 'Job completed: ' || COALESCE(job_type::text, 'processing')
                WHEN status = 'failed' THEN 'Job failed: ' || COALESCE(last_error, 'unknown error')
                WHEN status = 'processing' THEN 'Processing: ' || COALESCE(job_type::text, 'job')
                ELSE 'Job ' || status::text
            END AS message,
            COALESCE((payload::jsonb->>'principal')::numeric, 0) AS amount,
            status::text AS status,
            COALESCE(updated_at, created_at) AS event_time
        FROM ops.job_queue
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 50
    ), recent_judgments AS (
        SELECT 'judgment' AS event_type,
            id::text AS event_id,
            'New judgment: ' || COALESCE(defendant_name, 'Unknown') AS message,
            COALESCE(judgment_amount, 0) AS amount,
            'ingested'::text AS status,
            created_at AS event_time
        FROM public.judgments
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 50
    ), recent_packets AS (
        SELECT 'packet' AS event_type,
            id::text AS event_id,
            'Packet generated: ' || COALESCE(packet_type::text, 'enforcement') AS message,
            0::numeric AS amount,
            status::text AS status,
            COALESCE(updated_at, created_at) AS event_time
        FROM enforcement.draft_packets
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 50
    ), all_events AS (
        SELECT *
        FROM recent_jobs
        UNION ALL
        SELECT *
        FROM recent_judgments
        UNION ALL
        SELECT *
        FROM recent_packets
    )
SELECT event_type,
    event_id,
    message,
    amount,
    status,
    event_time,
    EXTRACT(
        EPOCH
        FROM (NOW() - event_time)
    ) AS seconds_ago
FROM all_events
ORDER BY event_time DESC
LIMIT 100;
-- Restore grants
GRANT SELECT ON public.v_live_feed_events TO anon,
    authenticated,
    service_role;
COMMENT ON VIEW public.v_live_feed_events IS 'Unified stream of recent events for the live feed ticker. Aggregates jobs, judgments, and packets. Fixed enum casting for job_type/status.';