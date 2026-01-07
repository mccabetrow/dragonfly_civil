-- ═══════════════════════════════════════════════════════════════════════════
-- HARDEN VIEW GRANTS: Zero Trust / RPC-Only Architecture
-- ═══════════════════════════════════════════════════════════════════════════
--
-- PURPOSE: Revoke ALL permissions on all views in public, intake, and ops
--          schemas from anon, authenticated, and public roles.
--
-- POLICY:  No direct view access is allowed. All UI must use SECURITY DEFINER
--          RPCs to access data. This drastically reduces the attack surface.
--
-- IMPORTANT: service_role and postgres retain full access.
--
-- ═══════════════════════════════════════════════════════════════════════════
DO $$
DECLARE _schema TEXT;
_view TEXT;
_sql TEXT;
_count INTEGER := 0;
BEGIN RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE 'HARDEN VIEW GRANTS: Revoking public access to all views';
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
-- Iterate through all views in target schemas
FOR _schema,
_view IN
SELECT table_schema,
    table_name
FROM information_schema.views
WHERE table_schema IN ('public', 'intake', 'ops')
ORDER BY table_schema,
    table_name LOOP -- Revoke ALL permissions from anon, authenticated, and public roles
    _sql := format(
        'REVOKE ALL ON TABLE %I.%I FROM anon, authenticated, public',
        _schema,
        _view
    );
BEGIN EXECUTE _sql;
RAISE NOTICE '[OK] Revoked permissions on %.%',
_schema,
_view;
_count := _count + 1;
EXCEPTION
WHEN OTHERS THEN RAISE WARNING '[WARN] Failed to revoke on %.%: %',
_schema,
_view,
SQLERRM;
END;
END LOOP;
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
RAISE NOTICE 'COMPLETE: Hardened % views',
_count;
RAISE NOTICE '═══════════════════════════════════════════════════════════════════';
END $$;
-- ═══════════════════════════════════════════════════════════════════════════
-- VERIFICATION QUERY
-- ═══════════════════════════════════════════════════════════════════════════
-- Run this after migration to verify no anon/authenticated/public grants remain:
--
-- SELECT
--     table_schema,
--     table_name,
--     grantee,
--     privilege_type
-- FROM information_schema.table_privileges tp
-- JOIN information_schema.views v
--     ON v.table_schema = tp.table_schema
--     AND v.table_name = tp.table_name
-- WHERE tp.table_schema IN ('public', 'intake', 'ops')
--   AND tp.grantee IN ('anon', 'authenticated', 'public')
-- ORDER BY table_schema, table_name, grantee;
--
-- Expected result: 0 rows (all view grants revoked)
-- ═══════════════════════════════════════════════════════════════════════════
