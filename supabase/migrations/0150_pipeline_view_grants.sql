-- 0150_pipeline_view_grants.sql
-- Restrict pipeline dashboard views to read-only access for anon/authenticated roles.
BEGIN;
DO $$
DECLARE target text;
views text [] := ARRAY [
        'v_case_copilot_latest',
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_enforcement_timeline',
        'v_ops_daily_summary',
        'v_plaintiff_call_queue',
        'v_plaintiff_open_tasks',
        'v_plaintiffs_overview',
        'v_judgment_pipeline'
    ];
BEGIN FOREACH target IN ARRAY views LOOP EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC;', target);
EXECUTE format('REVOKE ALL ON public.%I FROM anon;', target);
EXECUTE format(
    'REVOKE ALL ON public.%I FROM authenticated;',
    target
);
EXECUTE format('GRANT SELECT ON public.%I TO anon;', target);
EXECUTE format(
    'GRANT SELECT ON public.%I TO authenticated;',
    target
);
EXECUTE format(
    'GRANT SELECT ON public.%I TO service_role;',
    target
);
END LOOP;
END $$;
SELECT public.pgrst_reload();
COMMIT;

