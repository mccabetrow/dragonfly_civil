-- 0133_case_copilot_v2.sql
-- Case Copilot v2 context RPC powering multi-surface AI features.
BEGIN;
CREATE OR REPLACE FUNCTION public.copilot_case_context(p_case_id uuid) RETURNS TABLE (
        case_id uuid,
        context jsonb
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE timeline_limit integer := 30;
task_limit integer := 25;
contact_limit integer := 10;
status_history_limit integer := 10;
call_attempt_limit integer := 10;
now_utc timestamptz := timezone('utc', now());
BEGIN IF p_case_id IS NULL THEN RAISE EXCEPTION 'copilot_case_context: case_id is required' USING ERRCODE = '23502';
END IF;
PERFORM 1
FROM public.enforcement_cases ec
WHERE ec.id = p_case_id;
IF NOT FOUND THEN RAISE EXCEPTION 'copilot_case_context: enforcement case % not found',
p_case_id USING ERRCODE = 'P0002';
END IF;
PERFORM 1
FROM public.v_enforcement_case_summary ecs
WHERE ecs.case_id = p_case_id;
IF NOT FOUND THEN RAISE EXCEPTION 'copilot_case_context: case summary missing for %',
p_case_id USING ERRCODE = 'P0002';
END IF;
RETURN QUERY WITH base AS (
    SELECT ecs.case_id,
        ecs.judgment_id,
        ecs.case_number,
        ecs.opened_at,
        ecs.current_stage,
        ecs.status AS case_status,
        ecs.assigned_to,
        ecs.metadata,
        ecs.created_at,
        ecs.updated_at,
        ecs.judgment_amount,
        ecs.plaintiff_id,
        ecs.plaintiff_name,
        ecs.latest_event_type,
        ecs.latest_event_date,
        ecs.latest_event_note,
        j.case_number AS judgment_case_number,
        j.priority_level,
        j.enforcement_stage,
        j.county,
        j.state,
        j.defendant_name
    FROM public.v_enforcement_case_summary ecs
        JOIN public.judgments j ON j.id = ecs.judgment_id
    WHERE ecs.case_id = p_case_id
    LIMIT 1
), timeline AS (
    SELECT COALESCE(
            jsonb_agg(
                jsonb_strip_nulls(
                    jsonb_build_object(
                        'item_kind',
                        t.item_kind,
                        'title',
                        t.title,
                        'details',
                        t.details,
                        'occurred_at',
                        t.occurred_at,
                        'uploaded_by',
                        t.uploaded_by,
                        'storage_path',
                        t.storage_path,
                        'file_type',
                        t.file_type,
                        'metadata',
                        t.metadata
                    )
                )
                ORDER BY t.occurred_at DESC NULLS LAST,
                    t.created_at DESC NULLS LAST,
                    t.source_id DESC
            ),
            '[]'::jsonb
        ) AS entries,
        COALESCE(
            COUNT(*) FILTER (
                WHERE t.item_kind = 'event'
            ),
            0
        ) AS event_count,
        COALESCE(
            COUNT(*) FILTER (
                WHERE t.item_kind = 'evidence'
            ),
            0
        ) AS evidence_count,
        MAX(t.occurred_at) AS latest_activity_at,
        MIN(t.occurred_at) AS earliest_activity_at
    FROM (
            SELECT *
            FROM public.v_enforcement_timeline et
            WHERE et.case_id = p_case_id
            ORDER BY et.occurred_at DESC NULLS LAST,
                et.created_at DESC NULLS LAST,
                et.source_id DESC
            LIMIT timeline_limit
        ) t
), tasks AS (
    SELECT COALESCE(
            jsonb_agg(
                jsonb_strip_nulls(
                    jsonb_build_object(
                        'task_id',
                        t.id,
                        'kind',
                        t.kind,
                        'status',
                        t.status,
                        'severity',
                        t.severity,
                        'assignee',
                        t.assignee,
                        'due_at',
                        t.due_at,
                        'created_at',
                        t.created_at,
                        'note',
                        t.note,
                        'metadata',
                        t.metadata
                    )
                )
                ORDER BY t.due_at NULLS LAST,
                    t.created_at DESC
            ),
            '[]'::jsonb
        ) AS items,
        COALESCE(
            SUM(
                CASE
                    WHEN t.status IN ('open', 'in_progress') THEN 1
                    ELSE 0
                END
            ),
            0
        ) AS open_count,
        COALESCE(
            SUM(
                CASE
                    WHEN t.status IN ('open', 'in_progress')
                    AND t.due_at IS NOT NULL
                    AND t.due_at < now_utc THEN 1
                    ELSE 0
                END
            ),
            0
        ) AS overdue_count
    FROM (
            SELECT *
            FROM public.plaintiff_tasks pt
            WHERE pt.case_id = p_case_id
            ORDER BY pt.created_at DESC
            LIMIT task_limit
        ) t
), collectability AS (
    SELECT jsonb_strip_nulls(
            jsonb_build_object(
                'tier',
                cs.collectability_tier,
                'judgment_amount',
                cs.judgment_amount,
                'age_days',
                cs.age_days,
                'last_enriched_at',
                cs.last_enriched_at,
                'last_enrichment_status',
                cs.last_enrichment_status
            )
        ) AS payload
    FROM base
        LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = base.judgment_case_number
),
priority AS (
    SELECT jsonb_strip_nulls(
            jsonb_build_object(
                'stage',
                vp.stage,
                'priority_level',
                vp.priority_level,
                'plaintiff_status',
                vp.plaintiff_status,
                'collectability_tier',
                vp.collectability_tier,
                'judgment_amount',
                vp.judgment_amount
            )
        ) AS payload
    FROM base
        LEFT JOIN LATERAL (
            SELECT *
            FROM public.v_priority_pipeline vp
            WHERE vp.judgment_id = base.judgment_id
            LIMIT 1
        ) vp ON TRUE
),
import_meta AS (
    SELECT jsonb_strip_nulls(
            jsonb_build_object(
                'import_run_id',
                ir.id::text,
                'import_kind',
                ir.import_kind,
                'source_system',
                ir.source_system,
                'source_reference',
                ir.source_reference,
                'batch_name',
                ir.metadata->>'batch_name',
                'file_name',
                ir.file_name,
                'status',
                ir.status,
                'started_at',
                ir.started_at,
                'finished_at',
                ir.finished_at,
                'summary',
                ir.metadata->'summary'
            )
        ) AS payload
    FROM base
        LEFT JOIN LATERAL (
            SELECT *
            FROM public.import_runs ir
            WHERE ir.metadata ? 'row_operations'
                AND EXISTS (
                    SELECT 1
                    FROM jsonb_array_elements(ir.metadata->'row_operations') op
                    WHERE op->>'judgment_id' = base.judgment_id::text
                        OR (
                            base.plaintiff_id IS NOT NULL
                            AND op->>'plaintiff_id' = base.plaintiff_id::text
                        )
                )
            ORDER BY ir.started_at DESC NULLS LAST
            LIMIT 1
        ) ir ON TRUE
),
contacts AS (
    SELECT CASE
            WHEN base.plaintiff_id IS NULL THEN NULL::jsonb
            ELSE jsonb_strip_nulls(
                jsonb_build_object(
                    'primary_contact',
                    (
                        SELECT jsonb_strip_nulls(
                                jsonb_build_object(
                                    'contact_id',
                                    pc.id,
                                    'name',
                                    pc.name,
                                    'email',
                                    pc.email,
                                    'phone',
                                    pc.phone,
                                    'role',
                                    pc.role,
                                    'kind',
                                    pc.kind,
                                    'value',
                                    pc.value,
                                    'created_at',
                                    pc.created_at
                                )
                            )
                        FROM public.plaintiff_contacts pc
                        WHERE pc.plaintiff_id = base.plaintiff_id
                        ORDER BY pc.created_at DESC
                        LIMIT 1
                    ), 'contacts', COALESCE(
                        (
                            SELECT jsonb_agg(
                                    jsonb_strip_nulls(
                                        jsonb_build_object(
                                            'contact_id',
                                            pc.id,
                                            'name',
                                            pc.name,
                                            'email',
                                            pc.email,
                                            'phone',
                                            pc.phone,
                                            'role',
                                            pc.role,
                                            'kind',
                                            pc.kind,
                                            'value',
                                            pc.value,
                                            'created_at',
                                            pc.created_at
                                        )
                                    )
                                    ORDER BY pc.created_at DESC
                                )
                            FROM (
                                    SELECT *
                                    FROM public.plaintiff_contacts pc
                                    WHERE pc.plaintiff_id = base.plaintiff_id
                                    ORDER BY pc.created_at DESC
                                    LIMIT contact_limit
                                ) pc
                        ), '[]'::jsonb
                    ), 'status_history', COALESCE(
                        (
                            SELECT jsonb_agg(
                                    jsonb_strip_nulls(
                                        jsonb_build_object(
                                            'status',
                                            psh.status,
                                            'note',
                                            psh.note,
                                            'changed_at',
                                            psh.changed_at,
                                            'changed_by',
                                            psh.changed_by
                                        )
                                    )
                                    ORDER BY psh.changed_at DESC
                                )
                            FROM (
                                    SELECT *
                                    FROM public.plaintiff_status_history psh
                                    WHERE psh.plaintiff_id = base.plaintiff_id
                                    ORDER BY psh.changed_at DESC
                                    LIMIT status_history_limit
                                ) psh
                        ), '[]'::jsonb
                    ), 'call_attempts', COALESCE(
                        (
                            SELECT jsonb_agg(
                                    jsonb_strip_nulls(
                                        jsonb_build_object(
                                            'attempt_id',
                                            pca.id,
                                            'outcome',
                                            pca.outcome,
                                            'interest_level',
                                            pca.interest_level,
                                            'notes',
                                            pca.notes,
                                            'attempted_at',
                                            pca.attempted_at,
                                            'assignee',
                                            pca.assignee,
                                            'next_follow_up_at',
                                            pca.next_follow_up_at
                                        )
                                    )
                                    ORDER BY pca.attempted_at DESC
                                )
                            FROM (
                                    SELECT *
                                    FROM public.plaintiff_call_attempts pca
                                    WHERE pca.plaintiff_id = base.plaintiff_id
                                    ORDER BY pca.attempted_at DESC
                                    LIMIT call_attempt_limit
                                ) pca
                        ), '[]'::jsonb
                    ), 'last_contacted_at', NULLIF(
                        (
                            SELECT GREATEST(
                                    COALESCE(
                                        (
                                            SELECT MAX(psh.changed_at)
                                            FROM public.plaintiff_status_history psh
                                            WHERE psh.plaintiff_id = base.plaintiff_id
                                                AND psh.status IN (
                                                    'contacted',
                                                    'qualified',
                                                    'sent_agreement',
                                                    'signed'
                                                )
                                        ),
                                        '-infinity'::timestamptz
                                    ),
                                    COALESCE(
                                        (
                                            SELECT MAX(pca.attempted_at)
                                            FROM public.plaintiff_call_attempts pca
                                            WHERE pca.plaintiff_id = base.plaintiff_id
                                        ),
                                        '-infinity'::timestamptz
                                    )
                                )
                        ),
                        '-infinity'::timestamptz
                    )
                )
            )
        END AS payload
    FROM base
)
SELECT base.case_id,
    jsonb_strip_nulls(
        jsonb_build_object(
            'case',
            jsonb_strip_nulls(
                jsonb_build_object(
                    'case_id',
                    base.case_id,
                    'case_number',
                    base.case_number,
                    'judgment_case_number',
                    base.judgment_case_number,
                    'opened_at',
                    base.opened_at,
                    'case_age_days',
                    CASE
                        WHEN base.opened_at IS NULL THEN NULL
                        ELSE GREATEST(
                            DATE_PART('day', now_utc - base.opened_at)::int,
                            0
                        )
                    END,
                    'current_stage',
                    base.current_stage,
                    'status',
                    base.case_status,
                    'assigned_to',
                    base.assigned_to,
                    'latest_event_type',
                    base.latest_event_type,
                    'latest_event_date',
                    base.latest_event_date,
                    'latest_event_note',
                    base.latest_event_note,
                    'metadata',
                    base.metadata,
                    'created_at',
                    base.created_at,
                    'updated_at',
                    base.updated_at,
                    'defendant_name',
                    base.defendant_name
                )
            ),
            'judgment',
            jsonb_strip_nulls(
                jsonb_build_object(
                    'judgment_id',
                    base.judgment_id,
                    'amount',
                    base.judgment_amount,
                    'county',
                    base.county,
                    'state',
                    base.state,
                    'priority_level',
                    base.priority_level,
                    'enforcement_stage',
                    base.enforcement_stage
                )
            ),
            'plaintiff',
            (
                SELECT jsonb_strip_nulls(
                        jsonb_build_object(
                            'plaintiff_id',
                            p.id,
                            'name',
                            p.name,
                            'firm_name',
                            p.firm_name,
                            'email',
                            p.email,
                            'phone',
                            p.phone,
                            'status',
                            p.status,
                            'tier',
                            p.tier,
                            'source_system',
                            p.source_system
                        )
                    )
                FROM public.plaintiffs p
                WHERE p.id = base.plaintiff_id
            ),
            'collectability',
            COALESCE(collectability.payload, '{}'::jsonb),
            'priority',
            COALESCE(priority.payload, '{}'::jsonb),
            'timeline',
            timeline.entries,
            'timeline_stats',
            jsonb_strip_nulls(
                jsonb_build_object(
                    'event_count',
                    timeline.event_count,
                    'evidence_count',
                    timeline.evidence_count,
                    'latest_activity_at',
                    timeline.latest_activity_at,
                    'earliest_activity_at',
                    timeline.earliest_activity_at
                )
            ),
            'tasks',
            jsonb_build_object(
                'open_count',
                tasks.open_count,
                'overdue_count',
                tasks.overdue_count,
                'items',
                tasks.items
            ),
            'contacts',
            contacts.payload,
            'import_metadata',
            import_meta.payload,
            'risk_inputs',
            jsonb_strip_nulls(
                jsonb_build_object(
                    'case_age_days',
                    CASE
                        WHEN base.opened_at IS NULL THEN NULL
                        ELSE GREATEST(
                            DATE_PART('day', now_utc - base.opened_at)::int,
                            0
                        )
                    END,
                    'collectability_tier',
                    COALESCE(
                        priority.payload->>'collectability_tier',
                        collectability.payload->>'tier'
                    ),
                    'open_tasks',
                    tasks.open_count,
                    'overdue_tasks',
                    tasks.overdue_count,
                    'latest_event_age_days',
                    CASE
                        WHEN base.latest_event_date IS NULL THEN NULL
                        ELSE GREATEST(
                            DATE_PART('day', now_utc - base.latest_event_date)::int,
                            0
                        )
                    END,
                    'timeline_event_count',
                    timeline.event_count,
                    'timeline_evidence_count',
                    timeline.evidence_count,
                    'latest_activity_at',
                    timeline.latest_activity_at
                )
            )
        )
    ) AS context
FROM base
    CROSS JOIN timeline
    CROSS JOIN tasks
    LEFT JOIN collectability ON TRUE
    LEFT JOIN priority ON TRUE
    LEFT JOIN import_meta ON TRUE
    LEFT JOIN contacts ON TRUE;
END;
$$;
REVOKE ALL ON FUNCTION public.copilot_case_context(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.copilot_case_context(uuid) TO anon;
GRANT EXECUTE ON FUNCTION public.copilot_case_context(uuid) TO authenticated;
GRANT EXECUTE ON FUNCTION public.copilot_case_context(uuid) TO service_role;
-- Refresh the Case Copilot latest view to surface the richer v2 metadata
DROP VIEW IF EXISTS public.v_case_copilot_latest;
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
    COALESCE(actions.actions_array, ARRAY []::text []) AS recommended_actions,
    COALESCE(
        r.metadata->'enforcement_suggestions',
        '[]'::jsonb
    ) AS enforcement_suggestions,
    COALESCE(r.metadata->'draft_documents', '[]'::jsonb) AS draft_documents,
    NULLIF(r.metadata->'risk'->>'value', '')::int AS risk_value,
    r.metadata->'risk'->>'label' AS risk_label,
    COALESCE(risk.drivers_array, ARRAY []::text []) AS risk_drivers,
    COALESCE(r.metadata->'timeline_analysis', '[]'::jsonb) AS timeline_analysis,
    COALESCE(r.metadata->'contact_strategy', '[]'::jsonb) AS contact_strategy,
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
    LEFT JOIN LATERAL (
        SELECT array_agg(elem) AS drivers_array
        FROM jsonb_array_elements_text(r.metadata->'risk'->'drivers') elem
    ) risk ON (r.metadata->'risk' ? 'drivers')
WHERE r.row_num = 1;
GRANT SELECT ON public.v_case_copilot_latest TO service_role;
COMMIT;