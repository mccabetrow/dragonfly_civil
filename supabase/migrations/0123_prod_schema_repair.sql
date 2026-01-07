-- 0123_prod_schema_repair.sql
-- Align production schema with the canonical dev definition (functions, views, grants, and core tables).
BEGIN;
-- Ensure touch_updated_at() exists before any triggers reference it
CREATE OR REPLACE FUNCTION public.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at := NOW();
RETURN NEW;
END;
$$;
-- =====================================================================
-- Ensure queue_job RPC matches canonical definition
-- =====================================================================
DROP FUNCTION IF EXISTS public.queue_job (jsonb);
CREATE OR REPLACE FUNCTION public.queue_job(
    payload jsonb
) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_body jsonb;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_body := COALESCE(payload->'payload', '{}'::jsonb);
IF v_kind IS NULL THEN RAISE EXCEPTION 'queue_job: missing kind in payload';
END IF;
IF v_kind NOT IN ('enrich', 'outreach', 'enforce', 'case_copilot') THEN RAISE EXCEPTION 'queue_job: unsupported kind %',
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
$$;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO anon;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO service_role;
-- =====================================================================
-- Ensure request_case_copilot RPC is present
-- =====================================================================
DROP FUNCTION IF EXISTS public.request_case_copilot (uuid, text);
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
GRANT EXECUTE ON FUNCTION public.request_case_copilot(uuid, text) TO anon;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(
    uuid, text
) TO authenticated;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(
    uuid, text
) TO service_role;
-- =====================================================================
-- Ensure log_call_outcome RPC matches canonical implementation
-- =====================================================================
DROP FUNCTION IF EXISTS public.log_call_outcome (
    uuid, uuid, text, text, text, timestamptz
);
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
GRANT EXECUTE ON FUNCTION public.log_call_outcome(
    uuid, uuid, text, text, text, timestamptz
) TO anon;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(
    uuid, uuid, text, text, text, timestamptz
) TO authenticated;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(
    uuid, uuid, text, text, text, timestamptz
) TO service_role;
-- =====================================================================
-- Plaintiffs table safeguards
-- =====================================================================
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS source_system text;
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET DEFAULT 'unknown';
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET NOT NULL;
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS tier text;
ALTER TABLE public.plaintiffs
ALTER COLUMN tier
SET DEFAULT 'unknown';
ALTER TABLE public.plaintiff_contacts
ADD COLUMN IF NOT EXISTS kind text;
ALTER TABLE public.plaintiff_contacts
ADD COLUMN IF NOT EXISTS value text;
-- =====================================================================
-- judgments.cases alignment (columns, constraints, triggers)
-- =====================================================================
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS org_id uuid NOT NULL DEFAULT gen_random_uuid(),
ADD COLUMN IF NOT EXISTS source text NOT NULL DEFAULT 'unknown',
ADD COLUMN IF NOT EXISTS source_system text,
ADD COLUMN IF NOT EXISTS external_id text,
ADD COLUMN IF NOT EXISTS source_url text,
ADD COLUMN IF NOT EXISTS state text,
ADD COLUMN IF NOT EXISTS county text,
ADD COLUMN IF NOT EXISTS court_name text,
ADD COLUMN IF NOT EXISTS court text,
ADD COLUMN IF NOT EXISTS docket_number text,
ADD COLUMN IF NOT EXISTS index_no text,
ADD COLUMN IF NOT EXISTS title text,
ADD COLUMN IF NOT EXISTS case_type text,
ADD COLUMN IF NOT EXISTS case_status text,
ADD COLUMN IF NOT EXISTS case_url text,
ADD COLUMN IF NOT EXISTS filing_date date,
ADD COLUMN IF NOT EXISTS jurisdiction text,
ADD COLUMN IF NOT EXISTS assigned_judge text,
ADD COLUMN IF NOT EXISTS judgment_date date,
ADD COLUMN IF NOT EXISTS principal_amt numeric(14, 2),
ADD COLUMN IF NOT EXISTS amount_awarded numeric(14, 2),
ADD COLUMN IF NOT EXISTS currency text NOT NULL DEFAULT 'USD',
ADD COLUMN IF NOT EXISTS owner text,
ADD COLUMN IF NOT EXISTS metadata jsonb,
ADD COLUMN IF NOT EXISTS raw jsonb NOT NULL DEFAULT '{}'::jsonb,
ADD COLUMN IF NOT EXISTS ingestion_run_id uuid,
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
ALTER TABLE judgments.cases
ALTER COLUMN case_number
SET NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_state_county_docket ON judgments.cases (
    state, county, docket_number
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_org_src_num ON judgments.cases (
    org_id, source, case_number
);
CREATE INDEX IF NOT EXISTS ix_cases_external_id ON judgments.cases (
    external_id
);
CREATE OR REPLACE FUNCTION judgments.apply_case_defaults() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.docket_number IS NULL
    OR btrim(NEW.docket_number) = '' THEN NEW.docket_number := COALESCE(NULLIF(NEW.case_number, ''), NEW.external_id);
END IF;
IF NEW.docket_number IS NULL
OR btrim(NEW.docket_number) = '' THEN RAISE EXCEPTION 'docket_number is required';
END IF;
IF NEW.case_number IS NULL
OR btrim(NEW.case_number) = '' THEN NEW.case_number := NEW.docket_number;
END IF;
IF NEW.state IS NOT NULL THEN NEW.state := upper(trim(NEW.state));
END IF;
IF NEW.county IS NOT NULL THEN NEW.county := initcap(trim(NEW.county));
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_cases_defaults ON judgments.cases;
CREATE TRIGGER trg_cases_defaults BEFORE
INSERT
OR
UPDATE ON judgments.cases FOR EACH ROW EXECUTE FUNCTION judgments.apply_case_defaults();
DROP TRIGGER IF EXISTS trg_cases_touch_updated ON judgments.cases;
CREATE TRIGGER trg_cases_touch_updated BEFORE
UPDATE ON judgments.cases FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
-- =====================================================================
-- Rebuild internal-only dashboards and revoke public access
-- =====================================================================
CREATE OR REPLACE VIEW public.v_case_copilot_latest AS WITH ranked AS (
    SELECT
        l.id,
        l.case_id,
        l.model,
        l.metadata,
        l.created_at,
        row_number() OVER (
            PARTITION BY l.case_id
            ORDER BY
                l.created_at DESC,
                l.id DESC
        ) AS row_num
    FROM public.case_copilot_logs AS l
)

SELECT
    ec.id AS case_id,
    ec.judgment_id,
    ec.current_stage,
    ec.status AS case_status,
    ec.assigned_to,
    r.model,
    r.created_at AS generated_at,
    r.id AS log_id,
    coalesce(ec.case_number, j.case_number) AS case_number,
    r.metadata ->> 'summary' AS summary,
    r.metadata ->> 'risk_comment' AS risk_comment,
    coalesce(actions.actions_array, ARRAY[]::text []) AS recommended_actions,
    r.metadata ->> 'status' AS invocation_status,
    r.metadata ->> 'error' AS error_message,
    r.metadata ->> 'env' AS env,
    r.metadata ->> 'duration_ms' AS duration_ms
FROM ranked AS r
INNER JOIN public.enforcement_cases AS ec ON r.case_id = ec.id
LEFT JOIN public.judgments AS j ON ec.judgment_id = j.id
LEFT JOIN LATERAL (
    SELECT array_agg(elem) AS actions_array
    FROM jsonb_array_elements_text(r.metadata -> 'recommended_actions')
) AS actions ON (r.metadata ? 'recommended_actions')
WHERE r.row_num = 1;
REVOKE ALL PRIVILEGES ON TABLE public.v_case_copilot_latest
FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.v_case_copilot_latest
FROM authenticated;
GRANT SELECT ON public.v_case_copilot_latest TO service_role;
CREATE OR REPLACE VIEW public.v_pipeline_snapshot AS WITH simplicity AS (
    SELECT count(*)::bigint AS total
    FROM public.plaintiffs
    WHERE coalesce(lower(source_system), 'unknown') = 'simplicity'
),

normalized_status AS (
    SELECT
        CASE
            WHEN btrim(coalesce(status, '')) = '' THEN 'unknown'
            ELSE lower(status)
        END AS status_bucket
    FROM public.plaintiffs
),

lifecycle AS (
    SELECT
        coalesce(
            jsonb_object_agg(status_bucket, bucket_count),
            '{}'::jsonb
        ) AS counts
    FROM (
        SELECT
            status_bucket,
            count(*)::bigint AS bucket_count
        FROM normalized_status
        GROUP BY status_bucket
    ) AS buckets
),

collectability AS (
    SELECT
        jsonb_build_object(
            'A',
            coalesce(
                sum(
                    CASE
                        WHEN normalized_tier = 'A' THEN judgment_amount
                        ELSE 0
                    END
                ),
                0
            )::numeric,
            'B',
            coalesce(
                sum(
                    CASE
                        WHEN normalized_tier = 'B' THEN judgment_amount
                        ELSE 0
                    END
                ),
                0
            )::numeric,
            'C',
            coalesce(
                sum(
                    CASE
                        WHEN normalized_tier = 'C' THEN judgment_amount
                        ELSE 0
                    END
                ),
                0
            )::numeric
        ) AS totals
    FROM (
        SELECT
            CASE
                WHEN upper(coalesce(cs.collectability_tier, '')) = 'A' THEN 'A'
                WHEN upper(coalesce(cs.collectability_tier, '')) = 'B' THEN 'B'
                WHEN upper(coalesce(cs.collectability_tier, '')) = 'C' THEN 'C'
            END AS normalized_tier,
            coalesce(cs.judgment_amount, 0::numeric) AS judgment_amount
        FROM public.v_collectability_snapshot AS cs
    ) AS scored
),

jbi AS (
    SELECT
        coalesce(
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
                ORDER BY
                    status_priority,
                    status
            ),
            '[]'::jsonb
        ) AS summary
    FROM public.v_plaintiffs_jbi_900
)

SELECT
    simplicity.total AS simplicity_plaintiff_count,
    lifecycle.counts AS lifecycle_counts,
    collectability.totals AS tier_totals,
    jbi.summary AS jbi_summary,
    timezone('utc', now()) AS snapshot_at
FROM simplicity,
    lifecycle,
    collectability,
    jbi;
REVOKE ALL PRIVILEGES ON TABLE public.v_pipeline_snapshot
FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.v_pipeline_snapshot
FROM authenticated;
GRANT SELECT ON public.v_pipeline_snapshot TO service_role;
CREATE OR REPLACE VIEW public.v_priority_pipeline AS WITH normalized AS (
    SELECT
        j.id AS judgment_id,
        j.judgment_amount,
        coalesce(p.name, j.plaintiff_name) AS plaintiff_name,
        coalesce(
            nullif(lower(j.enforcement_stage), ''),
            'unknown'
        ) AS stage,
        coalesce(nullif(lower(p.status), ''), 'unknown') AS plaintiff_status,
        coalesce(
            nullif(lower(j.priority_level), ''), 'normal'
        ) AS priority_level,
        CASE
            WHEN upper(coalesce(cs.collectability_tier, '')) = 'A' THEN 'A'
            WHEN upper(coalesce(cs.collectability_tier, '')) = 'B' THEN 'B'
            WHEN upper(coalesce(cs.collectability_tier, '')) = 'C' THEN 'C'
            ELSE 'UNSCORED'
        END AS collectability_tier,
        CASE
            WHEN upper(coalesce(cs.collectability_tier, '')) = 'A' THEN 1
            WHEN upper(coalesce(cs.collectability_tier, '')) = 'B' THEN 2
            WHEN upper(coalesce(cs.collectability_tier, '')) = 'C' THEN 3
            ELSE 4
        END AS tier_order,
        CASE
            WHEN
                coalesce(nullif(lower(j.priority_level), ''), 'normal')
                = 'urgent'
                THEN 1
            WHEN
                coalesce(nullif(lower(j.priority_level), ''), 'normal') = 'high'
                THEN 2
            WHEN
                coalesce(nullif(lower(j.priority_level), ''), 'normal')
                = 'normal'
                THEN 3
            WHEN
                coalesce(nullif(lower(j.priority_level), ''), 'normal') = 'low'
                THEN 4
            WHEN
                coalesce(nullif(lower(j.priority_level), ''), 'normal')
                = 'on_hold'
                THEN 5
            ELSE 6
        END AS priority_order
    FROM public.judgments AS j
    LEFT JOIN public.plaintiffs AS p ON j.plaintiff_id = p.id
    LEFT JOIN
        public.v_collectability_snapshot AS cs
        ON j.case_number = cs.case_number
)

SELECT
    n.plaintiff_name,
    n.judgment_id,
    n.collectability_tier,
    n.priority_level,
    n.judgment_amount,
    n.stage,
    n.plaintiff_status,
    row_number() OVER (
        PARTITION BY n.collectability_tier
        ORDER BY
            n.priority_order ASC,
            coalesce(n.judgment_amount, 0)::numeric DESC,
            n.judgment_id DESC
    ) AS tier_rank
FROM normalized AS n;
REVOKE ALL PRIVILEGES ON TABLE public.v_priority_pipeline
FROM anon;
REVOKE ALL PRIVILEGES ON TABLE public.v_priority_pipeline
FROM authenticated;
GRANT SELECT ON public.v_priority_pipeline TO service_role;
COMMIT;

