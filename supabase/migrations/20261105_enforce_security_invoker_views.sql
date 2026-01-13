-- 20261105_enforce_security_invoker_views.sql
-- Purpose: Ensure all views in sensitive schemas run with security_invoker=true
-- Safe to rerun: uses idempotent ALTER VIEW ... SET statements only when needed.
BEGIN;
DO $$
DECLARE target_schema TEXT;
target_view TEXT;
BEGIN FOR target_schema,
target_view IN
SELECT n.nspname,
    c.relname
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v'
    AND n.nspname = ANY (
        ARRAY [
                'public','intake','enforcement','legal','rag',
                'evidence','workers','ops','analytics','ingest'
          ]
    )
    AND (
        c.reloptions IS NULL
        OR NOT (
            c.reloptions::text [] @> ARRAY ['security_invoker=true']
        )
    )
ORDER BY n.nspname,
    c.relname LOOP EXECUTE format(
        'ALTER VIEW %I.%I SET (security_invoker = true)',
        target_schema,
        target_view
    );
RAISE NOTICE '✅ Applied security_invoker=true to %.%',
target_schema,
target_view;
END LOOP;
IF NOT FOUND THEN RAISE NOTICE '🎉 All target views already had security_invoker=true';
END IF;
END $$;
-- Force PostgREST to refresh schema cache so changes take effect immediately
NOTIFY pgrst,
'reload schema';
-- Verification: summary counts per schema
SELECT n.nspname AS schema_name,
    COUNT(*) FILTER (
        WHERE c.reloptions::text [] @> ARRAY ['security_invoker=true']
    ) AS secure_views,
    COUNT(*) FILTER (
        WHERE c.reloptions IS NULL
            OR NOT (
                c.reloptions::text [] @> ARRAY ['security_invoker=true']
            )
    ) AS insecure_views,
    COUNT(*) AS total_views
FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE c.relkind = 'v'
    AND n.nspname = ANY (
        ARRAY [
        'public','intake','enforcement','legal','rag',
        'evidence','workers','ops','analytics','ingest'
  ]
    )
GROUP BY n.nspname
ORDER BY n.nspname;
COMMIT;