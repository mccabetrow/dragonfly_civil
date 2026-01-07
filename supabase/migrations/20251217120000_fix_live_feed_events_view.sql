-- ═══════════════════════════════════════════════════════════════════════════════
-- Migration: Fix v_live_feed_events enum casting (take 2)
-- ═══════════════════════════════════════════════════════════════════════════════
-- Problem: Prod migration still fails with:
--   "invalid input value for enum ops.job_type_enum: processing"
--
-- Root Cause: The CASE statement compares enum columns to text literals before
-- the final ::text cast is applied. Postgres tries to cast the text literal
-- to the enum type for comparison, causing the error.
--
-- Fix: Cast enum columns to text IMMEDIATELY at selection, before any CASE logic.
-- Use a subquery to ensure the cast happens first, then do all string comparisons.
--
-- Also: Handle NULL job_type gracefully to avoid "processing" literal entirely.
-- ═══════════════════════════════════════════════════════════════════════════════
-- Drop the existing view first to ensure clean replacement
DROP VIEW IF EXISTS public.v_live_feed_events;
-- Recreate with ALL enum fields cast to text BEFORE any comparisons
CREATE OR REPLACE VIEW public.v_live_feed_events AS WITH recent_jobs AS (
        -- Inner subquery casts enums to text first
        SELECT 'job' AS event_type,
            id::text AS event_id,
            CASE
                WHEN status_txt = 'completed' THEN 'Job completed: ' || COALESCE(job_type_txt, 'unknown')
                WHEN status_txt = 'failed' THEN 'Job failed: ' || COALESCE(last_error, 'unknown error')
                WHEN status_txt = 'processing' THEN 'Processing: ' || COALESCE(job_type_txt, 'job')
                WHEN status_txt = 'pending' THEN 'Pending: ' || COALESCE(job_type_txt, 'job')
                ELSE 'Job ' || COALESCE(status_txt, 'unknown')
            END AS message,
            COALESCE((payload::jsonb->>'principal')::numeric, 0) AS amount,
            COALESCE(status_txt, 'unknown') AS status,
            COALESCE(updated_at, created_at) AS event_time
        FROM (
                SELECT id,
                    job_type::text AS job_type_txt,
                    status::text AS status_txt,
                    last_error,
                    payload,
                    updated_at,
                    created_at
                FROM ops.job_queue
                WHERE created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 50
            ) jobs_casted
    ), recent_judgments AS (
        SELECT 'judgment' AS event_type,
            id::text AS event_id,
            'New judgment: ' || COALESCE(defendant_name, 'Unknown') AS message,
            COALESCE(judgment_amount, 0) AS amount,
            'ingested' AS status,
            created_at AS event_time
        FROM public.judgments
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 50
    ), recent_packets AS (
        SELECT 'packet' AS event_type,
            id::text AS event_id,
            'Packet generated: ' || COALESCE(packet_type_txt, 'enforcement') AS message,
            0::numeric AS amount,
            COALESCE(status_txt, 'unknown') AS status,
            COALESCE(updated_at, created_at) AS event_time
        FROM (
                SELECT id,
                    packet_type::text AS packet_type_txt,
                    status::text AS status_txt,
                    updated_at,
                    created_at
                FROM enforcement.draft_packets
                WHERE created_at > NOW() - INTERVAL '24 hours'
                ORDER BY created_at DESC
                LIMIT 50
            ) packets_casted
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
COMMENT ON VIEW public.v_live_feed_events IS 'Unified stream of recent events for the live feed ticker. Aggregates jobs, judgments, and packets. All enum fields cast to text via subquery to avoid enum literal comparison errors.';
