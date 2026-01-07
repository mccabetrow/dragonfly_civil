-- Fix remaining insecure views in analytics and ops schemas
DO $$
DECLARE v_schema TEXT;
v_view TEXT;
v_full_name TEXT;
v_count INT := 0;
v_schemas TEXT [] := ARRAY ['analytics', 'ops'];
BEGIN FOREACH v_schema IN ARRAY v_schemas LOOP IF NOT EXISTS (
    SELECT 1
    FROM information_schema.schemata
    WHERE schema_name = v_schema
) THEN CONTINUE;
END IF;
FOR v_view IN
SELECT c.relname
FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = v_schema
    AND c.relkind = 'v'
ORDER BY c.relname LOOP v_full_name := format('%I.%I', v_schema, v_view);
BEGIN EXECUTE format(
    'ALTER VIEW %s SET (security_invoker = true)',
    v_full_name
);
v_count := v_count + 1;
RAISE NOTICE 'Fixed: %',
v_full_name;
EXCEPTION
WHEN OTHERS THEN RAISE WARNING 'Error on %: %',
v_full_name,
SQLERRM;
END;
END LOOP;
END LOOP;
RAISE NOTICE 'Total fixed: % views',
v_count;
END;
$$;