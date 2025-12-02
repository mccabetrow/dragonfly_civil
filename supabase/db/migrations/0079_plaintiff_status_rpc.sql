-- 0079_plaintiff_status_rpc.sql
-- Canonical RPC for changing plaintiff status with history and task automation.

-- migrate:up

CREATE OR REPLACE FUNCTION public.set_plaintiff_status(
    _plaintiff_id uuid,
    _new_status text,
    _note text DEFAULT NULL,
    _changed_by text DEFAULT NULL
)
RETURNS public.plaintiffs
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
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

GRANT EXECUTE ON FUNCTION public.set_plaintiff_status(
    uuid, text, text, text
) TO anon,
authenticated;

-- migrate:down

REVOKE EXECUTE ON FUNCTION public.set_plaintiff_status(
    uuid, text, text, text
) FROM anon,
authenticated;
DROP FUNCTION IF EXISTS public.set_plaintiff_status (uuid, text, text, text);

-- Use public.set_plaintiff_status to mutate plaintiffs.status consistently with history + tasks.
