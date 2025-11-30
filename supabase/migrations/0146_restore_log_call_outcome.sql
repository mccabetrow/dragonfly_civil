-- 0146_restore_log_call_outcome.sql
-- Restore the six-argument log_call_outcome RPC with follow-up creation semantics.
BEGIN;
ALTER TABLE public.plaintiff_call_attempts
ADD COLUMN IF NOT EXISTS task_id uuid REFERENCES public.plaintiff_tasks(id) ON DELETE
SET NULL,
    ADD COLUMN IF NOT EXISTS metadata jsonb DEFAULT '{}'::jsonb;
ALTER TABLE public.plaintiff_call_attempts
ALTER COLUMN metadata
SET DEFAULT '{}'::jsonb;
CREATE OR REPLACE FUNCTION public.log_call_outcome(
        p_plaintiff_id uuid,
        p_task_id uuid,
        p_outcome text,
        p_interest text,
        p_notes text,
        p_follow_up_at timestamptz
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_terminal boolean := p_outcome IN ('do_not_call', 'bad_number');
v_now timestamptz := timezone('utc', now());
v_status text;
v_attempt_id uuid;
v_follow_up_task_id uuid;
v_follow_up_created boolean := false;
BEGIN IF p_plaintiff_id IS NULL THEN RAISE EXCEPTION 'plaintiff_id is required' USING ERRCODE = '23502';
END IF;
IF p_task_id IS NULL THEN RAISE EXCEPTION 'task_id is required' USING ERRCODE = '23502';
END IF;
IF p_outcome IS NULL
OR btrim(p_outcome) = '' THEN RAISE EXCEPTION 'outcome is required' USING ERRCODE = '23502';
END IF;
IF p_outcome = 'do_not_call' THEN v_status := 'do_not_call';
ELSIF p_outcome = 'bad_number' THEN v_status := 'bad_number';
ELSIF p_outcome = 'reached'
AND p_interest = 'hot' THEN v_status := 'reached_hot';
ELSIF p_outcome = 'reached'
AND p_interest = 'warm' THEN v_status := 'reached_warm';
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
        p_plaintiff_id,
        p_task_id,
        p_outcome,
        NULLIF(btrim(COALESCE(p_interest, '')), ''),
        p_notes,
        CASE
            WHEN NOT v_terminal THEN p_follow_up_at
            ELSE NULL
        END,
        v_now,
        jsonb_build_object(
            'from_rpc',
            'log_call_outcome',
            'follow_up_at',
            CASE
                WHEN NOT v_terminal THEN p_follow_up_at
                ELSE NULL
            END
        )
    )
RETURNING id INTO v_attempt_id;
UPDATE public.plaintiff_tasks t
SET status = 'closed',
    completed_at = v_now,
    closed_at = COALESCE(t.closed_at, v_now),
    result = COALESCE(t.result, p_outcome),
    metadata = COALESCE(t.metadata, '{}'::jsonb) || jsonb_build_object(
        'result',
        p_outcome,
        'interest_level',
        p_interest,
        'closed_by',
        'log_call_outcome',
        'closed_at',
        v_now
    )
WHERE t.id = p_task_id;
INSERT INTO public.plaintiff_status_history (
        plaintiff_id,
        status,
        note,
        changed_at,
        changed_by
    )
VALUES (
        p_plaintiff_id,
        v_status,
        COALESCE(
            p_notes,
            format('Call outcome recorded: %s', p_outcome)
        ),
        v_now,
        'log_call_outcome'
    );
IF NOT v_terminal
AND p_follow_up_at IS NOT NULL THEN
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
        p_plaintiff_id,
        'call',
        'open',
        p_follow_up_at,
        COALESCE(p_notes, 'Follow-up call'),
        'log_call_outcome',
        jsonb_build_object(
            'from_outcome',
            p_outcome,
            'interest_level',
            p_interest,
            'previous_task_id',
            p_task_id
        )
    )
RETURNING id INTO v_follow_up_task_id;
v_follow_up_created := true;
END IF;
RETURN jsonb_build_object(
    'plaintiff_id',
    p_plaintiff_id,
    'task_id',
    p_task_id,
    'outcome',
    p_outcome,
    'interest',
    p_interest,
    'status',
    v_status,
    'follow_up_created',
    v_follow_up_created,
    'follow_up_at',
    p_follow_up_at,
    'call_attempt_id',
    v_attempt_id,
    'created_follow_up_task_id',
    v_follow_up_task_id
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO authenticated;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO service_role;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO anon;
COMMIT;