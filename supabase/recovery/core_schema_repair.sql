-- ============================================================================
-- CORE SCHEMA REPAIR SCRIPT
-- ============================================================================
-- File: /supabase/recovery/core_schema_repair.sql
-- Purpose: Recreate all views required by CEO Dashboard & Ops Console
--
-- This script is fully idempotent and safe to run multiple times.
-- Paste into Supabase SQL Editor when prod schema drifts from dev.
--
-- Views included:
--   PUBLIC SCHEMA:
--     - v_collectability_snapshot (proxy to judgments schema)
--     - v_plaintiffs_overview
--     - v_enforcement_overview
--     - v_enforcement_recent
--     - v_judgment_pipeline
--     - v_priority_pipeline
--     - v_metrics_intake_daily
--     - v_metrics_pipeline
--     - v_metrics_enforcement
--     - v_plaintiffs_jbi_900
--     - v_plaintiff_open_tasks
--     - v_plaintiff_call_queue
--     - v_pipeline_snapshot
--     - v_case_copilot_latest
--
--   OPS SCHEMA (via ops_intake_schema_repair.sql):
--     - ops.v_intake_monitor
--     - ops.v_enrichment_health
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- SECTION 1: ENSURE REQUIRED SCHEMAS EXIST
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS enforcement;
CREATE SCHEMA IF NOT EXISTS finance;
CREATE SCHEMA IF NOT EXISTS judgments;
-- ============================================================================
-- SECTION 2: public.v_plaintiffs_overview
-- Base view used by many other views
-- ============================================================================
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
-- ============================================================================
-- SECTION 3: public.v_enforcement_overview
-- ============================================================================
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
-- ============================================================================
-- SECTION 4: public.v_enforcement_recent
-- ============================================================================
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
-- ============================================================================
-- SECTION 5: public.v_judgment_pipeline
-- ============================================================================
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
-- ============================================================================
-- SECTION 6: public.v_priority_pipeline
-- ============================================================================
CREATE OR REPLACE VIEW public.v_priority_pipeline AS WITH normalized AS (
        SELECT j.id AS judgment_id,
            COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
            j.judgment_amount,
            COALESCE(
                NULLIF(lower(j.enforcement_stage), ''),
                'unknown'
            ) AS stage,
            COALESCE(NULLIF(lower(p.status), ''), 'unknown') AS plaintiff_status,
            COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') AS priority_level,
            CASE
                WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 'A'
                WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 'B'
                WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 'C'
                ELSE 'UNSCORED'
            END AS collectability_tier,
            CASE
                WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 1
                WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 2
                WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 3
                ELSE 4
            END AS tier_order,
            CASE
                WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'urgent' THEN 1
                WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'high' THEN 2
                WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'normal' THEN 3
                WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'low' THEN 4
                WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'on_hold' THEN 5
                ELSE 6
            END AS priority_order
        FROM public.judgments j
            LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
            LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
    )
SELECT n.plaintiff_name,
    n.judgment_id,
    n.collectability_tier,
    n.priority_level,
    n.judgment_amount,
    n.stage,
    n.plaintiff_status,
    ROW_NUMBER() OVER (
        PARTITION BY n.collectability_tier
        ORDER BY n.priority_order,
            COALESCE(n.judgment_amount, 0)::numeric DESC,
            n.judgment_id DESC
    ) AS tier_rank
FROM normalized n;
GRANT SELECT ON public.v_priority_pipeline TO service_role;
-- ============================================================================
-- SECTION 7: public.v_metrics_intake_daily
-- ============================================================================
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
-- ============================================================================
-- SECTION 8: public.v_metrics_pipeline
-- ============================================================================
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
-- ============================================================================
-- SECTION 9: public.v_metrics_enforcement
-- ============================================================================
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
-- ============================================================================
-- SECTION 10: public.v_plaintiffs_jbi_900
-- ============================================================================
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
-- ============================================================================
-- SECTION 11: public.v_plaintiff_open_tasks
-- ============================================================================
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
    t.case_id,
    t.kind,
    t.status,
    t.assignee,
    t.due_at,
    t.created_at,
    t.note,
    t.metadata,
    t.severity,
    t.task_code
FROM public.plaintiff_tasks t
    JOIN public.plaintiffs p ON p.id = t.plaintiff_id
    LEFT JOIN public.v_plaintiffs_overview ov ON ov.plaintiff_id = p.id
    LEFT JOIN tier_lookup ON tier_lookup.plaintiff_id = t.plaintiff_id
WHERE t.status IN ('open', 'in_progress');
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon,
    authenticated,
    service_role;
-- ============================================================================
-- SECTION 12: public.v_plaintiff_call_queue
-- ============================================================================
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
    contact_info.last_call_outcome,
    contact_info.last_call_attempted_at,
    contact_info.last_call_interest_level,
    contact_info.last_call_notes,
    r.due_at,
    r.note AS notes,
    r.created_at
FROM ranked_call_tasks r
    LEFT JOIN LATERAL (
        WITH status_info AS (
            SELECT MAX(psh.changed_at) AS last_contacted_at
            FROM public.plaintiff_status_history psh
            WHERE psh.plaintiff_id = r.plaintiff_id
                AND psh.status IN (
                    'contacted',
                    'qualified',
                    'sent_agreement',
                    'signed'
                )
        ),
        attempt_info AS (
            SELECT pca.outcome,
                pca.interest_level,
                pca.notes,
                pca.attempted_at
            FROM public.plaintiff_call_attempts pca
            WHERE pca.plaintiff_id = r.plaintiff_id
            ORDER BY pca.attempted_at DESC
            LIMIT 1
        )
        SELECT CASE
                WHEN status_info.last_contacted_at IS NULL
                AND attempt_info.attempted_at IS NULL THEN NULL
                ELSE GREATEST(
                    COALESCE(
                        status_info.last_contacted_at,
                        '-infinity'::timestamptz
                    ),
                    COALESCE(
                        attempt_info.attempted_at,
                        '-infinity'::timestamptz
                    )
                )
            END AS last_contact_at,
            attempt_info.outcome AS last_call_outcome,
            attempt_info.interest_level AS last_call_interest_level,
            attempt_info.notes AS last_call_notes,
            attempt_info.attempted_at AS last_call_attempted_at
        FROM status_info
            LEFT JOIN attempt_info ON TRUE
    ) contact_info ON TRUE
WHERE r.task_rank = 1
ORDER BY r.due_at NULLS LAST,
    contact_info.last_contact_at NULLS FIRST,
    r.plaintiff_name;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
    authenticated,
    service_role;
-- ============================================================================
-- SECTION 13: public.v_pipeline_snapshot
-- ============================================================================
CREATE OR REPLACE VIEW public.v_pipeline_snapshot AS WITH simplicity AS (
        SELECT COUNT(*)::bigint AS total
        FROM public.plaintiffs
        WHERE COALESCE(lower(source_system), 'unknown') = 'simplicity'
    ),
    normalized_status AS (
        SELECT CASE
                WHEN btrim(COALESCE(status, '')) = '' THEN 'unknown'
                ELSE lower(status)
            END AS status_bucket
        FROM public.plaintiffs
    ),
    lifecycle AS (
        SELECT COALESCE(
                jsonb_object_agg(status_bucket, bucket_count),
                '{}'::jsonb
            ) AS counts
        FROM (
                SELECT status_bucket,
                    COUNT(*)::bigint AS bucket_count
                FROM normalized_status
                GROUP BY status_bucket
            ) buckets
    ),
    collectability AS (
        SELECT jsonb_build_object(
                'A',
                COALESCE(
                    SUM(
                        CASE
                            WHEN normalized_tier = 'A' THEN judgment_amount
                            ELSE 0
                        END
                    ),
                    0
                )::numeric,
                'B',
                COALESCE(
                    SUM(
                        CASE
                            WHEN normalized_tier = 'B' THEN judgment_amount
                            ELSE 0
                        END
                    ),
                    0
                )::numeric,
                'C',
                COALESCE(
                    SUM(
                        CASE
                            WHEN normalized_tier = 'C' THEN judgment_amount
                            ELSE 0
                        END
                    ),
                    0
                )::numeric
            ) AS totals
        FROM (
                SELECT CASE
                        WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 'A'
                        WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 'B'
                        WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 'C'
                        ELSE NULL
                    END AS normalized_tier,
                    COALESCE(cs.judgment_amount, 0::numeric) AS judgment_amount
                FROM public.v_collectability_snapshot cs
            ) scored
    ),
    jbi AS (
        SELECT COALESCE(
                jsonb_agg(
                    jsonb_build_object(
                        'status',
                        status,
                        'plaintiff_count',
                        plaintiff_count,
                        'total_judgment_amount',
                        total_judgment_amount,
                        'status_priority',
                        status_priority
                    )
                    ORDER BY status_priority,
                        status
                ),
                '[]'::jsonb
            ) AS summary
        FROM public.v_plaintiffs_jbi_900
    )
SELECT timezone('utc', now()) AS snapshot_at,
    simplicity.total AS simplicity_plaintiff_count,
    lifecycle.counts AS lifecycle_counts,
    collectability.totals AS tier_totals,
    jbi.summary AS jbi_summary
FROM simplicity,
    lifecycle,
    collectability,
    jbi;
GRANT SELECT ON public.v_pipeline_snapshot TO service_role;
-- ============================================================================
-- SECTION 14: ops.v_metrics_intake_daily (ops schema version)
-- ============================================================================
CREATE OR REPLACE VIEW ops.v_metrics_intake_daily AS
SELECT COALESCE(j.created_at::date, CURRENT_DATE) AS activity_date,
    COALESCE(p.source_system, 'unknown') AS source_system,
    COUNT(
        DISTINCT CASE
            WHEN j.id IS NOT NULL THEN 1
        END
    ) AS import_count,
    COUNT(DISTINCT p.id) AS plaintiff_count,
    COUNT(DISTINCT j.id) AS judgment_count,
    COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_judgment_amount
FROM public.plaintiffs p
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
WHERE p.created_at >= CURRENT_DATE - INTERVAL '90 days'
GROUP BY COALESCE(j.created_at::date, CURRENT_DATE),
    COALESCE(p.source_system, 'unknown')
ORDER BY activity_date DESC,
    source_system;
COMMENT ON VIEW ops.v_metrics_intake_daily IS 'Daily intake metrics by source system for Ops Console dashboard';
GRANT SELECT ON ops.v_metrics_intake_daily TO authenticated,
    service_role;
-- ============================================================================
-- SECTION 15: enforcement.v_enforcement_pipeline_status
-- ============================================================================
CREATE OR REPLACE VIEW enforcement.v_enforcement_pipeline_status AS
SELECT COALESCE(j.status, 'unknown') AS status,
    COUNT(*) AS count,
    COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_value
FROM public.judgments j
WHERE j.status IN (
        'enforcement_open',
        'enforcement_pending',
        'garnishment_active',
        'lien_filed',
        'payment_plan',
        'satisfied',
        'uncollectable'
    )
GROUP BY COALESCE(j.status, 'unknown')
ORDER BY count DESC;
COMMENT ON VIEW enforcement.v_enforcement_pipeline_status IS 'Enforcement pipeline status aggregation for dashboard';
GRANT SELECT ON enforcement.v_enforcement_pipeline_status TO authenticated,
    service_role;
-- ============================================================================
-- SECTION 16: enforcement.v_plaintiff_call_queue
-- ============================================================================
CREATE OR REPLACE VIEW enforcement.v_plaintiff_call_queue AS
SELECT p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_judgment_amount,
    COUNT(j.id) AS case_count,
    COALESCE(p.metadata->>'phone', '') AS phone
FROM public.plaintiffs p
    LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
WHERE p.status IN (
        'active',
        'pending_outreach',
        'callback_scheduled'
    )
GROUP BY p.id,
    p.name,
    p.firm_name,
    p.status,
    p.metadata
ORDER BY total_judgment_amount DESC
LIMIT 100;
COMMENT ON VIEW enforcement.v_plaintiff_call_queue IS 'Plaintiff call queue for outreach operations';
GRANT SELECT ON enforcement.v_plaintiff_call_queue TO authenticated,
    service_role;
-- ============================================================================
-- SECTION 17: finance.v_portfolio_stats
-- ============================================================================
CREATE OR REPLACE VIEW finance.v_portfolio_stats AS
SELECT COALESCE(SUM(j.judgment_amount), 0)::numeric(15, 2) AS total_aum,
    COALESCE(
        SUM(
            CASE
                WHEN j.status IN (
                    'enforcement_open',
                    'garnishment_active',
                    'payment_plan'
                ) THEN j.judgment_amount
                ELSE 0
            END
        ),
        0
    )::numeric(15, 2) AS actionable_liquidity,
    COALESCE(
        SUM(
            CASE
                WHEN j.status IN (
                    'intake_complete',
                    'enriched',
                    'enforcement_pending'
                ) THEN j.judgment_amount
                ELSE 0
            END
        ),
        0
    )::numeric(15, 2) AS pipeline_value,
    0::numeric(15, 2) AS offers_outstanding
FROM public.judgments j
WHERE j.judgment_amount IS NOT NULL
    AND j.judgment_amount > 0;
COMMENT ON VIEW finance.v_portfolio_stats IS 'Portfolio-level financial statistics for CEO dashboard';
GRANT SELECT ON finance.v_portfolio_stats TO authenticated,
    service_role;
-- ============================================================================
-- SECTION 18: SCHEMA GRANTS
-- ============================================================================
GRANT USAGE ON SCHEMA ops TO authenticated,
    service_role;
GRANT USAGE ON SCHEMA enforcement TO authenticated,
    service_role;
GRANT USAGE ON SCHEMA finance TO authenticated,
    service_role;
-- ============================================================================
-- SECTION 19: VALIDATION QUERIES
-- ============================================================================
SELECT 'v_plaintiffs_overview' AS view_name,
    to_regclass('public.v_plaintiffs_overview') IS NOT NULL AS exists;
SELECT 'v_enforcement_overview' AS view_name,
    to_regclass('public.v_enforcement_overview') IS NOT NULL AS exists;
SELECT 'v_enforcement_recent' AS view_name,
    to_regclass('public.v_enforcement_recent') IS NOT NULL AS exists;
SELECT 'v_judgment_pipeline' AS view_name,
    to_regclass('public.v_judgment_pipeline') IS NOT NULL AS exists;
SELECT 'v_priority_pipeline' AS view_name,
    to_regclass('public.v_priority_pipeline') IS NOT NULL AS exists;
SELECT 'v_metrics_intake_daily' AS view_name,
    to_regclass('public.v_metrics_intake_daily') IS NOT NULL AS exists;
SELECT 'v_metrics_pipeline' AS view_name,
    to_regclass('public.v_metrics_pipeline') IS NOT NULL AS exists;
SELECT 'v_metrics_enforcement' AS view_name,
    to_regclass('public.v_metrics_enforcement') IS NOT NULL AS exists;
SELECT 'v_plaintiffs_jbi_900' AS view_name,
    to_regclass('public.v_plaintiffs_jbi_900') IS NOT NULL AS exists;
SELECT 'v_plaintiff_open_tasks' AS view_name,
    to_regclass('public.v_plaintiff_open_tasks') IS NOT NULL AS exists;
SELECT 'v_plaintiff_call_queue' AS view_name,
    to_regclass('public.v_plaintiff_call_queue') IS NOT NULL AS exists;
SELECT 'v_pipeline_snapshot' AS view_name,
    to_regclass('public.v_pipeline_snapshot') IS NOT NULL AS exists;
-- ============================================================================
-- SECTION 20: NOTIFY POSTGREST
-- ============================================================================
NOTIFY pgrst,
'reload schema';
COMMIT;
-- ============================================================================
-- END OF CORE SCHEMA REPAIR SCRIPT
-- ============================================================================