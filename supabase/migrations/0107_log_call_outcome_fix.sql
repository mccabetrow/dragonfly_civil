-- 0107_log_call_outcome_fix.sql
-- Purpose: ensure the call workflow RPC exists with the required six-argument signature and supporting tables.
-- migrate:up
BEGIN;
CREATE TABLE IF NOT EXISTS public.plaintiff_call_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs(id) ON DELETE CASCADE,
    task_id uuid REFERENCES public.plaintiff_tasks(id) ON DELETE
    SET NULL,
        outcome text NOT NULL,
        interest_level text,
        notes text,
        next_follow_up_at timestamptz,
        attempted_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_plaintiff_call_attempts_plaintiff_id_attempted_at ON public.plaintiff_call_attempts (plaintiff_id, attempted_at DESC);
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS closed_at timestamptz,
    ADD COLUMN IF NOT EXISTS result text;
DROP FUNCTION IF EXISTS public.log_call_outcome(uuid, uuid, text, text, text, timestamptz);
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
BEGIN -- Determine normalized status bucket.
IF _outcome = 'do_not_call' THEN v_status := 'do_not_call';
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
COMMIT;
-- migrate:down
BEGIN;
REVOKE EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz)
FROM anon,
    authenticated,
    service_role;
DROP FUNCTION IF EXISTS public.log_call_outcome(uuid, uuid, text, text, text, timestamptz);
DROP INDEX IF EXISTS idx_plaintiff_call_attempts_plaintiff_id_attempted_at;
DROP TABLE IF EXISTS public.plaintiff_call_attempts;
ALTER TABLE public.plaintiff_tasks DROP COLUMN IF EXISTS result,
    DROP COLUMN IF EXISTS closed_at;
COMMIT;
-- Dev sanity:
--   cd C:\Users\mccab\dragonfly_civil
--   $env:SUPABASE_MODE = 'dev'
--   ./scripts/db_push.ps1 -SupabaseEnv dev
--   .\.venv\Scripts\python.exe -m pytest tests/test_plaintiff_call_outcomes.py -q
