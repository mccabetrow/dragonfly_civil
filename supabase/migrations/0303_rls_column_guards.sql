-- =============================================================================
-- 0303_rls_column_guards.sql
-- Dragonfly Civil – Column-Level Update Guards via RPCs
-- =============================================================================
-- Since PostgreSQL RLS operates at row-level (not column-level), we enforce
-- column restrictions via SECURITY DEFINER RPCs that validate field access.
-- =============================================================================
BEGIN;
-- =============================================================================
-- OPS: Update operational fields only (status, notes, follow_up, assignee)
-- =============================================================================
-- Update judgment operational fields (ops role only)
CREATE OR REPLACE FUNCTION public.ops_update_judgment(
        p_judgment_id bigint,
        p_enforcement_stage text DEFAULT NULL,
        p_priority_level text DEFAULT NULL,
        p_notes text DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_result public.judgments %ROWTYPE;
BEGIN -- Verify ops role
IF NOT public.dragonfly_has_role('ops') THEN RAISE EXCEPTION 'Access denied: requires ops role' USING ERRCODE = '42501';
END IF;
IF p_judgment_id IS NULL THEN RAISE EXCEPTION 'judgment_id is required';
END IF;
UPDATE public.judgments
SET enforcement_stage = COALESCE(p_enforcement_stage, enforcement_stage),
    enforcement_stage_updated_at = CASE
        WHEN p_enforcement_stage IS NOT NULL THEN timezone('utc', now())
        ELSE enforcement_stage_updated_at
    END,
    priority_level = COALESCE(p_priority_level, priority_level),
    priority_level_updated_at = CASE
        WHEN p_priority_level IS NOT NULL THEN timezone('utc', now())
        ELSE priority_level_updated_at
    END
WHERE id = p_judgment_id
RETURNING * INTO v_result;
IF NOT FOUND THEN RAISE EXCEPTION 'Judgment % not found',
p_judgment_id USING ERRCODE = 'P0002';
END IF;
RETURN jsonb_build_object(
    'success',
    true,
    'judgment_id',
    v_result.id,
    'enforcement_stage',
    v_result.enforcement_stage,
    'priority_level',
    v_result.priority_level,
    'updated_at',
    v_result.updated_at
);
END;
$$;
REVOKE ALL ON FUNCTION public.ops_update_judgment(bigint, text, text, text)
FROM public;
GRANT EXECUTE ON FUNCTION public.ops_update_judgment(bigint, text, text, text) TO authenticated,
    service_role;
-- Update plaintiff status (ops role only)
CREATE OR REPLACE FUNCTION public.ops_update_plaintiff_status(
        p_plaintiff_id uuid,
        p_status text,
        p_note text DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_old_status text;
v_now timestamptz := timezone('utc', now());
BEGIN IF NOT public.dragonfly_has_role('ops') THEN RAISE EXCEPTION 'Access denied: requires ops role' USING ERRCODE = '42501';
END IF;
IF p_plaintiff_id IS NULL
OR p_status IS NULL THEN RAISE EXCEPTION 'plaintiff_id and status are required';
END IF;
SELECT status INTO v_old_status
FROM public.plaintiffs
WHERE id = p_plaintiff_id;
IF NOT FOUND THEN RAISE EXCEPTION 'Plaintiff % not found',
p_plaintiff_id USING ERRCODE = 'P0002';
END IF;
IF v_old_status = p_status THEN RETURN jsonb_build_object(
    'success',
    true,
    'changed',
    false,
    'plaintiff_id',
    p_plaintiff_id,
    'status',
    p_status
);
END IF;
UPDATE public.plaintiffs
SET status = p_status,
    updated_at = v_now
WHERE id = p_plaintiff_id;
INSERT INTO public.plaintiff_status_history (
        plaintiff_id,
        status,
        note,
        changed_at,
        changed_by
    )
VALUES (
        p_plaintiff_id,
        p_status,
        p_note,
        v_now,
        'ops_update_plaintiff_status'
    );
RETURN jsonb_build_object(
    'success',
    true,
    'changed',
    true,
    'plaintiff_id',
    p_plaintiff_id,
    'old_status',
    v_old_status,
    'new_status',
    p_status
);
END;
$$;
REVOKE ALL ON FUNCTION public.ops_update_plaintiff_status(uuid, text, text)
FROM public;
GRANT EXECUTE ON FUNCTION public.ops_update_plaintiff_status(uuid, text, text) TO authenticated,
    service_role;
-- Update task assignment (ops role only)
CREATE OR REPLACE FUNCTION public.ops_update_task(
        p_task_id uuid,
        p_status text DEFAULT NULL,
        p_assignee text DEFAULT NULL,
        p_note text DEFAULT NULL,
        p_due_at timestamptz DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_result public.plaintiff_tasks %ROWTYPE;
BEGIN IF NOT public.dragonfly_has_role('ops') THEN RAISE EXCEPTION 'Access denied: requires ops role' USING ERRCODE = '42501';
END IF;
IF p_task_id IS NULL THEN RAISE EXCEPTION 'task_id is required';
END IF;
UPDATE public.plaintiff_tasks
SET status = COALESCE(p_status, status),
    assignee = COALESCE(p_assignee, assignee),
    note = COALESCE(p_note, note),
    due_at = COALESCE(p_due_at, due_at),
    completed_at = CASE
        WHEN p_status = 'closed' THEN timezone('utc', now())
        ELSE completed_at
    END,
    closed_at = CASE
        WHEN p_status = 'closed' THEN COALESCE(closed_at, timezone('utc', now()))
        ELSE closed_at
    END
WHERE id = p_task_id
RETURNING * INTO v_result;
IF NOT FOUND THEN RAISE EXCEPTION 'Task % not found',
p_task_id USING ERRCODE = 'P0002';
END IF;
RETURN jsonb_build_object(
    'success',
    true,
    'task_id',
    v_result.id,
    'status',
    v_result.status,
    'assignee',
    v_result.assignee
);
END;
$$;
REVOKE ALL ON FUNCTION public.ops_update_task(uuid, text, text, text, timestamptz)
FROM public;
GRANT EXECUTE ON FUNCTION public.ops_update_task(uuid, text, text, text, timestamptz) TO authenticated,
    service_role;
-- =============================================================================
-- ENRICHMENT_BOT: Update enrichment columns only
-- =============================================================================
CREATE OR REPLACE FUNCTION public.enrichment_update_debtor(
        p_judgment_id bigint,
        p_debtor_data jsonb
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_debtor_id uuid;
BEGIN IF NOT public.dragonfly_has_role('enrichment_bot') THEN RAISE EXCEPTION 'Access denied: requires enrichment_bot role' USING ERRCODE = '42501';
END IF;
IF p_judgment_id IS NULL
OR p_debtor_data IS NULL THEN RAISE EXCEPTION 'judgment_id and debtor_data are required';
END IF;
-- Verify judgment exists
IF NOT EXISTS (
    SELECT 1
    FROM public.judgments
    WHERE id = p_judgment_id
) THEN RAISE EXCEPTION 'Judgment % not found',
p_judgment_id USING ERRCODE = 'P0002';
END IF;
-- Insert or update debtor intelligence
INSERT INTO public.debtor_intelligence (
        judgment_id,
        employer_name,
        employer_verified_at,
        bank_name,
        bank_verified_at,
        property_records,
        vehicle_records,
        income_estimate,
        enrichment_source,
        enriched_at,
        metadata
    )
VALUES (
        p_judgment_id,
        p_debtor_data->>'employer_name',
        CASE
            WHEN p_debtor_data ? 'employer_name' THEN timezone('utc', now())
        END,
        p_debtor_data->>'bank_name',
        CASE
            WHEN p_debtor_data ? 'bank_name' THEN timezone('utc', now())
        END,
        p_debtor_data->'property_records',
        p_debtor_data->'vehicle_records',
        (p_debtor_data->>'income_estimate')::numeric,
        COALESCE(p_debtor_data->>'source', 'enrichment_bot'),
        timezone('utc', now()),
        p_debtor_data->'metadata'
    ) ON CONFLICT (judgment_id) DO
UPDATE
SET employer_name = COALESCE(
        EXCLUDED.employer_name,
        public.debtor_intelligence.employer_name
    ),
    employer_verified_at = CASE
        WHEN EXCLUDED.employer_name IS NOT NULL THEN timezone('utc', now())
        ELSE public.debtor_intelligence.employer_verified_at
    END,
    bank_name = COALESCE(
        EXCLUDED.bank_name,
        public.debtor_intelligence.bank_name
    ),
    bank_verified_at = CASE
        WHEN EXCLUDED.bank_name IS NOT NULL THEN timezone('utc', now())
        ELSE public.debtor_intelligence.bank_verified_at
    END,
    property_records = COALESCE(
        EXCLUDED.property_records,
        public.debtor_intelligence.property_records
    ),
    vehicle_records = COALESCE(
        EXCLUDED.vehicle_records,
        public.debtor_intelligence.vehicle_records
    ),
    income_estimate = COALESCE(
        EXCLUDED.income_estimate,
        public.debtor_intelligence.income_estimate
    ),
    enrichment_source = COALESCE(
        EXCLUDED.enrichment_source,
        public.debtor_intelligence.enrichment_source
    ),
    enriched_at = timezone('utc', now()),
    metadata = COALESCE(EXCLUDED.metadata, '{}')::jsonb || COALESCE(public.debtor_intelligence.metadata, '{}')::jsonb,
    updated_at = timezone('utc', now())
RETURNING id INTO v_debtor_id;
RETURN jsonb_build_object(
    'success',
    true,
    'judgment_id',
    p_judgment_id,
    'debtor_intelligence_id',
    v_debtor_id,
    'enriched_at',
    timezone('utc', now())
);
END;
$$;
REVOKE ALL ON FUNCTION public.enrichment_update_debtor(bigint, jsonb)
FROM public;
GRANT EXECUTE ON FUNCTION public.enrichment_update_debtor(bigint, jsonb) TO authenticated,
    service_role;
-- Log enrichment run (enrichment_bot only)
CREATE OR REPLACE FUNCTION public.enrichment_log_run(
        p_case_id uuid,
        p_status text,
        p_provider text DEFAULT NULL,
        p_metadata jsonb DEFAULT NULL
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_run_id uuid;
BEGIN IF NOT public.dragonfly_has_role('enrichment_bot') THEN RAISE EXCEPTION 'Access denied: requires enrichment_bot role' USING ERRCODE = '42501';
END IF;
INSERT INTO judgments.enrichment_runs (case_id, status, provider, metadata)
VALUES (
        p_case_id,
        p_status,
        p_provider,
        COALESCE(p_metadata, '{}'::jsonb)
    )
RETURNING id INTO v_run_id;
RETURN v_run_id;
END;
$$;
REVOKE ALL ON FUNCTION public.enrichment_log_run(uuid, text, text, jsonb)
FROM public;
GRANT EXECUTE ON FUNCTION public.enrichment_log_run(uuid, text, text, jsonb) TO authenticated,
    service_role;
-- =============================================================================
-- OUTREACH_BOT: Update call outcomes only
-- =============================================================================
CREATE OR REPLACE FUNCTION public.outreach_log_call(
        p_plaintiff_id uuid,
        p_task_id uuid DEFAULT NULL,
        p_outcome text DEFAULT NULL,
        p_interest_level text DEFAULT NULL,
        p_notes text DEFAULT NULL,
        p_follow_up_at timestamptz DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_attempt_id uuid;
v_now timestamptz := timezone('utc', now());
BEGIN IF NOT public.dragonfly_has_role('outreach_bot') THEN RAISE EXCEPTION 'Access denied: requires outreach_bot role' USING ERRCODE = '42501';
END IF;
IF p_plaintiff_id IS NULL THEN RAISE EXCEPTION 'plaintiff_id is required';
END IF;
-- Verify plaintiff exists
IF NOT EXISTS (
    SELECT 1
    FROM public.plaintiffs
    WHERE id = p_plaintiff_id
) THEN RAISE EXCEPTION 'Plaintiff % not found',
p_plaintiff_id USING ERRCODE = 'P0002';
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
        p_plaintiff_id,
        p_task_id,
        p_outcome,
        p_interest_level,
        p_notes,
        p_follow_up_at,
        v_now,
        jsonb_build_object('logged_by', 'outreach_bot', 'logged_at', v_now)
    )
RETURNING id INTO v_attempt_id;
-- Close the task if provided
IF p_task_id IS NOT NULL THEN
UPDATE public.plaintiff_tasks
SET status = 'closed',
    completed_at = v_now,
    closed_at = v_now,
    result = p_outcome
WHERE id = p_task_id;
END IF;
RETURN jsonb_build_object(
    'success',
    true,
    'call_attempt_id',
    v_attempt_id,
    'plaintiff_id',
    p_plaintiff_id,
    'outcome',
    p_outcome
);
END;
$$;
REVOKE ALL ON FUNCTION public.outreach_log_call(uuid, uuid, text, text, text, timestamptz)
FROM public;
GRANT EXECUTE ON FUNCTION public.outreach_log_call(uuid, uuid, text, text, text, timestamptz) TO authenticated,
    service_role;
-- Update outreach status (outreach_bot only)
CREATE OR REPLACE FUNCTION public.outreach_update_status(
        p_outreach_id bigint,
        p_status text,
        p_metadata jsonb DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$ BEGIN IF NOT public.dragonfly_has_role('outreach_bot') THEN RAISE EXCEPTION 'Access denied: requires outreach_bot role' USING ERRCODE = '42501';
END IF;
UPDATE public.outreach_log
SET status = p_status,
    metadata = COALESCE(metadata, '{}'::jsonb) || COALESCE(p_metadata, '{}'::jsonb)
WHERE id = p_outreach_id;
IF NOT FOUND THEN RAISE EXCEPTION 'Outreach record % not found',
p_outreach_id USING ERRCODE = 'P0002';
END IF;
RETURN jsonb_build_object(
    'success',
    true,
    'outreach_id',
    p_outreach_id,
    'status',
    p_status
);
END;
$$;
REVOKE ALL ON FUNCTION public.outreach_update_status(bigint, text, jsonb)
FROM public;
GRANT EXECUTE ON FUNCTION public.outreach_update_status(bigint, text, jsonb) TO authenticated,
    service_role;
-- =============================================================================
-- CEO: Read-only financial summary (no column guards needed, just helpful views)
-- =============================================================================
-- CEO financial dashboard view (aggregated, no PII)
CREATE OR REPLACE VIEW public.v_ceo_financial_summary AS
SELECT COUNT(*)::bigint AS total_judgments,
    COALESCE(SUM(judgment_amount), 0)::numeric AS total_portfolio_value,
    COALESCE(AVG(judgment_amount), 0)::numeric AS avg_judgment_amount,
    COUNT(*) FILTER (
        WHERE enforcement_stage = 'collected'
    )::bigint AS collected_count,
    COALESCE(
        SUM(judgment_amount) FILTER (
            WHERE enforcement_stage = 'collected'
        ),
        0
    )::numeric AS collected_amount,
    COUNT(*) FILTER (
        WHERE enforcement_stage IS NULL
            OR enforcement_stage = 'pre_enforcement'
    )::bigint AS pre_enforcement_count,
    COALESCE(
        SUM(judgment_amount) FILTER (
            WHERE enforcement_stage IS NULL
                OR enforcement_stage = 'pre_enforcement'
        ),
        0
    )::numeric AS pre_enforcement_amount
FROM public.judgments;
-- CEO can select from this view
GRANT SELECT ON public.v_ceo_financial_summary TO authenticated;
COMMENT ON FUNCTION public.ops_update_judgment IS 'OPS-only: Update operational judgment fields (stage, priority). Financial fields protected.';
COMMENT ON FUNCTION public.ops_update_plaintiff_status IS 'OPS-only: Update plaintiff status with audit trail.';
COMMENT ON FUNCTION public.ops_update_task IS 'OPS-only: Update task assignment and status.';
COMMENT ON FUNCTION public.enrichment_update_debtor IS 'ENRICHMENT_BOT-only: Update debtor intelligence data.';
COMMENT ON FUNCTION public.enrichment_log_run IS 'ENRICHMENT_BOT-only: Log enrichment run results.';
COMMENT ON FUNCTION public.outreach_log_call IS 'OUTREACH_BOT-only: Log call attempts and outcomes.';
COMMENT ON FUNCTION public.outreach_update_status IS 'OUTREACH_BOT-only: Update outreach record status.';
SELECT public.pgrst_reload();
COMMIT;