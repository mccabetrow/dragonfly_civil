-- 0112_dashboard_views_and_rpcs.sql
-- Recreate dashboard-critical views plus the worker RPCs that doctor + schema checks expect.
-- migrate:up
BEGIN;
-- Refresh RPCs that power worker queues.
DROP FUNCTION IF EXISTS public.dequeue_job(text);
DROP FUNCTION IF EXISTS public.pgmq_delete(text, bigint);
CREATE OR REPLACE FUNCTION public.pgmq_delete(queue_name text, msg_id bigint) RETURNS boolean LANGUAGE sql SECURITY DEFINER
SET search_path = public,
    pgmq AS $$
SELECT pgmq.delete(queue_name, msg_id);
$$;
GRANT EXECUTE ON FUNCTION public.pgmq_delete(text, bigint) TO anon;
GRANT EXECUTE ON FUNCTION public.pgmq_delete(text, bigint) TO authenticated;
GRANT EXECUTE ON FUNCTION public.pgmq_delete(text, bigint) TO service_role;
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE msg record;
BEGIN IF kind IS NULL
OR length(trim(kind)) = 0 THEN RAISE EXCEPTION 'dequeue_job: missing kind';
END IF;
IF kind NOT IN ('enrich', 'outreach', 'enforce', 'case_copilot') THEN RAISE EXCEPTION 'dequeue_job: unsupported kind %',
kind;
END IF;
SELECT * INTO msg
FROM pgmq.read(kind, 1, 30);
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
$$;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
-- Drop dependent views in leaf-to-root order before recreating them.
DROP VIEW IF EXISTS public.v_plaintiff_call_queue;
DROP VIEW IF EXISTS public.v_plaintiff_open_tasks;
DROP VIEW IF EXISTS public.v_plaintiffs_jbi_900;
DROP VIEW IF EXISTS public.v_enforcement_recent;
DROP VIEW IF EXISTS public.v_enforcement_overview;
DROP VIEW IF EXISTS public.v_judgment_pipeline;
DROP VIEW IF EXISTS public.v_metrics_enforcement;
DROP VIEW IF EXISTS public.v_metrics_pipeline;
DROP VIEW IF EXISTS public.v_metrics_intake_daily;
DROP VIEW IF EXISTS public.v_plaintiffs_overview;
DROP VIEW IF EXISTS public.v_collectability_snapshot;
-- Expose collectability snapshot via the public schema for dashboards.
CREATE OR REPLACE VIEW public.v_collectability_snapshot AS
SELECT *
FROM judgments.v_collectability_snapshot;
REVOKE ALL ON public.v_collectability_snapshot
FROM public;
REVOKE ALL ON public.v_collectability_snapshot
FROM anon;
REVOKE ALL ON public.v_collectability_snapshot
FROM authenticated;
GRANT SELECT ON public.v_collectability_snapshot TO anon,
    authenticated,
    service_role;
-- Core plaintiffs view consumed by most dashboards.
CREATE OR REPLACE VIEW public.v_plaintiffs_overview AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount,
    COUNT(DISTINCT j.id) AS case_count
FROM public.plaintiffs p
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
GROUP BY p.id,
    p.name,
    p.firm_name,
    p.status;
GRANT SELECT ON public.v_plaintiffs_overview TO anon,
    authenticated,
    service_role;
-- Enforcement rollups + recents.
CREATE OR REPLACE VIEW public.v_enforcement_overview AS
SELECT j.enforcement_stage,
    cs.collectability_tier,
    COUNT(*) AS case_count,
    COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount
FROM public.judgments j
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
GROUP BY j.enforcement_stage,
    cs.collectability_tier;
GRANT SELECT ON public.v_enforcement_overview TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_enforcement_recent AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id::text AS plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
ORDER BY j.enforcement_stage_updated_at DESC,
    j.id DESC;
GRANT SELECT ON public.v_enforcement_recent TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
SELECT j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id::text AS plaintiff_id,
    COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.enforcement_stage,
    j.enforcement_stage_updated_at,
    cs.collectability_tier,
    cs.age_days AS collectability_age_days,
    cs.last_enriched_at,
    cs.last_enrichment_status
FROM public.judgments j
    LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number;
GRANT SELECT ON public.v_judgment_pipeline TO anon,
    authenticated,
    service_role;
-- Executive metrics views.
CREATE OR REPLACE VIEW public.v_metrics_intake_daily AS WITH import_rows AS (
        SELECT date_trunc('day', timezone('utc', started_at))::date AS activity_date,
            COALESCE(NULLIF(lower(source_system), ''), 'unknown') AS source_system,
            COUNT(*) AS import_count
        FROM public.import_runs
        GROUP BY 1,
            2
    ),
    plaintiff_rows AS (
        SELECT date_trunc('day', timezone('utc', created_at))::date AS activity_date,
            COALESCE(NULLIF(lower(source_system), ''), 'unknown') AS source_system,
            COUNT(*) AS plaintiff_count
        FROM public.plaintiffs
        GROUP BY 1,
            2
    ),
    judgment_rows AS (
        SELECT date_trunc(
                'day',
                timezone(
                    'utc',
                    COALESCE(j.created_at, j.entry_date::timestamptz, now())
                )
            )::date AS activity_date,
            COALESCE(NULLIF(lower(p.source_system), ''), 'unknown') AS source_system,
            COUNT(*) AS judgment_count,
            COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount
        FROM public.judgments j
            LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
        GROUP BY 1,
            2
    ),
    combined_keys AS (
        SELECT activity_date,
            source_system
        FROM import_rows
        UNION
        SELECT activity_date,
            source_system
        FROM plaintiff_rows
        UNION
        SELECT activity_date,
            source_system
        FROM judgment_rows
    )
SELECT k.activity_date,
    k.source_system,
    COALESCE(i.import_count, 0) AS import_count,
    COALESCE(pl.plaintiff_count, 0) AS plaintiff_count,
    COALESCE(j.judgment_count, 0) AS judgment_count,
    COALESCE(j.total_judgment_amount, 0)::numeric AS total_judgment_amount
FROM combined_keys k
    LEFT JOIN import_rows i ON i.activity_date = k.activity_date
    AND i.source_system = k.source_system
    LEFT JOIN plaintiff_rows pl ON pl.activity_date = k.activity_date
    AND pl.source_system = k.source_system
    LEFT JOIN judgment_rows j ON j.activity_date = k.activity_date
    AND j.source_system = k.source_system
ORDER BY k.activity_date DESC,
    k.source_system;
GRANT SELECT ON public.v_metrics_intake_daily TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_metrics_pipeline AS
SELECT COALESCE(
        NULLIF(lower(j.enforcement_stage), ''),
        'unknown'
    ) AS enforcement_stage,
    COALESCE(
        NULLIF(lower(cs.collectability_tier), ''),
        'unscored'
    ) AS collectability_tier,
    COUNT(*) AS judgment_count,
    COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount,
    COALESCE(AVG(j.judgment_amount), 0)::numeric AS average_judgment_amount,
    MAX(j.enforcement_stage_updated_at) AS latest_stage_update
FROM public.judgments j
    LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
GROUP BY 1,
    2;
GRANT SELECT ON public.v_metrics_pipeline TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_metrics_enforcement AS WITH case_rows AS (
        SELECT ec.id,
            ec.opened_at,
            ec.updated_at,
            COALESCE(NULLIF(lower(ec.status), ''), 'open') AS status,
            ec.metadata,
            COALESCE(j.judgment_amount, 0)::numeric AS judgment_amount
        FROM public.enforcement_cases ec
            LEFT JOIN public.judgments j ON j.id = ec.judgment_id
    ),
    closed_events AS (
        SELECT e.case_id,
            MIN(e.event_date) AS closed_at
        FROM public.enforcement_events e
        WHERE lower(COALESCE(e.event_type, '')) LIKE '%closed%'
        GROUP BY e.case_id
    ),
    closed_metadata AS (
        SELECT id AS case_id,
            CASE
                WHEN metadata ? 'closed_at'
                AND jsonb_typeof(metadata->'closed_at') = 'string'
                AND COALESCE(metadata->>'closed_at', '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN (metadata->>'closed_at')::timestamptz
                ELSE NULL
            END AS closed_at
        FROM case_rows
    ),
    combined AS (
        SELECT cr.*,
            COALESCE(
                ce.closed_at,
                cm.closed_at,
                CASE
                    WHEN cr.status = 'closed' THEN cr.updated_at
                    ELSE NULL
                END
            ) AS closed_at
        FROM case_rows cr
            LEFT JOIN closed_events ce ON ce.case_id = cr.id
            LEFT JOIN closed_metadata cm ON cm.case_id = cr.id
    ),
    opened AS (
        SELECT date_trunc('week', timezone('utc', opened_at))::date AS bucket_week,
            COUNT(*) AS cases_opened,
            COALESCE(SUM(judgment_amount), 0)::numeric AS opened_judgment_amount
        FROM combined
        GROUP BY 1
    ),
    closed AS (
        SELECT date_trunc('week', timezone('utc', closed_at))::date AS bucket_week,
            COUNT(*) AS cases_closed,
            COALESCE(SUM(judgment_amount), 0)::numeric AS closed_judgment_amount
        FROM combined
        WHERE closed_at IS NOT NULL
        GROUP BY 1
    ),
    active AS (
        SELECT COUNT(*) FILTER (
                WHERE status <> 'closed'
            ) AS active_case_count,
            COALESCE(
                SUM(
                    CASE
                        WHEN status <> 'closed' THEN judgment_amount
                        ELSE 0
                    END
                ),
                0
            )::numeric AS active_judgment_amount
        FROM combined
    ),
    seed_week AS (
        SELECT date_trunc('week', timezone('utc', now()))::date AS bucket_week
    ),
    week_keys AS (
        SELECT bucket_week
        FROM opened
        UNION
        SELECT bucket_week
        FROM closed
        UNION
        SELECT bucket_week
        FROM seed_week
    )
SELECT wk.bucket_week,
    COALESCE(o.cases_opened, 0) AS cases_opened,
    COALESCE(o.opened_judgment_amount, 0)::numeric AS opened_judgment_amount,
    COALESCE(c.cases_closed, 0) AS cases_closed,
    COALESCE(c.closed_judgment_amount, 0)::numeric AS closed_judgment_amount,
    active.active_case_count,
    active.active_judgment_amount
FROM week_keys wk
    LEFT JOIN opened o ON o.bucket_week = wk.bucket_week
    LEFT JOIN closed c ON c.bucket_week = wk.bucket_week
    CROSS JOIN active
ORDER BY wk.bucket_week DESC;
GRANT SELECT ON public.v_metrics_enforcement TO anon,
    authenticated,
    service_role;
-- Views powering the plaintiff-side dashboards.
CREATE OR REPLACE VIEW public.v_plaintiffs_jbi_900 AS
SELECT p.status,
    COUNT(*)::bigint AS plaintiff_count,
    COALESCE(SUM(ov.total_judgment_amount), 0)::numeric AS total_judgment_amount,
    CASE
        WHEN btrim(lower(p.status)) = 'new' THEN 1
        WHEN btrim(lower(p.status)) = 'contacted' THEN 2
        WHEN btrim(lower(p.status)) = 'qualified' THEN 3
        WHEN btrim(lower(p.status)) = 'sent_agreement' THEN 4
        WHEN btrim(lower(p.status)) = 'signed' THEN 5
        WHEN btrim(lower(p.status)) = 'lost' THEN 6
        ELSE 99
    END AS status_priority
FROM public.plaintiffs p
    LEFT JOIN public.v_plaintiffs_overview ov ON ov.plaintiff_id = p.id
WHERE p.source_system = 'jbi_900'
GROUP BY p.status;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_plaintiff_open_tasks AS WITH tier_lookup AS (
        SELECT j.plaintiff_id,
            MIN(
                CASE
                    WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 1
                    WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 2
                    WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 3
                    ELSE 99
                END
            ) AS best_rank
        FROM public.judgments j
            LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
        WHERE j.plaintiff_id IS NOT NULL
        GROUP BY j.plaintiff_id
    )
SELECT t.id AS task_id,
    t.plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.email,
    p.phone,
    p.status AS plaintiff_status,
    COALESCE(ov.total_judgment_amount, 0::numeric) AS judgment_total,
    COALESCE(ov.case_count, 0) AS case_count,
    CASE
        WHEN tier_lookup.best_rank = 1 THEN 'A'
        WHEN tier_lookup.best_rank = 2 THEN 'B'
        WHEN tier_lookup.best_rank = 3 THEN 'C'
        ELSE NULL
    END AS top_collectability_tier,
    t.kind,
    t.status,
    t.assignee,
    t.due_at,
    t.created_at,
    t.note,
    t.metadata
FROM public.plaintiff_tasks t
    JOIN public.plaintiffs p ON p.id = t.plaintiff_id
    LEFT JOIN public.v_plaintiffs_overview ov ON ov.plaintiff_id = p.id
    LEFT JOIN tier_lookup ON tier_lookup.plaintiff_id = t.plaintiff_id
WHERE t.status IN ('open', 'in_progress');
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon,
    authenticated,
    service_role;
CREATE OR REPLACE VIEW public.v_plaintiff_call_queue AS WITH ranked_call_tasks AS (
        SELECT ot.*,
            row_number() OVER (
                PARTITION BY ot.plaintiff_id
                ORDER BY ot.due_at NULLS LAST,
                    ot.created_at ASC
            ) AS task_rank
        FROM public.v_plaintiff_open_tasks ot
        WHERE ot.kind = 'call'
            AND ot.status IN ('open', 'in_progress')
    )
SELECT r.task_id,
    r.plaintiff_id,
    r.plaintiff_name,
    r.firm_name,
    r.plaintiff_status AS status,
    r.status AS task_status,
    r.top_collectability_tier AS tier,
    r.judgment_total AS total_judgment_amount,
    r.case_count,
    r.phone,
    contact_info.last_contact_at AS last_contact_at,
    contact_info.last_contact_at AS last_contacted_at,
    CASE
        WHEN contact_info.last_contact_at IS NULL THEN NULL
        ELSE GREATEST(
            DATE_PART(
                'day',
                timezone('utc', now()) - contact_info.last_contact_at
            )::int,
            0
        )
    END AS days_since_contact,
    r.due_at,
    r.note AS notes,
    r.created_at
FROM ranked_call_tasks r
    LEFT JOIN LATERAL (
        SELECT CASE
                WHEN status_info.last_contacted_at IS NULL
                AND attempt_info.last_attempt_at IS NULL THEN NULL
                ELSE GREATEST(
                    COALESCE(
                        status_info.last_contacted_at,
                        '-infinity'::timestamptz
                    ),
                    COALESCE(
                        attempt_info.last_attempt_at,
                        '-infinity'::timestamptz
                    )
                )
            END AS last_contact_at
        FROM (
                SELECT MAX(psh.changed_at) AS last_contacted_at
                FROM public.plaintiff_status_history psh
                WHERE psh.plaintiff_id = r.plaintiff_id
                    AND psh.status IN (
                        'contacted',
                        'qualified',
                        'sent_agreement',
                        'signed'
                    )
            ) status_info,
            (
                SELECT MAX(pca.attempted_at) AS last_attempt_at
                FROM public.plaintiff_call_attempts pca
                WHERE pca.plaintiff_id = r.plaintiff_id
            ) attempt_info
    ) contact_info ON TRUE
WHERE r.task_rank = 1
ORDER BY r.due_at NULLS LAST,
    contact_info.last_contact_at NULLS FIRST,
    r.plaintiff_name;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
    authenticated,
    service_role;
COMMIT;
-- migrate:down
BEGIN;
DROP VIEW IF EXISTS public.v_plaintiff_call_queue;
DROP VIEW IF EXISTS public.v_plaintiff_open_tasks;
DROP VIEW IF EXISTS public.v_plaintiffs_jbi_900;
DROP VIEW IF EXISTS public.v_enforcement_recent;
DROP VIEW IF EXISTS public.v_enforcement_overview;
DROP VIEW IF EXISTS public.v_judgment_pipeline;
DROP VIEW IF EXISTS public.v_metrics_enforcement;
DROP VIEW IF EXISTS public.v_metrics_pipeline;
DROP VIEW IF EXISTS public.v_metrics_intake_daily;
DROP VIEW IF EXISTS public.v_plaintiffs_overview;
DROP VIEW IF EXISTS public.v_collectability_snapshot;
DROP FUNCTION IF EXISTS public.dequeue_job(text);
DROP FUNCTION IF EXISTS public.pgmq_delete(text, bigint);
COMMIT;