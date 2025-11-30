-- 0141_log_call_outcome.sql
-- Simplify call logging RPC and expose richer data for the call queue.
BEGIN;
-- Ensure plaintiff_call_attempts has the required columns
CREATE TABLE IF NOT EXISTS public.plaintiff_call_attempts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs(id) ON DELETE CASCADE,
    outcome text,
    interest_level text,
    notes text,
    attempted_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    assignee text,
    next_follow_up_at timestamptz
);
ALTER TABLE public.plaintiff_call_attempts
ADD COLUMN IF NOT EXISTS assignee text;
ALTER TABLE public.plaintiff_call_attempts
ALTER COLUMN attempted_at
SET DEFAULT timezone('utc', now());
CREATE INDEX IF NOT EXISTS idx_plaintiff_call_attempts_plaintiff_id_attempted_at ON public.plaintiff_call_attempts (plaintiff_id, attempted_at DESC);
-- Replace legacy log_call_outcome RPC with simplified signature
DROP FUNCTION IF EXISTS public.log_call_outcome(uuid, uuid, text, text, text, timestamptz);
DROP FUNCTION IF EXISTS public.log_call_outcome(uuid, text, text, text, timestamptz, text);
CREATE OR REPLACE FUNCTION public.log_call_outcome(
        p_plaintiff_id uuid,
        p_outcome text,
        p_interest_level text DEFAULT NULL,
        p_notes text DEFAULT NULL,
        p_next_follow_up_at timestamptz DEFAULT NULL,
        p_assignee text DEFAULT NULL
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE v_id uuid;
BEGIN IF p_plaintiff_id IS NULL THEN RAISE EXCEPTION 'plaintiff_id is required' USING ERRCODE = '23502';
END IF;
IF p_outcome IS NULL
OR btrim(p_outcome) = '' THEN RAISE EXCEPTION 'outcome is required' USING ERRCODE = '23502';
END IF;
INSERT INTO public.plaintiff_call_attempts (
        plaintiff_id,
        outcome,
        interest_level,
        notes,
        attempted_at,
        assignee,
        next_follow_up_at
    )
VALUES (
        p_plaintiff_id,
        NULLIF(btrim(COALESCE(p_outcome, '')), ''),
        NULLIF(btrim(COALESCE(p_interest_level, '')), ''),
        NULLIF(btrim(COALESCE(p_notes, '')), ''),
        timezone('utc', now()),
        NULLIF(btrim(COALESCE(p_assignee, '')), ''),
        p_next_follow_up_at
    )
RETURNING id INTO v_id;
RETURN v_id;
END;
$$;
REVOKE ALL ON FUNCTION public.log_call_outcome(uuid, text, text, text, timestamptz, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, text, text, text, timestamptz, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, text, text, text, timestamptz, text) TO service_role;
-- Refresh call queue view with richer context
DROP VIEW IF EXISTS public.v_plaintiff_call_queue;
CREATE OR REPLACE VIEW public.v_plaintiff_call_queue AS WITH ranked_call_tasks AS (
        SELECT ot.*,
            row_number() OVER (
                PARTITION BY ot.plaintiff_id
                ORDER BY ot.due_at NULLS LAST,
                    ot.created_at ASC
            ) AS task_rank
        FROM public.v_plaintiff_open_tasks ot
        WHERE ot.kind = 'call'
            AND ot.status IN ('open', 'in_progress')
    )
SELECT r.task_id,
    r.plaintiff_id,
    r.plaintiff_name,
    r.firm_name,
    r.plaintiff_status AS status,
    r.status AS task_status,
    r.top_collectability_tier AS tier,
    r.judgment_total AS total_judgment_amount,
    r.case_count,
    r.phone,
    contact_info.last_contact_at AS last_contact_at,
    contact_info.last_contact_at AS last_contacted_at,
    CASE
        WHEN contact_info.last_contact_at IS NULL THEN NULL
        ELSE GREATEST(
            DATE_PART(
                'day',
                timezone('utc', now()) - contact_info.last_contact_at
            )::int,
            0
        )
    END AS days_since_contact,
    contact_info.last_call_outcome,
    contact_info.last_call_attempted_at,
    contact_info.last_call_interest_level,
    contact_info.last_call_notes,
    r.due_at,
    r.note AS notes,
    r.created_at
FROM ranked_call_tasks r
    LEFT JOIN LATERAL (
        WITH status_info AS (
            SELECT MAX(psh.changed_at) AS last_contacted_at
            FROM public.plaintiff_status_history psh
            WHERE psh.plaintiff_id = r.plaintiff_id
                AND psh.status IN (
                    'contacted',
                    'qualified',
                    'sent_agreement',
                    'signed'
                )
        ),
        attempt_info AS (
            SELECT pca.outcome,
                pca.interest_level,
                pca.notes,
                pca.attempted_at
            FROM public.plaintiff_call_attempts pca
            WHERE pca.plaintiff_id = r.plaintiff_id
            ORDER BY pca.attempted_at DESC
            LIMIT 1
        )
        SELECT CASE
                WHEN status_info.last_contacted_at IS NULL
                AND attempt_info.attempted_at IS NULL THEN NULL
                ELSE GREATEST(
                    COALESCE(
                        status_info.last_contacted_at,
                        '-infinity'::timestamptz
                    ),
                    COALESCE(
                        attempt_info.attempted_at,
                        '-infinity'::timestamptz
                    )
                )
            END AS last_contact_at,
            attempt_info.outcome AS last_call_outcome,
            attempt_info.interest_level AS last_call_interest_level,
            attempt_info.notes AS last_call_notes,
            attempt_info.attempted_at AS last_call_attempted_at
        FROM status_info
            LEFT JOIN attempt_info ON TRUE
    ) contact_info ON TRUE
WHERE r.task_rank = 1
ORDER BY r.due_at NULLS LAST,
    contact_info.last_contact_at NULLS FIRST,
    r.plaintiff_name;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
    authenticated,
    service_role;
COMMIT;