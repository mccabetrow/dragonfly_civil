-- 0079_plaintiff_status_rpc.sql
-- Canonical RPC for changing plaintiff status with history and task automation.

-- migrate:up

create or replace function public.set_plaintiff_status(
    _plaintiff_id uuid,
    _new_status text,
    _note text default NULL,
    _changed_by text default NULL
)
returns public.plaintiffs
language plpgsql
security definer
as $$
DECLARE
    _valid_statuses constant text[] := ARRAY[
        'new',
        'contacted',
        'qualified',
        'sent_agreement',
        'signed',
        'lost'
    ];
    _old_status text;
    _p public.plaintiffs;
BEGIN
    IF _new_status IS NULL OR btrim(lower(_new_status)) NOT IN (SELECT UNNEST(_valid_statuses)) THEN
        RAISE EXCEPTION 'Invalid plaintiff status: %', _new_status
            USING ERRCODE = '22023';
    END IF;

    SELECT *
    INTO _p
    FROM public.plaintiffs
    WHERE id = _plaintiff_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Plaintiff % not found', _plaintiff_id
            USING ERRCODE = 'P0002';
    END IF;

    _old_status := _p.status;

    IF _old_status = _new_status THEN
        RETURN _p;
    END IF;

    UPDATE public.plaintiffs
    SET status = _new_status,
        updated_at = now()
    WHERE id = _plaintiff_id
    RETURNING *
    INTO _p;

    INSERT INTO public.plaintiff_status_history (plaintiff_id, status, note, changed_at, changed_by)
    VALUES (_plaintiff_id, _new_status, _note, now(), _changed_by);

    IF _old_status = 'new' AND _new_status = 'contacted' THEN
        PERFORM 1
        FROM public.plaintiff_tasks t
        WHERE t.plaintiff_id = _plaintiff_id
          AND t.kind = 'call'
          AND t.status IN ('open', 'in_progress')
        LIMIT 1;

        IF NOT FOUND THEN
            INSERT INTO public.plaintiff_tasks (plaintiff_id, kind, status, due_at, note, created_by)
            VALUES (_plaintiff_id, 'call', 'open', now(), COALESCE(_note, 'Initial outreach call'), _changed_by);
        END IF;
    ELSIF _old_status = 'qualified' AND _new_status = 'sent_agreement' THEN
        PERFORM 1
        FROM public.plaintiff_tasks t
        WHERE t.plaintiff_id = _plaintiff_id
          AND t.kind = 'agreement'
          AND t.status IN ('open', 'in_progress')
        LIMIT 1;

        IF NOT FOUND THEN
            INSERT INTO public.plaintiff_tasks (plaintiff_id, kind, status, due_at, note, created_by)
            VALUES (_plaintiff_id, 'agreement', 'open', now(), COALESCE(_note, 'Send plaintiff agreement'), _changed_by);
        END IF;
    END IF;

    RETURN _p;
END;
$$;

grant execute on function public.set_plaintiff_status(
    uuid, text, text, text
) to anon,
authenticated;

-- migrate:down

revoke execute on function public.set_plaintiff_status(
    uuid, text, text, text
) from anon,
authenticated;
drop function if exists public.set_plaintiff_status(uuid, text, text, text);

-- Use public.set_plaintiff_status to mutate plaintiffs.status consistently with history + tasks.
