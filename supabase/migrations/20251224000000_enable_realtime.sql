-- ══════════════════════════════════════════════════════════════════════════════
-- Enable Supabase Realtime Subscriptions
-- ══════════════════════════════════════════════════════════════════════════════
-- 
-- Purpose:
--   Enable real-time database change notifications for the CEO Dashboard and
--   Enforcement Radar. Users will see instant updates when jobs complete or
--   packets are generated, without manual refresh.
--
-- Tables Enabled:
--   1. ops.job_queue - Job processing status updates
--   2. enforcement.draft_packets - Packet generation events
--   3. public.judgments - New judgment ingestion events
--   4. analytics.event_stream - Activity feed events
--
-- Frontend Integration:
--   - useRealtimeSubscription hook subscribes to table changes
--   - Green flash animation on data updates
--   - Live Feed ticker shows real-time events
--
-- ══════════════════════════════════════════════════════════════════════════════
-- ═══════════════════════════════════════════════════════════════════════════════
-- 1. ENABLE REALTIME ON TARGET TABLES
-- ═══════════════════════════════════════════════════════════════════════════════
-- Enable realtime on ops.job_queue
-- This powers the intake station polling replacement
DO $$ BEGIN -- Check if table exists before enabling realtime
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
) THEN -- Enable publication for realtime
ALTER PUBLICATION supabase_realtime
ADD TABLE ops.job_queue;
RAISE NOTICE 'Enabled realtime on ops.job_queue';
ELSE RAISE NOTICE 'ops.job_queue does not exist, skipping realtime';
END IF;
EXCEPTION
WHEN duplicate_object THEN RAISE NOTICE 'ops.job_queue already in publication';
END;
$$;
-- Enable realtime on enforcement.draft_packets  
-- This powers the enforcement action center updates
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'enforcement'
        AND table_name = 'draft_packets'
) THEN ALTER PUBLICATION supabase_realtime
ADD TABLE enforcement.draft_packets;
RAISE NOTICE 'Enabled realtime on enforcement.draft_packets';
ELSE RAISE NOTICE 'enforcement.draft_packets does not exist, skipping realtime';
END IF;
EXCEPTION
WHEN duplicate_object THEN RAISE NOTICE 'enforcement.draft_packets already in publication';
END;
$$;
-- Enable realtime on public.judgments
-- This powers the intake radar and CEO dashboard
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
) THEN ALTER PUBLICATION supabase_realtime
ADD TABLE public.judgments;
RAISE NOTICE 'Enabled realtime on public.judgments';
ELSE RAISE NOTICE 'public.judgments does not exist, skipping realtime';
END IF;
EXCEPTION
WHEN duplicate_object THEN RAISE NOTICE 'public.judgments already in publication';
END;
$$;
-- Enable realtime on analytics.event_stream
-- This powers the live feed ticker
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'analytics'
        AND table_name = 'event_stream'
) THEN ALTER PUBLICATION supabase_realtime
ADD TABLE analytics.event_stream;
RAISE NOTICE 'Enabled realtime on analytics.event_stream';
ELSE RAISE NOTICE 'analytics.event_stream does not exist, skipping realtime';
END IF;
EXCEPTION
WHEN duplicate_object THEN RAISE NOTICE 'analytics.event_stream already in publication';
END;
$$;
-- ═══════════════════════════════════════════════════════════════════════════════
-- 2. LIVE FEED EVENTS VIEW
-- ═══════════════════════════════════════════════════════════════════════════════
-- Create a unified view of recent events for the live feed ticker
-- This aggregates from multiple sources into a single stream
CREATE OR REPLACE VIEW public.v_live_feed_events AS WITH recent_jobs AS (
        SELECT 'job' AS event_type,
            id AS event_id,
            CASE
                WHEN status = 'completed' THEN 'Job completed: ' || COALESCE(job_type, 'processing')
                WHEN status = 'failed' THEN 'Job failed: ' || COALESCE(last_error, 'unknown error')
                WHEN status = 'processing' THEN 'Processing: ' || COALESCE(job_type, 'job')
                ELSE 'Job ' || status
            END AS message,
            COALESCE((payload::jsonb->>'principal')::numeric, 0) AS amount,
            status,
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
            'ingested' AS status,
            created_at AS event_time
        FROM public.judgments
        WHERE created_at > NOW() - INTERVAL '24 hours'
        ORDER BY created_at DESC
        LIMIT 50
    ), recent_packets AS (
        SELECT 'packet' AS event_type,
            id::text AS event_id,
            'Packet generated: ' || COALESCE(packet_type, 'enforcement') AS message,
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
-- Grant access to the view
GRANT SELECT ON public.v_live_feed_events TO anon,
    authenticated,
    service_role;
COMMENT ON VIEW public.v_live_feed_events IS 'Unified stream of recent events for the live feed ticker. Aggregates jobs, judgments, and packets.';
-- ═══════════════════════════════════════════════════════════════════════════════
-- 3. REALTIME BROADCAST RPC (OPTIONAL MANUAL TRIGGER)
-- ═══════════════════════════════════════════════════════════════════════════════
-- Create an RPC to manually broadcast events for testing
CREATE OR REPLACE FUNCTION public.broadcast_live_event(
        p_event_type text,
        p_message text,
        p_amount numeric DEFAULT 0
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE v_payload jsonb;
BEGIN v_payload := jsonb_build_object(
    'event_type',
    p_event_type,
    'message',
    p_message,
    'amount',
    p_amount,
    'event_time',
    NOW()
);
-- Insert into event_stream if it exists
IF EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'analytics'
        AND table_name = 'event_stream'
) THEN
INSERT INTO analytics.event_stream (event_type, event_data, created_at)
VALUES (p_event_type, v_payload, NOW());
END IF;
RETURN v_payload;
END;
$$;
GRANT EXECUTE ON FUNCTION public.broadcast_live_event(text, text, numeric) TO authenticated,
    service_role;
COMMENT ON FUNCTION public.broadcast_live_event IS 'Manually broadcast a live event for testing realtime subscriptions.';
-- ═══════════════════════════════════════════════════════════════════════════════
-- MIGRATION COMPLETE
-- ═══════════════════════════════════════════════════════════════════════════════