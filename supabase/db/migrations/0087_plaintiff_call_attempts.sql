-- 0087_plaintiff_call_attempts.sql
-- Introduce detailed call-attempt logging plus the log_call_outcome RPC consumed by the dashboard.
-- migrate:up
begin;
create table if not exists public.plaintiff_call_attempts (
    id uuid primary key default gen_random_uuid(),
    plaintiff_id uuid not null references public.plaintiffs (
        id
    ) on delete cascade,
    task_id uuid references public.plaintiff_tasks (id) on delete
    set null,
    attempted_at timestamptz not null default timezone('utc', now()),
    outcome text not null,
    interest_level text,
    notes text,
    next_follow_up_at timestamptz,
    created_by text not null default 'call_queue',
    metadata jsonb not null default '{}'::jsonb,
    constraint plaintiff_call_attempts_outcome_check check (
        outcome in (
            'reached',
            'voicemail',
            'no_answer',
            'bad_number',
            'do_not_call'
        )
    )
);
create index if not exists idx_plaintiff_call_attempts_plaintiff_id on public.plaintiff_call_attempts (
    plaintiff_id, attempted_at desc
);
create or replace function public.log_call_outcome(
    _plaintiff_id uuid,
    _task_id uuid,
    _outcome text,
    _interest_level text default NULL,
    _notes text default NULL,
    _next_follow_up_at timestamptz default NULL
) returns table (
    call_attempt_id uuid,
    updated_task_id uuid,
    created_follow_up_task_id uuid
) language plpgsql security definer
set search_path = public,
pg_temp as $$
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
        jsonb_build_object('source', 'log_call_outcome')
    )
RETURNING id INTO _attempt_id;
IF _task_id IS NOT NULL THEN
UPDATE public.plaintiff_tasks
SET status = 'closed',
    completed_at = _now,
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
grant execute on function public.log_call_outcome(
    uuid, uuid, text, text, text, timestamptz
) to anon,
authenticated,
service_role;
commit;
-- migrate:down
begin;
revoke execute on function public.log_call_outcome(
    uuid, uuid, text, text, text, timestamptz
)
from anon,
authenticated,
service_role;
drop function if exists public.log_call_outcome(
    uuid, uuid, text, text, text, timestamptz
) cascade;
drop index if exists idx_plaintiff_call_attempts_plaintiff_id;
drop table if exists public.plaintiff_call_attempts;
commit;
