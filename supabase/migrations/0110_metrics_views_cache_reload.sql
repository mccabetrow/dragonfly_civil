-- 0110_metrics_views_cache_reload.sql
-- Reassert the canonical executive metrics views and refresh PostgREST so they are immediately visible.
-- migrate:up
BEGIN;
DROP VIEW IF EXISTS public.v_metrics_enforcement;
DROP VIEW IF EXISTS public.v_metrics_pipeline;
DROP VIEW IF EXISTS public.v_metrics_intake_daily;
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
COMMENT ON VIEW public.v_metrics_intake_daily IS 'Daily intake funnel rollups by source system for the executive dashboard.';
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
COMMENT ON VIEW public.v_metrics_pipeline IS 'Current pipeline exposure grouped by enforcement stage and collectability tier.';
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
COMMENT ON VIEW public.v_metrics_enforcement IS 'Weekly enforcement throughput plus active exposure snapshot for executives.';
GRANT SELECT ON public.v_metrics_enforcement TO anon,
    authenticated,
    service_role;
DO $$ BEGIN PERFORM public.pgrst_reload();
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'public.pgrst_reload() is unavailable; skipping schema cache reload.';
END;
$$;
COMMIT;
-- migrate:down
BEGIN;
DROP VIEW IF EXISTS public.v_metrics_enforcement;
DROP VIEW IF EXISTS public.v_metrics_pipeline;
DROP VIEW IF EXISTS public.v_metrics_intake_daily;
DO $$ BEGIN PERFORM public.pgrst_reload();
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'public.pgrst_reload() is unavailable; skipping schema cache reload.';
END;
$$;
COMMIT;