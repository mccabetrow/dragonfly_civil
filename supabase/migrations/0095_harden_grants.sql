-- Harden Supabase grants to satisfy tools.security_audit expectations.
-- Restricted tables lose anon/auth/public access, non-pipeline views are private,
-- and pipeline views become read-only for anon/auth.
DO $$
DECLARE restricted_tables text [] := ARRAY [
        'import_runs',
        'enforcement_cases',
        'enforcement_events',
        'enforcement_evidence'
    ];
restricted_rel text;
BEGIN FOREACH restricted_rel IN ARRAY restricted_tables LOOP IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relname = restricted_rel
) THEN EXECUTE format(
    'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM anon, authenticated, public',
    restricted_rel
);
END IF;
END LOOP;
END $$;
DO $$
DECLARE pipeline_views text [] := ARRAY [
        'v_plaintiffs_overview',
        'v_judgment_pipeline',
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_plaintiff_call_queue'
    ];
view_name text;
BEGIN FOR view_name IN
SELECT c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = 'public'
    AND c.relkind = 'v'
    AND NOT (c.relname = ANY(pipeline_views)) LOOP EXECUTE format(
        'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM anon, authenticated, public',
        view_name
    );
END LOOP;
FOREACH view_name IN ARRAY pipeline_views LOOP IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relkind = 'v'
        AND c.relname = view_name
) THEN EXECUTE format(
    'GRANT SELECT ON TABLE public.%I TO anon, authenticated',
    view_name
);
END IF;
END LOOP;
END $$;
