-- =============================================================================
-- 0300_rls_role_mapping.sql
-- Dragonfly Civil – Enterprise-Grade Role-Based Access Control (RBAC)
-- =============================================================================
-- ROLES:
--   admin        : full access to everything
--   ops          : UPDATE operational fields (status, notes, follow_up) - no DELETE
--   ceo          : SELECT all financial/case data - cannot modify operational fields
--   enrichment_bot: UPDATE enrichment columns only
--   outreach_bot  : UPDATE call outcome columns only
--
-- GLOBAL RULE: No table allows ANY operation unless auth.uid() matches a role mapping.
-- =============================================================================
BEGIN;
-- =============================================================================
-- STEP 1: Create role mapping table
-- =============================================================================
-- Maps authenticated users (auth.uid()) to application roles.
-- The service_role is always allowed; this table controls human/bot access.
CREATE TABLE IF NOT EXISTS public.dragonfly_role_mappings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL,
    -- auth.uid() of the user
    role text NOT NULL CHECK (
        role IN (
            'admin',
            'ops',
            'ceo',
            'enrichment_bot',
            'outreach_bot'
        )
    ),
    granted_by text,
    -- who granted this role
    granted_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    expires_at timestamptz,
    -- optional expiration
    is_active boolean NOT NULL DEFAULT true,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    UNIQUE (user_id, role)
);
CREATE INDEX IF NOT EXISTS dragonfly_role_mappings_user_idx ON public.dragonfly_role_mappings (user_id)
WHERE is_active = true;
CREATE INDEX IF NOT EXISTS dragonfly_role_mappings_role_idx ON public.dragonfly_role_mappings (role)
WHERE is_active = true;
-- RLS on the mapping table itself (only admins can modify, service_role always allowed)
ALTER TABLE public.dragonfly_role_mappings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dragonfly_role_mappings FORCE ROW LEVEL SECURITY;
-- =============================================================================
-- STEP 2: Helper functions for role checks
-- =============================================================================
-- Check if the current user has a specific role (or is service_role/admin)
CREATE OR REPLACE FUNCTION public.dragonfly_has_role(required_role text) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT -- service_role always passes
    auth.role() = 'service_role'
    OR -- Check if user has the required role or is admin
    EXISTS (
        SELECT 1
        FROM public.dragonfly_role_mappings rm
        WHERE rm.user_id = auth.uid()
            AND rm.is_active = true
            AND (
                rm.expires_at IS NULL
                OR rm.expires_at > timezone('utc', now())
            )
            AND (
                rm.role = required_role
                OR rm.role = 'admin'
            )
    );
$$;
-- Check if user has ANY of the specified roles
CREATE OR REPLACE FUNCTION public.dragonfly_has_any_role(required_roles text []) RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT auth.role() = 'service_role'
    OR EXISTS (
        SELECT 1
        FROM public.dragonfly_role_mappings rm
        WHERE rm.user_id = auth.uid()
            AND rm.is_active = true
            AND (
                rm.expires_at IS NULL
                OR rm.expires_at > timezone('utc', now())
            )
            AND (
                rm.role = ANY(required_roles)
                OR rm.role = 'admin'
            )
    );
$$;
-- Check if current user is admin
CREATE OR REPLACE FUNCTION public.dragonfly_is_admin() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT auth.role() = 'service_role'
    OR EXISTS (
        SELECT 1
        FROM public.dragonfly_role_mappings rm
        WHERE rm.user_id = auth.uid()
            AND rm.is_active = true
            AND (
                rm.expires_at IS NULL
                OR rm.expires_at > timezone('utc', now())
            )
            AND rm.role = 'admin'
    );
$$;
-- Check if user can read (admin, ops, ceo, or service_role)
CREATE OR REPLACE FUNCTION public.dragonfly_can_read() RETURNS boolean LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
SELECT public.dragonfly_has_any_role(
        ARRAY ['admin', 'ops', 'ceo', 'enrichment_bot', 'outreach_bot']
    );
$$;
-- =============================================================================
-- STEP 3: Policies for role_mappings table itself
-- =============================================================================
DROP POLICY IF EXISTS role_mappings_admin_all ON public.dragonfly_role_mappings;
DROP POLICY IF EXISTS role_mappings_service_all ON public.dragonfly_role_mappings;
DROP POLICY IF EXISTS role_mappings_read_own ON public.dragonfly_role_mappings;
-- Service role can do everything
CREATE POLICY role_mappings_service_all ON public.dragonfly_role_mappings FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
-- Admins can manage all role mappings
CREATE POLICY role_mappings_admin_all ON public.dragonfly_role_mappings FOR ALL USING (public.dragonfly_is_admin()) WITH CHECK (public.dragonfly_is_admin());
-- Users can read their own role mappings
CREATE POLICY role_mappings_read_own ON public.dragonfly_role_mappings FOR
SELECT USING (user_id = auth.uid());
REVOKE ALL ON public.dragonfly_role_mappings
FROM public;
REVOKE ALL ON public.dragonfly_role_mappings
FROM anon;
GRANT SELECT ON public.dragonfly_role_mappings TO authenticated;
GRANT ALL ON public.dragonfly_role_mappings TO service_role;
-- Grant execute on helper functions
GRANT EXECUTE ON FUNCTION public.dragonfly_has_role(text) TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION public.dragonfly_has_any_role(text []) TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION public.dragonfly_is_admin() TO authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION public.dragonfly_can_read() TO authenticated,
    service_role;
-- =============================================================================
-- STEP 4: Audit log for role changes
-- =============================================================================
CREATE TABLE IF NOT EXISTS public.dragonfly_role_audit_log (
    id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    action text NOT NULL CHECK (
        action IN ('grant', 'revoke', 'expire', 'modify')
    ),
    target_user_id uuid NOT NULL,
    role text NOT NULL,
    performed_by uuid,
    performed_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    details jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS dragonfly_role_audit_target_idx ON public.dragonfly_role_audit_log (target_user_id, performed_at DESC);
ALTER TABLE public.dragonfly_role_audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.dragonfly_role_audit_log FORCE ROW LEVEL SECURITY;
-- Audit log is append-only for service_role, read-only for admins
DROP POLICY IF EXISTS role_audit_service_insert ON public.dragonfly_role_audit_log;
DROP POLICY IF EXISTS role_audit_admin_read ON public.dragonfly_role_audit_log;
CREATE POLICY role_audit_service_insert ON public.dragonfly_role_audit_log FOR
INSERT WITH CHECK (auth.role() = 'service_role');
CREATE POLICY role_audit_admin_read ON public.dragonfly_role_audit_log FOR
SELECT USING (public.dragonfly_is_admin());
REVOKE ALL ON public.dragonfly_role_audit_log
FROM public;
REVOKE ALL ON public.dragonfly_role_audit_log
FROM anon;
REVOKE ALL ON public.dragonfly_role_audit_log
FROM authenticated;
GRANT SELECT ON public.dragonfly_role_audit_log TO authenticated;
GRANT INSERT,
    SELECT ON public.dragonfly_role_audit_log TO service_role;
COMMENT ON TABLE public.dragonfly_role_mappings IS 'RBAC role assignments for Dragonfly users. Maps auth.uid() to application roles.';
COMMENT ON TABLE public.dragonfly_role_audit_log IS 'Immutable audit log of all role grants/revokes for compliance.';
COMMENT ON FUNCTION public.dragonfly_has_role(text) IS 'Check if current user has a specific role (or is admin/service_role).';
COMMENT ON FUNCTION public.dragonfly_is_admin() IS 'Check if current user is admin or service_role.';
SELECT public.pgrst_reload();
COMMIT;
