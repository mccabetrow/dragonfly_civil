-- Reintroduce plaintiff task tracking table and dashboard view consumed by intake flows.
CREATE TABLE IF NOT EXISTS public.plaintiff_tasks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs (
        id
    ) ON DELETE CASCADE,
    kind text NOT NULL,
    status text NOT NULL DEFAULT 'open',
    due_at timestamptz,
    completed_at timestamptz,
    note text,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    created_by text
);
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS id uuid DEFAULT gen_random_uuid(),
ADD COLUMN IF NOT EXISTS plaintiff_id uuid,
ADD COLUMN IF NOT EXISTS kind text,
ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'open',
ADD COLUMN IF NOT EXISTS due_at timestamptz,
ADD COLUMN IF NOT EXISTS completed_at timestamptz,
ADD COLUMN IF NOT EXISTS note text,
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT timezone(
    'utc', now()
),
ADD COLUMN IF NOT EXISTS created_by text;
ALTER TABLE public.plaintiff_tasks
ALTER COLUMN id
SET DEFAULT gen_random_uuid(),
ALTER COLUMN plaintiff_id
SET NOT NULL,
ALTER COLUMN kind
SET NOT NULL,
ALTER COLUMN status
SET DEFAULT 'open',
ALTER COLUMN status
SET NOT NULL,
ALTER COLUMN created_at
SET DEFAULT timezone('utc', now()),
ALTER COLUMN created_at
SET NOT NULL;
DO $$ BEGIN
ALTER TABLE public.plaintiff_tasks
ADD CONSTRAINT plaintiff_tasks_plaintiff_id_fkey FOREIGN KEY (plaintiff_id) REFERENCES public.plaintiffs(id) ON DELETE CASCADE;
EXCEPTION
WHEN duplicate_object THEN NULL;
END;
$$;
CREATE INDEX IF NOT EXISTS plaintiff_tasks_plaintiff_status_due_idx ON public.plaintiff_tasks (
    plaintiff_id, status, due_at
);
CREATE OR REPLACE VIEW public.v_plaintiff_open_tasks AS
SELECT
    t.id AS task_id,
    t.plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    t.kind,
    t.status,
    t.due_at,
    t.created_at,
    t.note
FROM public.plaintiff_tasks AS t
INNER JOIN public.plaintiffs AS p ON t.plaintiff_id = p.id
WHERE t.status IN ('open', 'in_progress');
GRANT SELECT ON TABLE public.plaintiff_tasks TO anon,
authenticated;
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon,
authenticated;
GRANT SELECT ON TABLE public.plaintiff_tasks TO anon,
authenticated,
service_role;
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon,
authenticated,
service_role;
