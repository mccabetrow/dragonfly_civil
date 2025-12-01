-- 0090_plaintiff_task_conflict_target.sql
-- Support ON CONFLICT clauses for call-task enqueue logic.
BEGIN;
CREATE UNIQUE INDEX IF NOT EXISTS plaintiff_tasks_unique_kind_status ON public.plaintiff_tasks (
    plaintiff_id, kind, status
);
COMMIT;
