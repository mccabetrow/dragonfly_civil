-- 0080_plaintiff_funnel_stats.sql
-- Adds an aggregated funnel view for plaintiffs by status.

-- migrate:up

CREATE OR REPLACE VIEW public.v_plaintiff_funnel_stats AS
SELECT
    COUNT(*)::bigint AS plaintiff_count,
    COALESCE(SUM(o.total_judgment_amount), 0)::numeric AS total_judgment_amount,
    COALESCE(p.status, 'unknown') AS status
FROM public.plaintiffs AS p
LEFT JOIN public.v_plaintiffs_overview AS o
    ON p.id = o.plaintiff_id
GROUP BY COALESCE(p.status, 'unknown')
ORDER BY status;

GRANT SELECT ON public.v_plaintiff_funnel_stats TO anon,
authenticated,
service_role;

-- migrate:down

REVOKE SELECT ON public.v_plaintiff_funnel_stats FROM anon,
authenticated,
service_role;
DROP VIEW IF EXISTS public.v_plaintiff_funnel_stats;

-- Purpose: summarize plaintiff funnel volume and value for dashboards.
