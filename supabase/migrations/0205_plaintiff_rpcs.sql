-- Migration: 0205_plaintiff_rpcs.sql
-- Purpose: Add RPCs for plaintiff status and task management
-- These RPCs allow n8n to update plaintiff data through controlled interfaces
-- rather than direct table writes.
--
-- Depends on: 0200+ schema (plaintiffs, plaintiff_status_history, plaintiff_tasks)
--------------------------------------------------------------------------------
-- RPC: update_plaintiff_status
-- Atomically updates plaintiff status and writes to status history
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.update_plaintiff_status(
        p_plaintiff_id uuid,
        p_new_status text,
        p_note text DEFAULT NULL,
        p_changed_by text DEFAULT 'system'
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE v_old_status text;
v_history_id uuid;
v_result jsonb;
BEGIN -- Validate plaintiff exists and get current status
SELECT status INTO v_old_status
FROM plaintiffs
WHERE id = p_plaintiff_id FOR
UPDATE;
IF NOT FOUND THEN RETURN jsonb_build_object(
    'success',
    false,
    'error',
    'plaintiff_not_found',
    'plaintiff_id',
    p_plaintiff_id
);
END IF;
-- Skip if status unchanged
IF v_old_status = p_new_status THEN RETURN jsonb_build_object(
    'success',
    true,
    'plaintiff_id',
    p_plaintiff_id,
    'status',
    p_new_status,
    'changed',
    false,
    'note',
    'Status unchanged'
);
END IF;
-- Update plaintiff status
UPDATE plaintiffs
SET status = p_new_status,
    updated_at = now()
WHERE id = p_plaintiff_id;
-- Write status history
INSERT INTO plaintiff_status_history (
        plaintiff_id,
        status,
        note,
        changed_by,
        created_at
    )
VALUES (
        p_plaintiff_id,
        p_new_status,
        COALESCE(
            p_note,
            'Status changed from ' || v_old_status || ' to ' || p_new_status
        ),
        p_changed_by,
        now()
    )
RETURNING id INTO v_history_id;
v_result := jsonb_build_object(
    'success',
    true,
    'plaintiff_id',
    p_plaintiff_id,
    'old_status',
    v_old_status,
    'new_status',
    p_new_status,
    'history_id',
    v_history_id,
    'changed',
    true,
    'changed_by',
    p_changed_by
);
RETURN v_result;
END;
$$;
COMMENT ON FUNCTION public.update_plaintiff_status IS 'Atomically updates plaintiff status and writes audit history. Use from n8n/workers instead of direct table writes.';
-- Grant to service_role only (n8n uses service key)
REVOKE ALL ON FUNCTION public.update_plaintiff_status
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.update_plaintiff_status TO service_role;
--------------------------------------------------------------------------------
-- RPC: upsert_plaintiff_task
-- Creates or updates a plaintiff task with proper idempotency
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.upsert_plaintiff_task(
        p_plaintiff_id uuid,
        p_kind text,
        p_due_at timestamptz DEFAULT NULL,
        p_metadata jsonb DEFAULT '{}'::jsonb,
        p_created_by text DEFAULT 'system'
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE v_task_id uuid;
v_is_new boolean := false;
v_existing_status text;
BEGIN -- Validate plaintiff exists
IF NOT EXISTS (
    SELECT 1
    FROM plaintiffs
    WHERE id = p_plaintiff_id
) THEN RETURN jsonb_build_object(
    'success',
    false,
    'error',
    'plaintiff_not_found',
    'plaintiff_id',
    p_plaintiff_id
);
END IF;
-- Check for existing open task of same kind
SELECT id,
    status INTO v_task_id,
    v_existing_status
FROM plaintiff_tasks
WHERE plaintiff_id = p_plaintiff_id
    AND kind = p_kind
    AND status NOT IN ('completed', 'cancelled')
ORDER BY created_at DESC
LIMIT 1;
IF v_task_id IS NOT NULL THEN -- Update existing task
UPDATE plaintiff_tasks
SET due_at = COALESCE(p_due_at, due_at),
    metadata = metadata || p_metadata,
    updated_at = now()
WHERE id = v_task_id;
ELSE -- Create new task
v_is_new := true;
INSERT INTO plaintiff_tasks (
        plaintiff_id,
        kind,
        status,
        due_at,
        metadata,
        created_by,
        created_at
    )
VALUES (
        p_plaintiff_id,
        p_kind,
        'pending',
        COALESCE(p_due_at, now() + interval '1 day'),
        p_metadata,
        p_created_by,
        now()
    )
RETURNING id INTO v_task_id;
END IF;
RETURN jsonb_build_object(
    'success',
    true,
    'task_id',
    v_task_id,
    'plaintiff_id',
    p_plaintiff_id,
    'kind',
    p_kind,
    'is_new',
    v_is_new,
    'created_by',
    p_created_by
);
END;
$$;
COMMENT ON FUNCTION public.upsert_plaintiff_task IS 'Idempotently creates or updates a plaintiff task. Prevents duplicate open tasks of the same kind.';
-- Grant to service_role only
REVOKE ALL ON FUNCTION public.upsert_plaintiff_task
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.upsert_plaintiff_task TO service_role;
--------------------------------------------------------------------------------
-- RPC: complete_plaintiff_task
-- Marks a task complete and optionally logs outcome
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.complete_plaintiff_task(
        p_task_id uuid,
        p_outcome text DEFAULT 'completed',
        p_notes text DEFAULT NULL,
        p_completed_by text DEFAULT 'system'
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE v_plaintiff_id uuid;
v_kind text;
v_old_status text;
BEGIN -- Get task details
SELECT plaintiff_id,
    kind,
    status INTO v_plaintiff_id,
    v_kind,
    v_old_status
FROM plaintiff_tasks
WHERE id = p_task_id FOR
UPDATE;
IF NOT FOUND THEN RETURN jsonb_build_object(
    'success',
    false,
    'error',
    'task_not_found',
    'task_id',
    p_task_id
);
END IF;
-- Already completed?
IF v_old_status IN ('completed', 'cancelled') THEN RETURN jsonb_build_object(
    'success',
    true,
    'task_id',
    p_task_id,
    'changed',
    false,
    'note',
    'Task already in terminal status: ' || v_old_status
);
END IF;
-- Complete the task
UPDATE plaintiff_tasks
SET status = 'completed',
    outcome = p_outcome,
    notes = p_notes,
    completed_by = p_completed_by,
    completed_at = now(),
    updated_at = now()
WHERE id = p_task_id;
RETURN jsonb_build_object(
    'success',
    true,
    'task_id',
    p_task_id,
    'plaintiff_id',
    v_plaintiff_id,
    'kind',
    v_kind,
    'outcome',
    p_outcome,
    'changed',
    true,
    'completed_by',
    p_completed_by
);
END;
$$;
COMMENT ON FUNCTION public.complete_plaintiff_task IS 'Marks a plaintiff task as completed with optional outcome and notes.';
-- Grant to service_role only
REVOKE ALL ON FUNCTION public.complete_plaintiff_task
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.complete_plaintiff_task TO service_role;
--------------------------------------------------------------------------------
-- RPC: advance_import_run
-- Updates import_run status with proper transitions
--------------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.advance_import_run(
        p_import_run_id uuid,
        p_new_status text,
        p_metadata jsonb DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public AS $$
DECLARE v_old_status text;
v_valid_transitions text [];
BEGIN -- Get current status
SELECT status INTO v_old_status
FROM import_runs
WHERE id = p_import_run_id FOR
UPDATE;
IF NOT FOUND THEN RETURN jsonb_build_object(
    'success',
    false,
    'error',
    'import_run_not_found',
    'import_run_id',
    p_import_run_id
);
END IF;
-- Define valid status transitions
v_valid_transitions := CASE
    v_old_status
    WHEN 'pending' THEN ARRAY ['ready_for_queue', 'queued', 'cancelled']
    WHEN 'ready_for_queue' THEN ARRAY ['queued', 'processing', 'cancelled']
    WHEN 'queued' THEN ARRAY ['processing', 'failed', 'cancelled']
    WHEN 'processing' THEN ARRAY ['completed', 'failed']
    ELSE ARRAY []::text []
END;
IF NOT (p_new_status = ANY(v_valid_transitions)) THEN RETURN jsonb_build_object(
    'success',
    false,
    'error',
    'invalid_transition',
    'import_run_id',
    p_import_run_id,
    'from_status',
    v_old_status,
    'to_status',
    p_new_status,
    'valid_transitions',
    v_valid_transitions
);
END IF;
-- Perform update
UPDATE import_runs
SET status = p_new_status,
    metadata = CASE
        WHEN p_metadata IS NOT NULL THEN COALESCE(metadata, '{}'::jsonb) || p_metadata
        ELSE metadata
    END,
    updated_at = now(),
    completed_at = CASE
        WHEN p_new_status IN ('completed', 'failed') THEN now()
        ELSE completed_at
    END
WHERE id = p_import_run_id;
RETURN jsonb_build_object(
    'success',
    true,
    'import_run_id',
    p_import_run_id,
    'old_status',
    v_old_status,
    'new_status',
    p_new_status
);
END;
$$;
COMMENT ON FUNCTION public.advance_import_run IS 'Advances an import_run through valid status transitions with metadata updates.';
-- Grant to service_role only
REVOKE ALL ON FUNCTION public.advance_import_run
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.advance_import_run TO service_role;
