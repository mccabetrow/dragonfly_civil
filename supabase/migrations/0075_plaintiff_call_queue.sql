-- 0075_plaintiff_call_queue.sql
-- Purpose: expose a prioritized plaintiff call queue for the dashboard.

-- migrate:up

CREATE OR REPLACE VIEW public.v_plaintiff_call_queue AS
SELECT
    p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    status_info.last_contacted_at,
    p.created_at,
    COALESCE(ov.total_judgment_amount, 0::numeric) AS total_judgment_amount,
    COALESCE(ov.case_count, 0) AS case_count
FROM public.plaintiffs AS p
LEFT JOIN public.v_plaintiffs_overview AS ov
    ON p.id = ov.plaintiff_id
LEFT JOIN LATERAL (
    SELECT MAX(psh.changed_at) AS last_contacted_at
    FROM public.plaintiff_status_history AS psh
    WHERE
        psh.plaintiff_id = p.id
        AND psh.status IN ('contacted', 'qualified', 'sent_agreement', 'signed')
) AS status_info ON TRUE
WHERE p.status IN ('new', 'contacted', 'qualified')
ORDER BY
    COALESCE(ov.total_judgment_amount, 0::numeric) DESC,
    COALESCE(status_info.last_contacted_at, p.created_at) ASC;

GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
authenticated,
service_role;

-- migrate:down

REVOKE SELECT ON public.v_plaintiff_call_queue FROM anon,
authenticated,
service_role;
DROP VIEW IF EXISTS public.v_plaintiff_call_queue;

-- Powers the “call queue” panel in the dashboard to target the next plaintiffs to contact.
