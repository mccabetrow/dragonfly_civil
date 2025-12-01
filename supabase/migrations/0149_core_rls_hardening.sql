-- 0149_core_rls_hardening.sql
-- Force RLS + restrict write grants on core enforcement/plaintiff tables per security audit.
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
EXECUTE format(
    'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC;',
    target
);
EXECUTE format(
    'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM anon;',
    target
);
EXECUTE format(
    'REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM authenticated;',
    target
);
EXECUTE format(
    'GRANT INSERT, UPDATE, DELETE, TRUNCATE ON public.%I TO service_role;',
    target
);
END LOOP;
END $$;
SELECT public.pgrst_reload();
COMMIT;
