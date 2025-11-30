-- 0099_executive_metrics_enforcement_view.sql
-- Rebuild the enforcement metrics view to expose weekly buckets expected by tools, tests, and the dashboard.
-- migrate:up
BEGIN;

DROP VIEW IF EXISTS public.v_metrics_enforcement;
CREATE OR REPLACE VIEW public.v_metrics_enforcement AS
WITH case_rows AS (
    SELECT
        ec.id,
        ec.opened_at,
        ec.updated_at,
        ec.metadata,
        COALESCE(j.judgment_amount, 0)::numeric AS judgment_amount,
        COALESCE(NULLIF(LOWER(ec.status), ''), 'open') AS status
    FROM public.enforcement_cases AS ec
    LEFT JOIN public.judgments AS j ON ec.judgment_id = j.id
),

closed_events AS (
    SELECT
        e.case_id,
        MIN(e.event_date) AS closed_at
    FROM public.enforcement_events AS e
    WHERE LOWER(COALESCE(e.event_type, '')) LIKE '%closed%'
    GROUP BY e.case_id
),

closed_metadata AS (
    SELECT
        id AS case_id,
        CASE
            WHEN
                metadata ? 'closed_at'
                AND JSONB_TYPEOF(metadata -> 'closed_at') = 'string'
                AND COALESCE(metadata ->> 'closed_at', '')
                ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}'
                THEN (metadata ->> 'closed_at')::timestamptz
        END AS closed_at
    FROM case_rows
),

combined AS (
    SELECT
        cr.*,
        COALESCE(
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
        DATE_TRUNC('week', TIMEZONE('utc', opened_at))::date AS bucket_week,
        COUNT(*) AS cases_opened,
        COALESCE(SUM(judgment_amount), 0)::numeric AS opened_judgment_amount
    FROM combined
    GROUP BY 1
),

closed AS (
    SELECT
        DATE_TRUNC('week', TIMEZONE('utc', closed_at))::date AS bucket_week,
        COUNT(*) AS cases_closed,
        COALESCE(SUM(judgment_amount), 0)::numeric AS closed_judgment_amount
    FROM combined
    WHERE closed_at IS NOT NULL
    GROUP BY 1
),

active AS (
    SELECT
        COALESCE(
            SUM(
                CASE
                    WHEN status <> 'closed' THEN judgment_amount
                    ELSE 0
                END
            ),
            0
        )::numeric AS active_judgment_amount,
        COUNT(*) FILTER (
            WHERE status <> 'closed'
        ) AS active_case_count
    FROM combined
),

seed_week AS (
    SELECT DATE_TRUNC('week', TIMEZONE('utc', NOW()))::date AS bucket_week
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
    COALESCE(o.opened_judgment_amount, 0)::numeric AS opened_judgment_amount,
    COALESCE(c.closed_judgment_amount, 0)::numeric AS closed_judgment_amount,
    active.active_case_count,
    active.active_judgment_amount,
    COALESCE(o.cases_opened, 0) AS cases_opened,
    COALESCE(c.cases_closed, 0) AS cases_closed
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
COMMIT;
