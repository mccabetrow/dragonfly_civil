-- 20251209_promote_enforcement_to_prod.sql
-- ============================================================================
-- Goal: Bring PROD up to DEV parity for enforcement/ops schema objects.
-- 
-- Created: 2025-12-09
-- Author: Dragonfly Civil Release Engineering
--
-- This migration creates:
--   1. Schemas: enforcement, ops
--   2. Enum types in ops and enforcement schemas
--   3. Tables: enforcement_cases, enforcement_events, enforcement_history,
--              enforcement_timeline, plaintiff_tasks
--   4. Tables: ops.ingest_batches, ops.job_queue
--   5. Tables: enforcement.enforcement_plans, enforcement.draft_packets,
--              enforcement.offers
--   6. Views: v_enforcement_overview, v_enforcement_recent, v_enforcement_timeline,
--             v_enforcement_case_summary, enforcement.v_radar, etc.
--   7. RPCs: queue_job, spawn_enforcement_flow, generate_enforcement_tasks, etc.
--
-- Constraints:
--   - Idempotent: uses IF NOT EXISTS and CREATE OR REPLACE
--   - Safe: no destructive DROP TABLE without guards
--   - Exact DDL from DEV
-- ============================================================================
BEGIN;
-- ============================================================================
-- 1) SCHEMAS
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS enforcement;
CREATE SCHEMA IF NOT EXISTS ops;
-- ============================================================================
-- 2) ENUM TYPES
-- ============================================================================
-- ops.intake_source_type
DO $$ BEGIN CREATE TYPE ops.intake_source_type AS ENUM (
    'simplicity',
    'jbi',
    'manual',
    'csv_upload',
    'api'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- ops.job_status_enum
DO $$ BEGIN CREATE TYPE ops.job_status_enum AS ENUM (
    'pending',
    'processing',
    'completed',
    'failed'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- ops.job_type_enum
DO $$ BEGIN CREATE TYPE ops.job_type_enum AS ENUM (
    'enrich_tlo',
    'enrich_idicore',
    'generate_pdf'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- enforcement.offer_status
DO $$ BEGIN CREATE TYPE enforcement.offer_status AS ENUM (
    'offered',
    'accepted',
    'rejected',
    'negotiation'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- enforcement.offer_type
DO $$ BEGIN CREATE TYPE enforcement.offer_type AS ENUM ('purchase', 'contingency');
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- public.enforcement_task_severity
DO $$ BEGIN CREATE TYPE public.enforcement_task_severity AS ENUM ('low', 'medium', 'high');
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- public.enforcement_task_kind
DO $$ BEGIN CREATE TYPE public.enforcement_task_kind AS ENUM (
    'enforcement_phone_attempt',
    'enforcement_phone_follow_up',
    'enforcement_mailer',
    'enforcement_demand_letter',
    'enforcement_wage_garnishment_prep',
    'enforcement_bank_levy_prep',
    'enforcement_skiptrace_refresh'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- ============================================================================
-- 3) PUBLIC SCHEMA TABLES
-- ============================================================================
-- public.enforcement_cases
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'enforcement_cases'
) THEN CREATE TABLE public.enforcement_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id bigint NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    plaintiff_id uuid REFERENCES public.plaintiffs(id) ON DELETE
    SET NULL,
        case_number text,
        opened_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
        current_stage text,
        status text NOT NULL DEFAULT 'open',
        assigned_to text,
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
        updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX enforcement_cases_judgment_idx ON public.enforcement_cases(judgment_id);
CREATE INDEX enforcement_cases_status_idx ON public.enforcement_cases(status);
CREATE INDEX enforcement_cases_plaintiff_idx ON public.enforcement_cases(plaintiff_id);
CREATE UNIQUE INDEX enforcement_cases_judgment_unique_idx ON public.enforcement_cases(judgment_id);
END IF;
END $$;
-- public.enforcement_events
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'enforcement_events'
) THEN CREATE TABLE public.enforcement_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES public.enforcement_cases(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    event_date timestamptz NOT NULL DEFAULT timezone('utc', now()),
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE INDEX enforcement_events_case_idx ON public.enforcement_events(case_id);
END IF;
END $$;
-- public.enforcement_history
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'enforcement_history'
) THEN CREATE TABLE public.enforcement_history (
    id bigserial PRIMARY KEY,
    judgment_id bigint NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    stage text NOT NULL,
    note text,
    changed_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    changed_by text
);
CREATE INDEX idx_enforcement_history_judgment_id ON public.enforcement_history(judgment_id);
END IF;
END $$;
-- public.enforcement_timeline
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'enforcement_timeline'
) THEN CREATE TABLE public.enforcement_timeline (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL,
    judgment_id bigint NOT NULL,
    plaintiff_id uuid,
    entry_kind text NOT NULL,
    stage_key text,
    status text,
    source text NOT NULL DEFAULT 'system',
    title text NOT NULL,
    details text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    created_by text
);
CREATE INDEX idx_enforcement_timeline_case_id ON public.enforcement_timeline(case_id);
CREATE INDEX idx_enforcement_timeline_judgment_id ON public.enforcement_timeline(judgment_id);
END IF;
END $$;
-- public.plaintiff_tasks
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_tasks'
) THEN CREATE TABLE public.plaintiff_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs(id) ON DELETE CASCADE,
    case_id uuid,
    kind text NOT NULL,
    task_code public.enforcement_task_kind,
    severity public.enforcement_task_severity NOT NULL DEFAULT 'medium',
    status text NOT NULL DEFAULT 'open',
    due_at timestamptz,
    completed_at timestamptz,
    closed_at timestamptz,
    result text,
    note text,
    assignee text DEFAULT 'unassigned',
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    created_by text
);
CREATE INDEX idx_plaintiff_tasks_plaintiff_id ON public.plaintiff_tasks(plaintiff_id);
CREATE INDEX idx_plaintiff_tasks_case_id ON public.plaintiff_tasks(case_id);
CREATE INDEX idx_plaintiff_tasks_status ON public.plaintiff_tasks(status);
END IF;
END $$;
-- ============================================================================
-- 4) OPS SCHEMA TABLES
-- ============================================================================
-- ops.ingest_batches
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'ops'
        AND table_name = 'ingest_batches'
) THEN CREATE TABLE ops.ingest_batches (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    filename text NOT NULL,
    row_count_raw integer NOT NULL DEFAULT 0,
    row_count_valid integer NOT NULL DEFAULT 0,
    row_count_invalid integer NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending',
    error_summary text,
    created_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    created_by text,
    stats jsonb DEFAULT '{}'::jsonb,
    started_at timestamptz,
    completed_at timestamptz,
    worker_id text,
    updated_at timestamptz DEFAULT now()
);
CREATE INDEX idx_ops_ingest_batches_status ON ops.ingest_batches(status);
END IF;
END $$;
-- ops.job_queue
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
) THEN CREATE TABLE ops.job_queue (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_type ops.job_type_enum NOT NULL,
    payload jsonb NOT NULL,
    status ops.job_status_enum NOT NULL DEFAULT 'pending',
    attempts integer NOT NULL DEFAULT 0,
    locked_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_ops_job_queue_status ON ops.job_queue(status);
CREATE INDEX idx_ops_job_queue_job_type ON ops.job_queue(job_type);
END IF;
END $$;
-- ============================================================================
-- 5) ENFORCEMENT SCHEMA TABLES
-- ============================================================================
-- enforcement.enforcement_plans
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'enforcement'
        AND table_name = 'enforcement_plans'
) THEN CREATE TABLE enforcement.enforcement_plans (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL,
    plan_status text NOT NULL DEFAULT 'pending',
    priority integer NOT NULL DEFAULT 0,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
END IF;
END $$;
-- enforcement.draft_packets
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'enforcement'
        AND table_name = 'draft_packets'
) THEN CREATE TABLE enforcement.draft_packets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL,
    packet_type text NOT NULL,
    status text NOT NULL DEFAULT 'draft',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
END IF;
END $$;
-- enforcement.offers
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.tables
    WHERE table_schema = 'enforcement'
        AND table_name = 'offers'
) THEN CREATE TABLE enforcement.offers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id bigint NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    offer_amount numeric NOT NULL,
    offer_type enforcement.offer_type NOT NULL,
    status enforcement.offer_status NOT NULL DEFAULT 'offered',
    operator_notes text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_enforcement_offers_judgment_id ON enforcement.offers(judgment_id);
CREATE INDEX idx_enforcement_offers_status ON enforcement.offers(status);
END IF;
END $$;
-- ============================================================================
-- 6) VIEWS (CREATE OR REPLACE for idempotency)
-- ============================================================================
-- v_enforcement_overview
CREATE OR REPLACE VIEW public.v_enforcement_overview AS
SELECT enforcement_stage,
    count(*) AS count,
    sum(judgment_amount) AS total_value
FROM judgments j
WHERE status NOT IN ('satisfied', 'dismissed')
GROUP BY enforcement_stage;
-- v_enforcement_recent
CREATE OR REPLACE VIEW public.v_enforcement_recent AS
SELECT id,
    case_number,
    defendant_name,
    judgment_amount,
    enforcement_stage,
    updated_at,
    status
FROM judgments j
WHERE updated_at >= (CURRENT_DATE - INTERVAL '7 days')
    AND enforcement_stage IS NOT NULL
ORDER BY updated_at DESC
LIMIT 50;
-- v_enforcement_timeline
DROP VIEW IF EXISTS public.v_enforcement_timeline;
CREATE VIEW public.v_enforcement_timeline AS
SELECT et.id,
    et.case_id,
    et.judgment_id,
    et.plaintiff_id,
    et.entry_kind,
    et.stage_key,
    et.status,
    et.source,
    et.title,
    et.details,
    et.metadata,
    et.occurred_at,
    et.created_at,
    j.case_number,
    p.name AS plaintiff_name
FROM enforcement_timeline et
    LEFT JOIN judgments j ON j.id = et.judgment_id
    LEFT JOIN plaintiffs p ON p.id = et.plaintiff_id
ORDER BY et.occurred_at DESC;
-- v_enforcement_case_summary
DROP VIEW IF EXISTS public.v_enforcement_case_summary;
CREATE VIEW public.v_enforcement_case_summary AS WITH latest_event AS (
    SELECT DISTINCT ON (e.case_id) e.case_id,
        e.event_type,
        e.event_date,
        e.notes,
        e.metadata
    FROM enforcement_events e
    ORDER BY e.case_id,
        e.event_date DESC,
        e.created_at DESC
),
case_rows AS (
    SELECT ec.id AS case_id,
        ec.judgment_id,
        ec.case_number,
        ec.opened_at,
        ec.current_stage,
        ec.status,
        ec.assigned_to,
        ec.metadata,
        ec.created_at,
        ec.updated_at,
        j.judgment_amount,
        j.case_number AS judgment_case_number,
        j.plaintiff_id,
        p.name AS plaintiff_name
    FROM enforcement_cases ec
        JOIN judgments j ON j.id = ec.judgment_id
        LEFT JOIN plaintiffs p ON p.id = j.plaintiff_id
)
SELECT cr.case_id,
    cr.judgment_id,
    COALESCE(cr.case_number, cr.judgment_case_number) AS case_number,
    cr.opened_at,
    cr.current_stage,
    cr.status,
    cr.assigned_to,
    cr.metadata,
    cr.created_at,
    cr.updated_at,
    cr.judgment_amount,
    cr.plaintiff_id,
    cr.plaintiff_name,
    le.event_type AS latest_event_type,
    le.event_date AS latest_event_date,
    le.notes AS latest_event_note,
    le.metadata AS latest_event_metadata
FROM case_rows cr
    LEFT JOIN latest_event le ON le.case_id = cr.case_id;
-- enforcement.v_radar
CREATE OR REPLACE VIEW enforcement.v_radar AS
SELECT id,
    case_number,
    plaintiff_name,
    defendant_name,
    judgment_amount,
    court,
    county,
    COALESCE(judgment_date, entry_date) AS judgment_date,
    collectability_score,
    status,
    enforcement_stage,
    CASE
        WHEN collectability_score >= 70
        AND judgment_amount >= 10000 THEN 'BUY_CANDIDATE'
        WHEN collectability_score >= 40 THEN 'CONTINGENCY'
        WHEN collectability_score IS NULL THEN 'ENRICHMENT_PENDING'
        ELSE 'LOW_PRIORITY'
    END AS offer_strategy,
    created_at,
    updated_at
FROM judgments j
WHERE COALESCE(status, '') NOT IN ('SATISFIED', 'EXPIRED')
ORDER BY collectability_score DESC NULLS LAST,
    judgment_amount DESC;
-- enforcement.v_enforcement_pipeline_status
CREATE OR REPLACE VIEW enforcement.v_enforcement_pipeline_status AS
SELECT enforcement_stage,
    count(*) AS case_count,
    sum(judgment_amount) AS total_amount,
    avg(collectability_score) AS avg_score,
    min(created_at) AS oldest_case,
    max(updated_at) AS latest_activity
FROM judgments j
WHERE status NOT IN ('satisfied', 'dismissed', 'expired')
GROUP BY enforcement_stage
ORDER BY CASE
        enforcement_stage
        WHEN 'discovery' THEN 1
        WHEN 'asset_search' THEN 2
        WHEN 'levy_pending' THEN 3
        WHEN 'garnishment' THEN 4
        WHEN 'negotiation' THEN 5
        ELSE 99
    END;
-- enforcement.v_plaintiff_call_queue
CREATE OR REPLACE VIEW enforcement.v_plaintiff_call_queue AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.tier,
    p.status,
    pc.phone,
    pc.email,
    count(j.id) AS judgment_count,
    sum(j.judgment_amount) AS total_balance,
    max(j.updated_at) AS last_activity,
    CASE
        WHEN p.tier = 'platinum' THEN 1
        WHEN p.tier = 'gold' THEN 2
        WHEN p.tier = 'silver' THEN 3
        ELSE 4
    END AS priority_rank
FROM plaintiffs p
    LEFT JOIN plaintiff_contacts pc ON pc.plaintiff_id = p.id
    LEFT JOIN judgments j ON j.plaintiff_id = p.id
WHERE p.status IN ('active', 'pending_outreach', 'follow_up')
GROUP BY p.id,
    p.name,
    p.tier,
    p.status,
    pc.phone,
    pc.email
ORDER BY CASE
        WHEN p.tier = 'platinum' THEN 1
        WHEN p.tier = 'gold' THEN 2
        WHEN p.tier = 'silver' THEN 3
        ELSE 4
    END,
    sum(j.judgment_amount) DESC NULLS LAST;
-- enforcement.v_offer_stats
CREATE OR REPLACE VIEW enforcement.v_offer_stats AS
SELECT judgment_id,
    count(*) AS total_offers,
    count(*) FILTER (
        WHERE status = 'offered'
    ) AS offers_made,
    count(*) FILTER (
        WHERE status = 'accepted'
    ) AS offers_accepted,
    count(*) FILTER (
        WHERE status = 'rejected'
    ) AS offers_rejected,
    count(*) FILTER (
        WHERE status = 'negotiation'
    ) AS offers_in_negotiation,
    max(offer_amount) AS max_offer_amount,
    min(offer_amount) AS min_offer_amount,
    max(created_at) AS last_offer_at
FROM enforcement.offers
GROUP BY judgment_id;
-- enforcement.v_offer_metrics
CREATE OR REPLACE VIEW enforcement.v_offer_metrics AS
SELECT count(*) AS total_offers,
    count(*) FILTER (
        WHERE status = 'accepted'
    ) AS accepted,
    count(*) FILTER (
        WHERE status = 'rejected'
    ) AS rejected,
    count(*) FILTER (
        WHERE status = 'negotiation'
    ) AS negotiation,
    count(*) FILTER (
        WHERE status = 'offered'
    ) AS pending,
    CASE
        WHEN count(*) > 0 THEN round(
            (
                count(*) FILTER (
                    WHERE status = 'accepted'
                )::numeric / count(*)::numeric
            ) * 100,
            2
        )
        ELSE 0
    END AS conversion_rate_pct,
    sum(offer_amount) FILTER (
        WHERE status = 'accepted'
    ) AS total_accepted_value,
    avg(offer_amount) FILTER (
        WHERE status = 'accepted'
    ) AS avg_accepted_value
FROM enforcement.offers;
-- ============================================================================
-- 7) RPCs (FUNCTIONS)
-- ============================================================================
-- public.queue_job(jsonb)
CREATE OR REPLACE FUNCTION public.queue_job(payload jsonb) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'public',
    'pg_temp' AS $function$
DECLARE v_kind text;
v_idempotency_key text;
v_body jsonb;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_body := coalesce(payload->'payload', '{}'::jsonb);
IF v_kind IS NULL THEN RAISE EXCEPTION 'queue_job: missing kind in payload';
END IF;
IF v_kind NOT IN (
    'enrich',
    'outreach',
    'enforce',
    'case_copilot',
    'collectability',
    'judgment_enrich',
    'enforcement_action',
    'tier_assignment'
) THEN RAISE EXCEPTION 'queue_job: unsupported kind %',
v_kind;
END IF;
IF v_idempotency_key IS NULL
OR length(v_idempotency_key) = 0 THEN RAISE EXCEPTION 'queue_job: missing idempotency_key';
END IF;
RETURN pgmq.send(
    v_kind,
    jsonb_build_object(
        'payload',
        v_body,
        'idempotency_key',
        v_idempotency_key,
        'kind',
        v_kind,
        'enqueued_at',
        now()
    )
);
END;
$function$;
-- public.generate_enforcement_tasks(uuid)
DROP FUNCTION IF EXISTS public.generate_enforcement_tasks(uuid);
CREATE FUNCTION public.generate_enforcement_tasks(p_case_id uuid) RETURNS TABLE(
    task_id uuid,
    kind text,
    severity public.enforcement_task_severity
) LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'public',
    'pg_temp' AS $function$
DECLARE v_plaintiff_id uuid;
v_task_id uuid;
v_task_record RECORD;
v_due_offset INTERVAL;
v_task_configs CONSTANT jsonb := '[
        {"kind": "phone_attempt", "severity": "high", "offset_days": 0},
        {"kind": "phone_follow_up", "severity": "medium", "offset_days": 3},
        {"kind": "mailer", "severity": "low", "offset_days": 7},
        {"kind": "demand_letter", "severity": "high", "offset_days": 14},
        {"kind": "wage_garnishment_prep", "severity": "medium", "offset_days": 21},
        {"kind": "bank_levy_prep", "severity": "medium", "offset_days": 28},
        {"kind": "skiptrace_refresh", "severity": "low", "offset_days": 30}
    ]'::jsonb;
BEGIN -- Get plaintiff_id from enforcement_cases
SELECT ec.plaintiff_id INTO v_plaintiff_id
FROM public.enforcement_cases ec
WHERE ec.id = p_case_id;
IF v_plaintiff_id IS NULL THEN RAISE EXCEPTION 'generate_enforcement_tasks: case_id % not found or missing plaintiff_id',
p_case_id USING ERRCODE = 'P0002';
END IF;
-- Create tasks based on config
FOR v_task_record IN
SELECT *
FROM jsonb_array_elements(v_task_configs) LOOP v_due_offset := (v_task_record.value->>'offset_days')::int * INTERVAL '1 day';
INSERT INTO public.plaintiff_tasks (
        plaintiff_id,
        case_id,
        kind,
        task_code,
        severity,
        status,
        due_at,
        note,
        created_by
    )
VALUES (
        v_plaintiff_id,
        p_case_id,
        'enforcement_' || (v_task_record.value->>'kind'),
        ('enforcement_' || (v_task_record.value->>'kind'))::public.enforcement_task_kind,
        (v_task_record.value->>'severity')::public.enforcement_task_severity,
        'open',
        timezone('utc', now()) + v_due_offset,
        format(
            'Auto-generated enforcement task: %s',
            v_task_record.value->>'kind'
        ),
        'system'
    )
RETURNING id INTO v_task_id;
task_id := v_task_id;
kind := 'enforcement_' || (v_task_record.value->>'kind');
severity := (v_task_record.value->>'severity')::public.enforcement_task_severity;
RETURN NEXT;
END LOOP;
RETURN;
END;
$function$;
-- public.spawn_enforcement_flow(text, text)
CREATE OR REPLACE FUNCTION public.spawn_enforcement_flow(
        p_case_number text,
        p_template_code text DEFAULT 'INFO_SUBPOENA_FLOW'
    ) RETURNS uuid [] LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'public',
    'pg_temp' AS $function$
DECLARE v_judgment_id bigint;
v_case_id uuid;
v_plaintiff_id uuid;
v_created_ids uuid [];
BEGIN -- Lookup judgment
SELECT id,
    plaintiff_id INTO v_judgment_id,
    v_plaintiff_id
FROM public.judgments
WHERE case_number = p_case_number
LIMIT 1;
IF v_judgment_id IS NULL THEN RAISE EXCEPTION 'spawn_enforcement_flow: judgment not found for case_number %',
p_case_number USING ERRCODE = 'P0002';
END IF;
-- Upsert enforcement_case
INSERT INTO public.enforcement_cases (
        judgment_id,
        plaintiff_id,
        case_number,
        status,
        current_stage
    )
VALUES (
        v_judgment_id,
        v_plaintiff_id,
        p_case_number,
        'open',
        'enforcement_active'
    ) ON CONFLICT (judgment_id) DO
UPDATE
SET status = 'open',
    current_stage = COALESCE(
        EXCLUDED.current_stage,
        enforcement_cases.current_stage
    ),
    updated_at = timezone('utc', now())
RETURNING id INTO v_case_id;
-- Log timeline entry
INSERT INTO public.enforcement_timeline (
        case_id,
        judgment_id,
        plaintiff_id,
        entry_kind,
        stage_key,
        title,
        details
    )
VALUES (
        v_case_id,
        v_judgment_id,
        v_plaintiff_id,
        'stage_change',
        p_template_code,
        'Enforcement flow spawned',
        format('Template: %s', p_template_code)
    );
-- Generate tasks via existing RPC
SELECT array_agg(task_id) INTO v_created_ids
FROM public.generate_enforcement_tasks(v_case_id);
RETURN COALESCE(v_created_ids, ARRAY []::uuid []);
END;
$function$;
-- public.set_enforcement_stage(bigint, text, text, text)
CREATE OR REPLACE FUNCTION public.set_enforcement_stage(
        _judgment_id bigint,
        _new_stage text,
        _note text DEFAULT NULL,
        _changed_by text DEFAULT NULL
    ) RETURNS judgments LANGUAGE plpgsql SECURITY DEFINER AS $function$
DECLARE allowed_stages constant text [] := ARRAY [
        'levy_issued', 'payment_plan', 'waiting_payment', 'pre_enforcement',
        'paperwork_filed', 'collected', 'closed_no_recovery'
    ];
normalized_stage text;
current_row public.judgments %ROWTYPE;
BEGIN IF _judgment_id IS NULL THEN RAISE EXCEPTION 'judgment id is required';
END IF;
normalized_stage := trim(lower(COALESCE(_new_stage, '')));
IF normalized_stage = '' THEN RAISE EXCEPTION 'new stage is required';
END IF;
IF NOT normalized_stage = ANY(allowed_stages) THEN RAISE EXCEPTION 'invalid enforcement stage: %',
_new_stage;
END IF;
SELECT * INTO current_row
FROM public.judgments
WHERE id = _judgment_id FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'judgment % not found',
_judgment_id;
END IF;
IF COALESCE(current_row.enforcement_stage, '') = normalized_stage THEN RETURN current_row;
END IF;
-- Log history
INSERT INTO public.enforcement_history (judgment_id, stage, note, changed_by)
VALUES (
        _judgment_id,
        normalized_stage,
        _note,
        _changed_by
    );
-- Update judgment
UPDATE public.judgments
SET enforcement_stage = normalized_stage,
    updated_at = timezone('utc', now())
WHERE id = _judgment_id
RETURNING * INTO current_row;
RETURN current_row;
END;
$function$;
-- public.dequeue_job(text)
DROP FUNCTION IF EXISTS public.dequeue_job(text);
CREATE FUNCTION public.dequeue_job(queue_name text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path TO 'public',
    'pg_temp' AS $function$
DECLARE msg record;
BEGIN
SELECT * INTO msg
FROM pgmq.read(queue_name, 30, 1)
LIMIT 1;
IF msg IS NULL THEN RETURN NULL;
END IF;
RETURN jsonb_build_object(
    'msg_id',
    msg.msg_id,
    'vt',
    msg.vt,
    'read_ct',
    msg.read_ct,
    'enqueued_at',
    msg.enqueued_at,
    'payload',
    msg.message,
    'body',
    msg.message
);
END;
$function$;
-- ============================================================================
-- COMMIT
-- ============================================================================
COMMIT;