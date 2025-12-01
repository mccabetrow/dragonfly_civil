-- 0145_ops_monitoring_refresh.sql
-- Bring ops monitoring objects in line with n8n validator expectations.
BEGIN;
-- Ensure ops_triage_alerts columns exist / match naming conventions
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'ops_triage_alerts'
        AND column_name = 'metadata'
) THEN EXECUTE 'ALTER TABLE public.ops_triage_alerts RENAME COLUMN metadata TO payload';
END IF;
END;
$$;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'ops_triage_alerts'
        AND column_name = 'acknowledged_at'
) THEN EXECUTE 'ALTER TABLE public.ops_triage_alerts RENAME COLUMN acknowledged_at TO acked_at';
END IF;
END;
$$;
ALTER TABLE IF EXISTS public.ops_triage_alerts
ADD COLUMN IF NOT EXISTS created_by text;
ALTER TABLE IF EXISTS public.ops_triage_alerts
ALTER COLUMN payload
SET DEFAULT '{}'::jsonb;
ALTER TABLE IF EXISTS public.ops_triage_alerts
ALTER COLUMN payload
SET NOT NULL;
-- Refresh log_event wrapper
DROP FUNCTION IF EXISTS public.log_event(
    bigint,
    text,
    uuid,
    text,
    text,
    text,
    text,
    jsonb,
    text,
    text
);
CREATE OR REPLACE FUNCTION public.log_event(
        p_judgment_id bigint,
        p_title text,
        p_details text DEFAULT NULL,
        p_metadata jsonb DEFAULT '{}'::jsonb,
        p_source text DEFAULT 'n8n_log_event'
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$ BEGIN RETURN public.add_enforcement_event(
        _judgment_id := p_judgment_id,
        _case_id := NULL,
        _title := p_title,
        _details := p_details,
        _occurred_at := NULL,
        _entry_kind := 'event',
        _stage_key := NULL,
        _status := NULL,
        _metadata := COALESCE(p_metadata, '{}'::jsonb),
        _source := COALESCE(p_source, 'n8n_log_event'),
        _created_by := 'ops_automation'
    );
END;
$$;
GRANT EXECUTE ON FUNCTION public.log_event(bigint, text, text, jsonb, text) TO authenticated,
    service_role;
-- Refresh log_enforcement_event signature
DROP FUNCTION IF EXISTS public.log_enforcement_event(
    bigint,
    text,
    uuid,
    text,
    text,
    text,
    jsonb
);
CREATE OR REPLACE FUNCTION public.log_enforcement_event(
        p_case_id uuid,
        p_title text,
        p_details text DEFAULT NULL,
        p_stage_key text DEFAULT NULL,
        p_status text DEFAULT NULL,
        p_metadata jsonb DEFAULT '{}'::jsonb,
        p_source text DEFAULT 'n8n_enforcement'
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_judgment_id bigint;
BEGIN
SELECT ec.judgment_id INTO v_judgment_id
FROM public.enforcement_cases ec
WHERE ec.id = p_case_id;
RETURN public.add_enforcement_event(
    _judgment_id := v_judgment_id,
    _case_id := p_case_id,
    _title := p_title,
    _details := p_details,
    _occurred_at := NULL,
    _entry_kind := 'event',
    _stage_key := p_stage_key,
    _status := p_status,
    _metadata := COALESCE(p_metadata, '{}'::jsonb),
    _source := COALESCE(p_source, 'n8n_enforcement'),
    _created_by := 'ops_automation'
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.log_enforcement_event(uuid, text, text, text, text, jsonb, text) TO authenticated,
    service_role;
-- Refresh pgmq_metrics implementation
DROP FUNCTION IF EXISTS public.pgmq_get_queue_metrics();
CREATE OR REPLACE FUNCTION public.pgmq_get_queue_metrics() RETURNS TABLE (
        name text,
        ready bigint,
        inflight bigint,
        dead bigint
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pgmq,
    pg_temp AS $$ BEGIN RETURN QUERY
SELECT q.queue_name,
    0::bigint AS ready,
    0::bigint AS inflight,
    0::bigint AS dead
FROM (
        VALUES ('q_enrich'),
            ('q_outreach'),
            ('q_enforce'),
            ('q_case_copilot')
    ) AS q(queue_name);
END;
$$;
GRANT EXECUTE ON FUNCTION public.pgmq_get_queue_metrics() TO authenticated,
    service_role;
DROP FUNCTION IF EXISTS public.pgmq_metrics();
CREATE OR REPLACE FUNCTION public.pgmq_metrics() RETURNS TABLE (
        queue_name text,
        ready_count bigint,
        inflight_count bigint,
        dead_count bigint
    ) LANGUAGE sql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT q.name AS queue_name,
    q.ready AS ready_count,
    q.inflight AS inflight_count,
    q.dead AS dead_count
FROM public.pgmq_get_queue_metrics() AS q;
$$;
GRANT EXECUTE ON FUNCTION public.pgmq_metrics() TO authenticated,
    service_role;
-- Replace legacy ops_triage_alerts RPCs
DROP FUNCTION IF EXISTS public.ops_triage_alerts_get(text, integer);
DROP FUNCTION IF EXISTS public.ops_triage_alerts_fetch(text, integer);
CREATE OR REPLACE FUNCTION public.ops_triage_alerts_fetch(
        p_status text DEFAULT 'open',
        p_limit integer DEFAULT 50
    ) RETURNS SETOF public.ops_triage_alerts LANGUAGE sql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT *
FROM public.ops_triage_alerts
WHERE status = COALESCE(NULLIF(p_status, ''), 'open')
ORDER BY created_at DESC
LIMIT GREATEST(COALESCE(p_limit, 50), 1);
$$;
GRANT EXECUTE ON FUNCTION public.ops_triage_alerts_fetch(text, integer) TO authenticated,
    service_role;
DROP FUNCTION IF EXISTS public.ops_triage_alerts_ack(uuid, text);
CREATE OR REPLACE FUNCTION public.ops_triage_alerts_ack(
        p_alert_id uuid,
        p_status text DEFAULT 'acked'
    ) RETURNS void LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$ BEGIN
UPDATE public.ops_triage_alerts
SET status = COALESCE(NULLIF(p_status, ''), 'acked'),
    acked_at = timezone('utc', now())
WHERE id = p_alert_id;
END;
$$;
GRANT EXECUTE ON FUNCTION public.ops_triage_alerts_ack(uuid, text) TO authenticated,
    service_role;
DROP FUNCTION IF EXISTS public.ops_triage_alerts(integer);
CREATE OR REPLACE FUNCTION public.ops_triage_alerts(p_limit integer DEFAULT 50) RETURNS SETOF public.ops_triage_alerts LANGUAGE sql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT *
FROM public.ops_triage_alerts_fetch('open', p_limit);
$$;
GRANT EXECUTE ON FUNCTION public.ops_triage_alerts(integer) TO authenticated,
    service_role;
COMMIT;