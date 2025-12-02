-- 0084_jbi_900_intake.sql
-- Track plaintiff source_system and expose aggregated stats for the JBI 900 upload.
-- migrate:up
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS source_system text;
UPDATE public.plaintiffs
SET source_system = 'unknown'
WHERE
    source_system IS NULL
    OR btrim(source_system) = '';
DO $$ BEGIN
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET DEFAULT 'unknown';
EXCEPTION
WHEN undefined_column THEN -- Column was just added above for older environments.
NULL;
END $$;
UPDATE public.plaintiffs p
SET source_system = 'simplicity'
WHERE
    coalesce(p.source_system, 'unknown') = 'unknown'
    AND EXISTS (
        SELECT 1
        FROM public.plaintiff_status_history AS h
        WHERE
            h.plaintiff_id = p.id
            AND h.changed_by = 'simplicity_import'
    );
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET NOT NULL;
CREATE OR REPLACE VIEW public.v_plaintiffs_jbi_900 AS
SELECT
    p.status,
    count(*)::bigint AS plaintiff_count,
    coalesce(
        sum(ov.total_judgment_amount), 0
    )::numeric AS total_judgment_amount,
    CASE
    btrim(lower(p.status))
        WHEN 'new' THEN 1
        WHEN 'contacted' THEN 2
        WHEN 'qualified' THEN 3
        WHEN 'sent_agreement' THEN 4
        WHEN 'signed' THEN 5
        WHEN 'lost' THEN 6
        ELSE 99
    END AS status_priority
FROM public.plaintiffs AS p
LEFT JOIN public.v_plaintiffs_overview AS ov ON p.id = ov.plaintiff_id
WHERE p.source_system = 'jbi_900'
GROUP BY p.status;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO anon,
authenticated,
service_role;
-- migrate:down
REVOKE
SELECT ON public.v_plaintiffs_jbi_900
FROM anon,
authenticated,
service_role;
DROP VIEW IF EXISTS public.v_plaintiffs_jbi_900;
ALTER TABLE public.plaintiffs DROP COLUMN IF EXISTS source_system;
-- Adds a source tag for plaintiffs and exposes a JBI-specific summary view for dashboards.
