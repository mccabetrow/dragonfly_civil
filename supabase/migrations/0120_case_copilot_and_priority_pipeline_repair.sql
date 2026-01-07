-- 0120_case_copilot_and_priority_pipeline_repair.sql
-- Restores v_case_copilot_latest, v_pipeline_snapshot, v_priority_pipeline,
-- request_case_copilot, and log_call_outcome so dev matches the repo + tests.
-- migrate:up
BEGIN;
-- Case Copilot latest view used by dashboards and tests.
CREATE OR REPLACE VIEW public.v_case_copilot_latest AS WITH ranked AS (
        SELECT l.id,
            l.case_id,
            l.model,
            l.metadata,
            l.created_at,
            row_number() OVER (
                PARTITION BY l.case_id
                ORDER BY l.created_at DESC,
                    l.id DESC
            ) AS row_num
        FROM public.case_copilot_logs l
    )
SELECT ec.id AS case_id,
    COALESCE(ec.case_number, j.case_number) AS case_number,
    ec.judgment_id,
    ec.current_stage,
    ec.status AS case_status,
    ec.assigned_to,
    r.model,
    r.created_at AS generated_at,
    r.metadata->>'summary' AS summary,
    r.metadata->>'risk_comment' AS risk_comment,
    COALESCE(actions.actions_array, ARRAY []::text []) AS recommended_actions,
    r.metadata->>'status' AS invocation_status,
    r.metadata->>'error' AS error_message,
    r.metadata->>'env' AS env,
    r.metadata->>'duration_ms' AS duration_ms,
    r.id AS log_id
FROM ranked r
    JOIN public.enforcement_cases ec ON ec.id = r.case_id
    LEFT JOIN public.judgments j ON j.id = ec.judgment_id
    LEFT JOIN LATERAL (
        SELECT array_agg(elem) AS actions_array
        FROM jsonb_array_elements_text(r.metadata->'recommended_actions') elem
    ) actions ON (r.metadata ? 'recommended_actions')
WHERE r.row_num = 1;
GRANT SELECT ON public.v_case_copilot_latest TO anon,
    authenticated,
    service_role;
-- Case Copilot re-run RPC consumed by tooling.
DROP FUNCTION IF EXISTS public.request_case_copilot(uuid, text);
CREATE OR REPLACE FUNCTION public.request_case_copilot(
        p_case_id uuid,
        requested_by text DEFAULT NULL
    ) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_case record;
v_payload jsonb;
v_key text;
BEGIN IF p_case_id IS NULL THEN RAISE EXCEPTION 'request_case_copilot: case_id is required';
END IF;
SELECT ec.id,
    COALESCE(ec.case_number, j.case_number) AS case_number INTO v_case
FROM public.enforcement_cases ec
    JOIN public.judgments j ON j.id = ec.judgment_id
WHERE ec.id = p_case_id
LIMIT 1;
IF v_case.id IS NULL THEN RAISE EXCEPTION 'request_case_copilot: case % not found',
p_case_id;
END IF;
v_payload := jsonb_build_object(
    'case_id',
    v_case.id::text,
    'case_number',
    v_case.case_number,
    'requested_by',
    NULLIF(trim(COALESCE(requested_by, '')), ''),
    'requested_at',
    timezone('utc', now())
);
v_key := format(
    'case_copilot:%s:%s',
    v_case.id,
    encode(extensions.gen_random_bytes(6), 'hex')
);
RETURN public.queue_job(
    jsonb_build_object(
        'kind',
        'case_copilot',
        'idempotency_key',
        v_key,
        'payload',
        v_payload
    )
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(uuid, text) TO anon,
    authenticated,
    service_role;
-- Six-argument log_call_outcome RPC required by outreach + tests.
CREATE OR REPLACE FUNCTION public.log_call_outcome(
        _plaintiff_id uuid,
        _task_id uuid,
        _outcome text,
        _interest text,
        _notes text,
        _follow_up_at timestamptz
    ) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_terminal boolean := _outcome IN ('do_not_call', 'bad_number');
v_now timestamptz := timezone('utc', now());
v_status text;
v_follow_up_created boolean := false;
v_attempt_id uuid;
v_follow_up_task_id uuid;
BEGIN IF _outcome = 'do_not_call' THEN v_status := 'do_not_call';
ELSIF _outcome = 'bad_number' THEN v_status := 'bad_number';
ELSIF _outcome = 'reached'
AND _interest = 'hot' THEN v_status := 'reached_hot';
ELSIF _outcome = 'reached'
AND _interest = 'warm' THEN v_status := 'reached_warm';
ELSE v_status := 'contacted';
END IF;
INSERT INTO public.plaintiff_call_attempts (
        plaintiff_id,
        task_id,
        outcome,
        interest_level,
        notes,
        next_follow_up_at,
        attempted_at,
        metadata
    )
VALUES (
        _plaintiff_id,
        _task_id,
        _outcome,
        NULLIF(_interest, ''),
        _notes,
        CASE
            WHEN NOT v_terminal THEN _follow_up_at
            ELSE NULL
        END,
        v_now,
        jsonb_build_object(
            'from_rpc',
            'log_call_outcome',
            'follow_up_at',
            CASE
                WHEN NOT v_terminal THEN _follow_up_at
                ELSE NULL
            END
        )
    )
RETURNING id INTO v_attempt_id;
UPDATE public.plaintiff_tasks t
SET status = 'closed',
    completed_at = v_now,
    closed_at = COALESCE(t.closed_at, v_now),
    result = COALESCE(t.result, _outcome),
    metadata = COALESCE(t.metadata, '{}'::jsonb) || jsonb_build_object(
        'result',
        _outcome,
        'interest_level',
        _interest,
        'closed_by',
        'log_call_outcome',
        'closed_at',
        v_now
    )
WHERE t.id = _task_id;
INSERT INTO public.plaintiff_status_history (
        plaintiff_id,
        status,
        note,
        changed_at,
        changed_by
    )
VALUES (
        _plaintiff_id,
        v_status,
        COALESCE(
            _notes,
            format('Call outcome recorded: %s', _outcome)
        ),
        v_now,
        'log_call_outcome'
    );
IF (NOT v_terminal)
AND _follow_up_at IS NOT NULL THEN
INSERT INTO public.plaintiff_tasks (
        plaintiff_id,
        kind,
        status,
        due_at,
        note,
        created_by,
        metadata
    )
VALUES (
        _plaintiff_id,
        'call',
        'open',
        _follow_up_at,
        COALESCE(_notes, 'Follow-up call'),
        'log_call_outcome',
        jsonb_build_object(
            'from_outcome',
            _outcome,
            'interest_level',
            _interest,
            'previous_task_id',
            _task_id
        )
    )
RETURNING id INTO v_follow_up_task_id;
v_follow_up_created := true;
END IF;
RETURN jsonb_build_object(
    'plaintiff_id',
    _plaintiff_id,
    'task_id',
    _task_id,
    'outcome',
    _outcome,
    'interest',
    _interest,
    'status',
    v_status,
    'follow_up_created',
    v_follow_up_created,
    'follow_up_at',
    _follow_up_at,
    'call_attempt_id',
    v_attempt_id,
    'created_follow_up_task_id',
    v_follow_up_task_id
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO anon,
    authenticated,
    service_role;
-- Pipeline snapshot view referenced by dashboards + tooling.
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
GRANT SELECT ON public.v_pipeline_snapshot TO anon,
    authenticated,
    service_role;
-- Priority pipeline ranking view used by ops dashboards.
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
GRANT SELECT ON public.v_priority_pipeline TO anon,
    authenticated,
    service_role;
COMMIT;
-- migrate:down
BEGIN;
DROP VIEW IF EXISTS public.v_priority_pipeline;
DROP VIEW IF EXISTS public.v_pipeline_snapshot;
DROP VIEW IF EXISTS public.v_case_copilot_latest;
REVOKE EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz)
FROM anon,
    authenticated,
    service_role;
DROP FUNCTION IF EXISTS public.log_call_outcome(uuid, uuid, text, text, text, timestamptz);
REVOKE EXECUTE ON FUNCTION public.request_case_copilot(uuid, text)
FROM anon,
    authenticated,
    service_role;
DROP FUNCTION IF EXISTS public.request_case_copilot(uuid, text);
COMMIT;
