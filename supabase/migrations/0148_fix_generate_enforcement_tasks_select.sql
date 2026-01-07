-- 0148_fix_generate_enforcement_tasks_select.sql
-- Qualify CTE output when returning rows from generate_enforcement_tasks.
BEGIN;
CREATE OR REPLACE FUNCTION public.generate_enforcement_tasks(case_id uuid) RETURNS TABLE(
        task_id uuid,
        task_code public.enforcement_task_kind,
        due_at timestamptz,
        severity public.enforcement_task_severity
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE target_case_id uuid := case_id;
v_case RECORD;
v_now timestamptz := timezone('utc', now());
BEGIN IF target_case_id IS NULL THEN RAISE EXCEPTION 'generate_enforcement_tasks: case_id is required';
END IF;
SELECT ec.id,
    ec.judgment_id,
    COALESCE(j.plaintiff_id, NULL) AS plaintiff_id INTO v_case
FROM public.enforcement_cases ec
    LEFT JOIN public.judgments j ON j.id = ec.judgment_id
WHERE ec.id = target_case_id
LIMIT 1;
IF v_case.id IS NULL THEN RAISE EXCEPTION 'generate_enforcement_tasks: enforcement case % not found',
target_case_id USING ERRCODE = 'P0002';
END IF;
IF v_case.plaintiff_id IS NULL THEN RAISE EXCEPTION 'generate_enforcement_tasks: plaintiff missing for case %',
target_case_id USING ERRCODE = '23502';
END IF;
RETURN QUERY WITH defs AS (
    SELECT *
    FROM (
            VALUES (
                    'enforcement_phone_attempt',
                    'enforcement_phone_attempt',
                    'medium',
                    0,
                    'Place immediate enforcement phone call to confirm borrower contact info.',
                    7,
                    'phone',
                    'follow_up_7_days'
                ),
                (
                    'enforcement_phone_follow_up',
                    'enforcement_phone_follow_up',
                    'medium',
                    7,
                    'Follow up on phone outreach (7-day rule).',
                    7,
                    'phone',
                    'follow_up_7_days'
                ),
                (
                    'enforcement_mailer',
                    'enforcement_mailer',
                    'low',
                    7,
                    'Send enforcement mailer packet to borrower and employer.',
                    NULL,
                    'mail',
                    'follow_up_7_days'
                ),
                (
                    'enforcement_demand_letter',
                    'enforcement_demand_letter',
                    'high',
                    14,
                    'Prepare and send demand letter (14-day escalation).',
                    NULL,
                    'legal',
                    'escalation_14_days'
                ),
                (
                    'enforcement_wage_garnishment_prep',
                    'enforcement_wage_garnishment_prep',
                    'high',
                    14,
                    'Gather payroll intel for wage garnishment filing.',
                    NULL,
                    'legal',
                    'escalation_14_days'
                ),
                (
                    'enforcement_bank_levy_prep',
                    'enforcement_bank_levy_prep',
                    'high',
                    14,
                    'Review assets and prepare bank levy paperwork.',
                    NULL,
                    'legal',
                    'escalation_14_days'
                ),
                (
                    'enforcement_skiptrace_refresh',
                    'enforcement_skiptrace_refresh',
                    'medium',
                    30,
                    'Refresh skiptrace data (30-day cycle).',
                    30,
                    'research',
                    'refresh_30_days'
                )
        ) AS d(
            task_code_text,
            kind_text,
            severity_text,
            offset_days,
            note,
            frequency_days,
            category,
            rule_code
        )
),
inserted AS (
    INSERT INTO public.plaintiff_tasks (
            plaintiff_id,
            case_id,
            kind,
            status,
            severity,
            due_at,
            note,
            assignee,
            metadata,
            created_by,
            task_code
        )
    SELECT v_case.plaintiff_id,
        v_case.id,
        d.kind_text,
        'open',
        d.severity_text::public.enforcement_task_severity,
        v_now + (d.offset_days || ' days')::interval,
        d.note,
        NULL,
        jsonb_strip_nulls(
            jsonb_build_object(
                'task_code',
                d.task_code_text,
                'category',
                d.category,
                'frequency_days',
                d.frequency_days,
                'rule',
                d.rule_code,
                'planned_at',
                v_now
            )
        ),
        'enforcement_planner_v2',
        d.task_code_text::public.enforcement_task_kind
    FROM defs d
    WHERE NOT EXISTS (
            SELECT 1
            FROM public.plaintiff_tasks existing
            WHERE existing.case_id = v_case.id
                AND existing.task_code = d.task_code_text::public.enforcement_task_kind
                AND existing.status IN ('open', 'in_progress')
        )
    RETURNING id,
        public.plaintiff_tasks.task_code,
        public.plaintiff_tasks.due_at,
        public.plaintiff_tasks.severity
)
SELECT inserted.id,
    inserted.task_code,
    inserted.due_at,
    inserted.severity
FROM inserted;
END;
$$;
REVOKE ALL ON FUNCTION public.generate_enforcement_tasks(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.generate_enforcement_tasks(uuid) TO authenticated,
    service_role;
COMMIT;
