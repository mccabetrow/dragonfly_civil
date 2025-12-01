-- 0151_table_security_lockdown.sql
-- Enforce RLS + forced RLS and restrict grants on core plaintiff/enforcement tables per security audit.
BEGIN;
DO $$
DECLARE target text;
tables text [] := ARRAY [
        'judgments',
        'plaintiffs',
        'enforcement_cases',
        'enforcement_timeline',
        'enforcement_evidence',
        'plaintiff_tasks',
        'plaintiff_call_attempts'
    ];
BEGIN FOREACH target IN ARRAY tables LOOP EXECUTE format(
    'ALTER TABLE IF EXISTS public.%I ENABLE ROW LEVEL SECURITY;',
    target
);
EXECUTE format(
    'ALTER TABLE IF EXISTS public.%I FORCE ROW LEVEL SECURITY;',
    target
);
EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC;', target);
EXECUTE format('REVOKE ALL ON public.%I FROM anon;', target);
EXECUTE format(
    'REVOKE ALL ON public.%I FROM authenticated;',
    target
);
EXECUTE format(
    'GRANT ALL ON public.%I TO service_role;',
    target
);
END LOOP;
END $$;
SELECT public.pgrst_reload();
COMMIT;
