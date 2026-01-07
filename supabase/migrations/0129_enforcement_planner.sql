-- 0129_enforcement_planner.sql
-- Enforcement Task Planner v2: severity tiers, scheduling RPC, and idempotent task definitions.
BEGIN;
DO $$ BEGIN CREATE TYPE public.enforcement_task_kind AS ENUM (
    'enforcement_phone_attempt',
    'enforcement_phone_follow_up',
    'enforcement_mailer',
    'enforcement_demand_letter',
    'enforcement_wage_garnishment_prep',
    'enforcement_bank_levy_prep',
    'enforcement_skiptrace_refresh'
);
EXCEPTION
WHEN duplicate_object THEN NULL;
END;
$$;
DO $$ BEGIN CREATE TYPE public.enforcement_task_severity AS ENUM ('low', 'medium', 'high');
EXCEPTION
WHEN duplicate_object THEN NULL;
END;
$$;
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS case_id uuid REFERENCES public.enforcement_cases(id) ON DELETE
SET NULL,
    ADD COLUMN IF NOT EXISTS severity public.enforcement_task_severity NOT NULL DEFAULT 'medium',
    ADD COLUMN IF NOT EXISTS task_code public.enforcement_task_kind,
    ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT timezone('utc', now());
UPDATE public.plaintiff_tasks
SET severity = 'medium'
WHERE severity IS NULL;
DROP TRIGGER IF EXISTS plaintiff_tasks_touch_updated_at ON public.plaintiff_tasks;
CREATE TRIGGER plaintiff_tasks_touch_updated_at BEFORE
UPDATE ON public.plaintiff_tasks FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
CREATE UNIQUE INDEX IF NOT EXISTS plaintiff_tasks_case_task_code_open_idx ON public.plaintiff_tasks (case_id, task_code)
WHERE case_id IS NOT NULL
    AND task_code IS NOT NULL
    AND status IN ('open', 'in_progress');
DROP VIEW IF EXISTS public.v_plaintiff_call_queue;
DROP VIEW IF EXISTS public.v_plaintiff_open_tasks;
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
    ) AS contact_info ON true
WHERE r.task_rank = 1
ORDER BY r.due_at NULLS LAST,
    contact_info.last_contact_at NULLS FIRST,
    r.plaintiff_name;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
    authenticated,
    service_role;
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
        task_code,
        due_at,
        severity
)
SELECT id,
    task_code,
    due_at,
    severity
FROM inserted;
END;
$$;
REVOKE ALL ON FUNCTION public.generate_enforcement_tasks(uuid)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.generate_enforcement_tasks(uuid) TO authenticated,
    service_role;
COMMIT;
