-- 0083_complete_plaintiff_call_task.sql
-- Allow operators to record call outcomes and optional follow-up tasks via RPC.
-- migrate:up
create or replace function public.complete_plaintiff_call_task(
    _task_id uuid,
    _new_status text,
    _notes text default NULL,
    _next_follow_up_at timestamptz default NULL
) returns void language plpgsql security definer
set search_path = public,
pg_temp as $$
DECLARE _normalized_status text;
_task public.plaintiff_tasks %ROWTYPE;
_status_history text;
_changed_by text := COALESCE(
    current_setting('app.current_user', true),
    'complete_plaintiff_call_task'
);
BEGIN IF _new_status IS NULL THEN RAISE EXCEPTION 'new_status is required' USING ERRCODE = '22023';
END IF;
_normalized_status := lower(btrim(_new_status));
IF _normalized_status NOT IN ('completed', 'cannot_contact', 'do_not_pursue') THEN RAISE EXCEPTION 'Invalid call task status: %',
_new_status USING ERRCODE = '22023';
END IF;
SELECT * INTO _task
FROM public.plaintiff_tasks
WHERE id = _task_id FOR
UPDATE;
IF NOT FOUND THEN RAISE EXCEPTION 'Plaintiff task % not found',
_task_id USING ERRCODE = 'P0002';
END IF;
UPDATE public.plaintiff_tasks
SET status = _normalized_status,
    due_at = _next_follow_up_at,
    completed_at = now(),
    note = COALESCE(NULLIF(_notes, ''), note)
WHERE id = _task_id;
_status_history := CASE
    _normalized_status
    WHEN 'completed' THEN 'call_completed'
    WHEN 'cannot_contact' THEN 'call_cannot_contact'
    ELSE 'call_do_not_pursue'
END;
INSERT INTO public.plaintiff_status_history (plaintiff_id, status, note, changed_by)
VALUES (
        _task.plaintiff_id,
        _status_history,
        COALESCE(
            _notes,
            format('Call task marked %s', _normalized_status)
        ),
        _changed_by
    );
IF _next_follow_up_at IS NOT NULL THEN
INSERT INTO public.plaintiff_tasks (
        plaintiff_id,
        kind,
        status,
        due_at,
        note,
        created_by
    )
VALUES (
        _task.plaintiff_id,
        _task.kind,
        'open',
        _next_follow_up_at,
        COALESCE(
            _notes,
            'Follow-up call scheduled from outcome RPC'
        ),
        _changed_by
    );
END IF;
END;
$$;
revoke all on function public.complete_plaintiff_call_task(
    uuid, text, text, timestamptz
)
from public;
grant execute on function public.complete_plaintiff_call_task(
    uuid, text, text, timestamptz
) to service_role;
-- migrate:down
revoke execute on function public.complete_plaintiff_call_task(
    uuid, text, text, timestamptz
)
from service_role;
drop function if exists public.complete_plaintiff_call_task(
    uuid, text, text, timestamptz
);
