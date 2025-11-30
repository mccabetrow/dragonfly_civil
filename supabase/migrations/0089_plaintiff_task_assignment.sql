-- 0089_plaintiff_task_assignment.sql
-- Ensure plaintiff_tasks carries assignment + metadata fields and refresh the open-tasks view.
BEGIN;
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS assignee text,
ADD COLUMN IF NOT EXISTS metadata jsonb;
UPDATE public.plaintiff_tasks
SET metadata = '{}'::jsonb
WHERE metadata IS NULL;
UPDATE public.plaintiff_tasks
SET assignee = 'mom_full_name_or_user_id'
WHERE assignee IS NULL;
ALTER TABLE public.plaintiff_tasks
ALTER COLUMN metadata
SET DEFAULT '{}'::jsonb,
ALTER COLUMN metadata
SET NOT NULL,
ALTER COLUMN assignee
SET DEFAULT 'mom_full_name_or_user_id';
DROP VIEW IF EXISTS public.v_plaintiff_open_tasks;
CREATE OR REPLACE VIEW public.v_plaintiff_open_tasks AS
SELECT
    t.id AS task_id,
    t.plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.email,
    p.phone,
    p.status AS plaintiff_status,
    ov.case_count,
    t.kind,
    t.status,
    t.assignee,
    t.due_at,
    t.created_at,
    t.note,
    t.metadata,
    COALESCE(ov.total_judgment_amount, 0::numeric) AS judgment_total
FROM public.plaintiff_tasks AS t
INNER JOIN public.plaintiffs AS p ON t.plaintiff_id = p.id
LEFT JOIN public.v_plaintiffs_overview AS ov ON p.id = ov.plaintiff_id
WHERE t.status IN ('open', 'in_progress');
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon,
authenticated,
service_role;
COMMIT;
