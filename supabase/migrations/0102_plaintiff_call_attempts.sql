-- 0102_plaintiff_call_attempts.sql
-- Purpose: add granular call-attempt tracking plus the log_call_outcome RPC used by the dashboard call queue.
-- migrate:up
BEGIN;
CREATE TABLE IF NOT EXISTS public.plaintiff_call_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs(id) ON DELETE CASCADE,
    task_id uuid REFERENCES public.plaintiff_tasks(id) ON DELETE
    SET NULL,
        attempted_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
        outcome text NOT NULL,
        interest_level text,
        notes text,
        next_follow_up_at timestamptz,
        created_by text NOT NULL DEFAULT 'call_queue',
        metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
        CONSTRAINT plaintiff_call_attempts_outcome_check CHECK (
            outcome IN (
                'reached',
                'voicemail',
                'no_answer',
                'bad_number',
                'do_not_call'
            )
        )
);
CREATE INDEX IF NOT EXISTS idx_plaintiff_call_attempts_plaintiff_id ON public.plaintiff_call_attempts (plaintiff_id, attempted_at DESC);
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS closed_at timestamptz,
    ADD COLUMN IF NOT EXISTS result text;
DROP FUNCTION IF EXISTS public.log_call_outcome(uuid, uuid, text, text, text, timestamptz);
CREATE OR REPLACE FUNCTION public.log_call_outcome(
        _plaintiff_id uuid,
        _task_id uuid,
        _outcome text,
        _interest_level text DEFAULT NULL,
        _notes text DEFAULT NULL,
        _next_follow_up_at timestamptz DEFAULT NULL
    ) RETURNS TABLE (
        call_attempt_id uuid,
        updated_task_id uuid,
        created_follow_up_task_id uuid
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _attempt_id uuid;
_closed_task_id uuid;
_follow_up_task_id uuid;
_normalized_outcome text;
_normalized_interest text;
_sanitized_notes text := NULLIF(btrim(COALESCE(_notes, '')), '');
_status_event text;
_now timestamptz := timezone('utc', now());
BEGIN IF _plaintiff_id IS NULL THEN RAISE EXCEPTION 'plaintiff_id is required' USING ERRCODE = '22023';
END IF;
IF _outcome IS NULL THEN RAISE EXCEPTION 'outcome is required' USING ERRCODE = '22023';
END IF;
_normalized_outcome := lower(btrim(_outcome));
IF _normalized_outcome NOT IN (
    'reached',
    'voicemail',
    'no_answer',
    'bad_number',
    'do_not_call'
) THEN RAISE EXCEPTION 'Invalid outcome: %',
_outcome USING ERRCODE = '22023';
END IF;
IF _interest_level IS NOT NULL THEN _normalized_interest := lower(btrim(_interest_level));
IF _normalized_interest NOT IN ('hot', 'warm', 'cold', 'none') THEN RAISE EXCEPTION 'Invalid interest level: %',
_interest_level USING ERRCODE = '22023';
END IF;
ELSE _normalized_interest := NULL;
END IF;
INSERT INTO public.plaintiff_call_attempts (
        plaintiff_id,
        task_id,
        outcome,
        interest_level,
        notes,
        next_follow_up_at,
        metadata
    )
VALUES (
        _plaintiff_id,
        _task_id,
        _normalized_outcome,
        _normalized_interest,
        _sanitized_notes,
        _next_follow_up_at,
        jsonb_build_object(
            'source',
            'log_call_outcome',
            'interest_level',
            COALESCE(_normalized_interest, 'none')
        )
    )
RETURNING id INTO _attempt_id;
IF _task_id IS NOT NULL THEN
UPDATE public.plaintiff_tasks
SET status = 'closed',
    closed_at = _now,
    completed_at = _now,
    result = _normalized_outcome,
    note = COALESCE(_sanitized_notes, note),
    metadata = COALESCE(metadata, '{}'::jsonb) || jsonb_build_object(
        'closed_by',
        'log_call_outcome',
        'closed_at',
        _now,
        'result',
        _normalized_outcome
    )
WHERE id = _task_id
RETURNING id INTO _closed_task_id;
END IF;
_status_event := CASE
    WHEN _normalized_outcome = 'do_not_call' THEN 'do_not_call'
    WHEN _normalized_outcome = 'bad_number' THEN 'bad_number'
    WHEN _normalized_outcome = 'reached'
    AND _normalized_interest = 'hot' THEN 'reached_hot'
    WHEN _normalized_outcome = 'reached'
    AND _normalized_interest = 'warm' THEN 'reached_warm'
    ELSE 'contacted'
END;
INSERT INTO public.plaintiff_status_history (
        plaintiff_id,
        status,
        note,
        changed_at,
        changed_by
    )
VALUES (
        _plaintiff_id,
        _status_event,
        COALESCE(
            _sanitized_notes,
            format('Call outcome recorded: %s', _normalized_outcome)
        ),
        _now,
        'call_queue'
    );
IF _next_follow_up_at IS NOT NULL
AND _normalized_outcome NOT IN ('do_not_call', 'bad_number') THEN
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
        _next_follow_up_at,
        COALESCE(_sanitized_notes, 'Follow-up call scheduled'),
        'call_queue_followup',
        jsonb_build_object(
            'from_outcome',
            _normalized_outcome,
            'interest_level',
            COALESCE(_normalized_interest, 'none')
        )
    )
RETURNING id INTO _follow_up_task_id;
END IF;
call_attempt_id := _attempt_id;
updated_task_id := _closed_task_id;
created_follow_up_task_id := _follow_up_task_id;
RETURN NEXT;
RETURN;
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
DROP INDEX IF EXISTS idx_plaintiff_call_attempts_plaintiff_id;
DROP TABLE IF EXISTS public.plaintiff_call_attempts;
ALTER TABLE public.plaintiff_tasks DROP COLUMN IF EXISTS result,
    DROP COLUMN IF EXISTS closed_at;
COMMIT;