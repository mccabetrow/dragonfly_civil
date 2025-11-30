-- 0143_ops_monitoring.sql
-- Minimal ops / monitoring schema to support n8n flows and validate_n8n_flows.
BEGIN;
-- 1. Ops metadata key/value store
CREATE TABLE IF NOT EXISTS public.ops_metadata (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    key text NOT NULL,
    value jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE UNIQUE INDEX IF NOT EXISTS ops_metadata_key_unique_idx ON public.ops_metadata (key);
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.ops_metadata TO authenticated,
    service_role;
-- 2. Ops triage alerts table
CREATE TABLE IF NOT EXISTS public.ops_triage_alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    alert_kind text NOT NULL,
    severity text NOT NULL DEFAULT 'info',
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'open',
    acked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    created_by text
);
CREATE INDEX IF NOT EXISTS ops_triage_alerts_status_idx ON public.ops_triage_alerts (status, created_at DESC);
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.ops_triage_alerts TO authenticated,
    service_role;
-- 3. log_event: thin wrapper around add_enforcement_event (generic events)
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
-- 4. log_enforcement_event: specialization for enforcement-related events
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
-- 5. pgmq_metrics: lightweight queue metrics for monitoring
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
-- 6. ops_triage_alerts RPC: fetch & ack
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
COMMIT;