-- Executive dashboard metrics views for intake, pipeline, and enforcement.
-- migrate:up
BEGIN;
DROP VIEW IF EXISTS public.v_metrics_intake_daily;
CREATE OR REPLACE VIEW public.v_metrics_intake_daily AS WITH import_rows AS (
    SELECT
        date_trunc('day', timezone('utc', started_at))::date AS activity_date,
        coalesce(nullif(lower(source_system), ''), 'unknown') AS source_system,
        count(*) AS import_count
    FROM public.import_runs
    GROUP BY
        1,
        2
),

plaintiff_rows AS (
    SELECT
        date_trunc('day', timezone('utc', created_at))::date AS activity_date,
        coalesce(nullif(lower(source_system), ''), 'unknown') AS source_system,
        count(*) AS plaintiff_count
    FROM public.plaintiffs
    GROUP BY
        1,
        2
),

judgment_rows AS (
    SELECT
        date_trunc(
            'day',
            timezone(
                'utc',
                coalesce(j.created_at, j.entry_date::timestamptz, now())
            )
        )::date AS activity_date,
        coalesce(
            nullif(lower(p.source_system), ''), 'unknown'
        ) AS source_system,
        count(*) AS judgment_count,
        coalesce(sum(j.judgment_amount), 0)::numeric AS total_judgment_amount
    FROM public.judgments AS j
    LEFT JOIN public.plaintiffs AS p ON j.plaintiff_id = p.id
    GROUP BY
        1,
        2
),

combined_keys AS (
    SELECT
        activity_date,
        source_system
    FROM import_rows
    UNION
    SELECT
        activity_date,
        source_system
    FROM plaintiff_rows
    UNION
    SELECT
        activity_date,
        source_system
    FROM judgment_rows
)

SELECT
    k.activity_date,
    k.source_system,
    coalesce(j.total_judgment_amount, 0)::numeric AS total_judgment_amount,
    coalesce(i.import_count, 0) AS import_count,
    coalesce(pl.plaintiff_count, 0) AS plaintiff_count,
    coalesce(j.judgment_count, 0) AS judgment_count
FROM combined_keys AS k
LEFT JOIN import_rows AS i
    ON
        k.activity_date = i.activity_date
        AND k.source_system = i.source_system
LEFT JOIN plaintiff_rows AS pl
    ON
        k.activity_date = pl.activity_date
        AND k.source_system = pl.source_system
LEFT JOIN judgment_rows AS j
    ON
        k.activity_date = j.activity_date
        AND k.source_system = j.source_system
ORDER BY
    k.activity_date DESC,
    k.source_system ASC;
COMMENT ON VIEW public.v_metrics_intake_daily IS 'Daily intake funnel rollups by source system for the executive dashboard.';
GRANT SELECT ON public.v_metrics_intake_daily TO anon,
authenticated,
service_role;
DROP VIEW IF EXISTS public.v_metrics_pipeline;
CREATE OR REPLACE VIEW public.v_metrics_pipeline AS
SELECT
    coalesce(
        nullif(lower(j.enforcement_stage), ''),
        'unknown'
    ) AS enforcement_stage,
    coalesce(
        nullif(lower(cs.collectability_tier), ''),
        'unscored'
    ) AS collectability_tier,
    count(*) AS judgment_count,
    coalesce(sum(j.judgment_amount), 0)::numeric AS total_judgment_amount,
    coalesce(avg(j.judgment_amount), 0)::numeric AS average_judgment_amount,
    max(j.enforcement_stage_updated_at) AS latest_stage_update
FROM public.judgments AS j
LEFT JOIN
    public.v_collectability_snapshot AS cs
    ON j.case_number = cs.case_number
GROUP BY
    1,
    2;
COMMENT ON VIEW public.v_metrics_pipeline IS 'Current pipeline exposure grouped by enforcement stage and collectability tier.';
GRANT SELECT ON public.v_metrics_pipeline TO anon,
authenticated,
service_role;
DROP VIEW IF EXISTS public.v_metrics_enforcement;
CREATE OR REPLACE VIEW public.v_metrics_enforcement AS WITH case_rows AS (
    SELECT
        ec.id,
        ec.opened_at,
        ec.updated_at,
        ec.metadata,
        coalesce(j.judgment_amount, 0)::numeric AS judgment_amount,
        coalesce(nullif(lower(ec.status), ''), 'open') AS status
    FROM public.enforcement_cases AS ec
    LEFT JOIN public.judgments AS j ON ec.judgment_id = j.id
),

closed_events AS (
    SELECT
        e.case_id,
        min(e.event_date) AS closed_at
    FROM public.enforcement_events AS e
    WHERE lower(coalesce(e.event_type, '')) LIKE '%closed%'
    GROUP BY e.case_id
),

closed_metadata AS (
    SELECT
        id AS case_id,
        CASE
            WHEN
                metadata ? 'closed_at'
                AND jsonb_typeof(metadata -> 'closed_at') = 'string'
                AND coalesce(metadata ->> 'closed_at', '')
                ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                THEN (metadata ->> 'closed_at')::timestamptz
        END AS closed_at
    FROM case_rows
),

combined AS (
    SELECT
        cr.*,
        coalesce(
            ce.closed_at,
            cm.closed_at,
            CASE
                WHEN cr.status = 'closed' THEN cr.updated_at
            END
        ) AS closed_at
    FROM case_rows AS cr
    LEFT JOIN closed_events AS ce ON cr.id = ce.case_id
    LEFT JOIN closed_metadata AS cm ON cr.id = cm.case_id
),

opened AS (
    SELECT
        date_trunc('week', timezone('utc', opened_at))::date AS bucket_week,
        count(*) AS cases_opened,
        coalesce(sum(judgment_amount), 0)::numeric AS opened_judgment_amount
    FROM combined
    GROUP BY 1
),

closed AS (
    SELECT
        date_trunc('week', timezone('utc', closed_at))::date AS bucket_week,
        count(*) AS cases_closed,
        coalesce(sum(judgment_amount), 0)::numeric AS closed_judgment_amount
    FROM combined
    WHERE closed_at IS NOT NULL
    GROUP BY 1
),

active AS (
    SELECT
        coalesce(
            sum(
                CASE
                    WHEN status <> 'closed' THEN judgment_amount
                    ELSE 0
                END
            ),
            0
        )::numeric AS active_judgment_amount,
        count(*) FILTER (
            WHERE status <> 'closed'
        ) AS active_case_count
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

SELECT
    wk.bucket_week,
    coalesce(o.opened_judgment_amount, 0)::numeric AS opened_judgment_amount,
    coalesce(c.closed_judgment_amount, 0)::numeric AS closed_judgment_amount,
    active.active_case_count,
    active.active_judgment_amount,
    coalesce(o.cases_opened, 0) AS cases_opened,
    coalesce(c.cases_closed, 0) AS cases_closed
FROM week_keys AS wk
LEFT JOIN opened AS o ON wk.bucket_week = o.bucket_week
LEFT JOIN closed AS c ON wk.bucket_week = c.bucket_week
CROSS JOIN active
ORDER BY wk.bucket_week DESC;
COMMENT ON VIEW public.v_metrics_enforcement IS 'Weekly enforcement throughput plus active exposure snapshot for executives.';
GRANT SELECT ON public.v_metrics_enforcement TO anon,
authenticated,
service_role;
COMMIT;
-- migrate:down
BEGIN;
DROP VIEW IF EXISTS public.v_metrics_enforcement;
DROP VIEW IF EXISTS public.v_metrics_pipeline;
DROP VIEW IF EXISTS public.v_metrics_intake_daily;
COMMIT;
