-- Ensure pipeline views are read-only for anon/auth and hidden from public.
DO $$
DECLARE pipeline_views text [] := ARRAY [
        'v_plaintiffs_overview',
        'v_judgment_pipeline',
        'v_enforcement_overview',
        'v_enforcement_recent',
        'v_plaintiff_call_queue'
    ];
rel text;
BEGIN FOREACH rel IN ARRAY pipeline_views LOOP IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relkind = 'v'
        AND c.relname = rel
) THEN EXECUTE format(
    'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM anon, authenticated, public',
    rel
);
EXECUTE format(
    'GRANT SELECT ON TABLE public.%I TO anon, authenticated',
    rel
);
END IF;
END LOOP;
END $$;
-- Remove the legacy read access from v_collectability_snapshot entirely.
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_class c
        JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
        AND c.relkind = 'v'
        AND c.relname = 'v_collectability_snapshot'
) THEN EXECUTE 'REVOKE ALL PRIVILEGES ON TABLE public.v_collectability_snapshot FROM anon, authenticated, public';
EXECUTE 'GRANT SELECT ON TABLE public.v_collectability_snapshot TO service_role';
END IF;
END $$;
