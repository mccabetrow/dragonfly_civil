-- ============================================================================
-- 0203_rls_force_core_judgment_tables.sql
-- Harden RLS on core judgment tables: Enable + FORCE ROW LEVEL SECURITY
-- ============================================================================
--
-- PURPOSE:
--   Per the Dragonfly Security and Compliance Audit (docs/dragonfly_security_and_compliance_audit.md),
--   all tables containing PII and audit data must have RLS enabled AND forced.
--   FORCE ROW LEVEL SECURITY ensures that even table owners (postgres) are
--   subject to RLS policies, preventing accidental data exposure.
--
-- TABLES HARDENED:
--   - public.core_judgments (debtor PII, judgment amounts)
--   - public.debtor_intelligence (employer info, bank info, income data)
--   - public.enforcement_actions (enforcement history, generated documents)
--   - public.external_data_calls (FCRA audit trail for skip-trace APIs)
--   - public.communications (FDCPA-regulated contact log)
--
-- SECURITY MODEL:
--   - SELECT: authenticated + service_role
--   - INSERT/UPDATE/DELETE: service_role only
--   - RLS is FORCED so even superuser queries go through policies
--
-- WARNING:
--   These tables contain consumer PII and compliance-critical audit data.
--   RLS must NEVER be disabled in production. Any changes to these policies
--   require security review per the Dragonfly operating model.
--
-- SAFE PATTERNS:
--   - ALTER TABLE ... ENABLE ROW LEVEL SECURITY (idempotent)
--   - ALTER TABLE ... FORCE ROW LEVEL SECURITY (idempotent)
--   - CREATE POLICY IF NOT EXISTS equivalent via DO block
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- TABLE: public.core_judgments
-- Contains: Debtor names, addresses, SSN fragments, judgment amounts
-- ============================================================================
ALTER TABLE public.core_judgments ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.core_judgments FORCE ROW LEVEL SECURITY;
-- Add policies if they don't exist (using DO block for conditional creation)
DO $$ BEGIN -- SELECT policy for authenticated users
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'core_judgments'
        AND policyname = 'core_judgments_select_authenticated'
) THEN CREATE POLICY core_judgments_select_authenticated ON public.core_judgments FOR
SELECT USING (auth.role() IN ('authenticated', 'service_role'));
END IF;
-- INSERT policy for service_role only
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'core_judgments'
        AND policyname = 'core_judgments_insert_service'
) THEN CREATE POLICY core_judgments_insert_service ON public.core_judgments FOR
INSERT WITH CHECK (auth.role() = 'service_role');
END IF;
-- UPDATE policy for service_role only
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'core_judgments'
        AND policyname = 'core_judgments_update_service'
) THEN CREATE POLICY core_judgments_update_service ON public.core_judgments FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
-- DELETE policy for service_role only
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'core_judgments'
        AND policyname = 'core_judgments_delete_service'
) THEN CREATE POLICY core_judgments_delete_service ON public.core_judgments FOR DELETE USING (auth.role() = 'service_role');
END IF;
END $$;
COMMENT ON TABLE public.core_judgments IS 'Core judgment records with debtor PII. RLS FORCED per Dragonfly security audit. Never disable RLS in prod.';
-- ============================================================================
-- TABLE: public.debtor_intelligence
-- Contains: Employer info, bank names, income bands, skip-trace results
-- ============================================================================
ALTER TABLE public.debtor_intelligence ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.debtor_intelligence FORCE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'debtor_intelligence'
        AND policyname = 'debtor_intelligence_select_authenticated'
) THEN CREATE POLICY debtor_intelligence_select_authenticated ON public.debtor_intelligence FOR
SELECT USING (auth.role() IN ('authenticated', 'service_role'));
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'debtor_intelligence'
        AND policyname = 'debtor_intelligence_insert_service'
) THEN CREATE POLICY debtor_intelligence_insert_service ON public.debtor_intelligence FOR
INSERT WITH CHECK (auth.role() = 'service_role');
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'debtor_intelligence'
        AND policyname = 'debtor_intelligence_update_service'
) THEN CREATE POLICY debtor_intelligence_update_service ON public.debtor_intelligence FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'debtor_intelligence'
        AND policyname = 'debtor_intelligence_delete_service'
) THEN CREATE POLICY debtor_intelligence_delete_service ON public.debtor_intelligence FOR DELETE USING (auth.role() = 'service_role');
END IF;
END $$;
COMMENT ON TABLE public.debtor_intelligence IS 'Debtor employer/bank/income intelligence. RLS FORCED per Dragonfly security audit. Never disable RLS in prod.';
-- ============================================================================
-- TABLE: public.enforcement_actions
-- Contains: Enforcement history, attorney-signed documents, generated PDFs
-- ============================================================================
ALTER TABLE public.enforcement_actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.enforcement_actions FORCE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'enforcement_actions'
        AND policyname = 'enforcement_actions_select_authenticated'
) THEN CREATE POLICY enforcement_actions_select_authenticated ON public.enforcement_actions FOR
SELECT USING (auth.role() IN ('authenticated', 'service_role'));
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'enforcement_actions'
        AND policyname = 'enforcement_actions_insert_service'
) THEN CREATE POLICY enforcement_actions_insert_service ON public.enforcement_actions FOR
INSERT WITH CHECK (auth.role() = 'service_role');
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'enforcement_actions'
        AND policyname = 'enforcement_actions_update_service'
) THEN CREATE POLICY enforcement_actions_update_service ON public.enforcement_actions FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'enforcement_actions'
        AND policyname = 'enforcement_actions_delete_service'
) THEN CREATE POLICY enforcement_actions_delete_service ON public.enforcement_actions FOR DELETE USING (auth.role() = 'service_role');
END IF;
END $$;
COMMENT ON TABLE public.enforcement_actions IS 'Enforcement action history and documents. RLS FORCED per Dragonfly security audit. Never disable RLS in prod.';
-- ============================================================================
-- TABLE: public.external_data_calls
-- Contains: FCRA audit trail for skip-trace API calls (compliance-critical)
-- NOTE: This table is append-only; UPDATE/DELETE policies are intentionally
--       NOT added to maintain audit integrity. Existing RLS from 0201 enforced.
-- ============================================================================
ALTER TABLE public.external_data_calls ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.external_data_calls FORCE ROW LEVEL SECURITY;
-- external_data_calls already has policies from 0201_fcra_audit_log.sql:
--   - external_data_calls_select_authenticated (SELECT)
--   - external_data_calls_insert_service (INSERT)
-- No UPDATE/DELETE policies by design (append-only audit log)
COMMENT ON TABLE public.external_data_calls IS 'FCRA audit log for external data API calls. RLS FORCED. Append-only; no UPDATE/DELETE. Never disable RLS in prod.';
-- ============================================================================
-- TABLE: public.communications
-- Contains: FDCPA-regulated contact log with debtor communications
-- NOTE: This table is append-only; UPDATE/DELETE policies are intentionally
--       NOT added to maintain audit integrity. Existing RLS from 0202 enforced.
-- ============================================================================
ALTER TABLE public.communications ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.communications FORCE ROW LEVEL SECURITY;
-- communications already has policies from 0202_fdcpa_contact_guard.sql:
--   - communications_select_authenticated (SELECT)
--   - communications_insert_service (INSERT)
-- No UPDATE/DELETE policies by design (append-only communications log)
COMMENT ON TABLE public.communications IS 'FDCPA-regulated communications log. RLS FORCED. Append-only; no UPDATE/DELETE. Never disable RLS in prod.';
-- ============================================================================
-- GRANTS (ensure proper access levels)
-- ============================================================================
-- core_judgments
REVOKE ALL ON public.core_judgments
FROM PUBLIC;
REVOKE ALL ON public.core_judgments
FROM anon;
GRANT SELECT ON public.core_judgments TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.core_judgments TO service_role;
-- debtor_intelligence
REVOKE ALL ON public.debtor_intelligence
FROM PUBLIC;
REVOKE ALL ON public.debtor_intelligence
FROM anon;
GRANT SELECT ON public.debtor_intelligence TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.debtor_intelligence TO service_role;
-- enforcement_actions
REVOKE ALL ON public.enforcement_actions
FROM PUBLIC;
REVOKE ALL ON public.enforcement_actions
FROM anon;
GRANT SELECT ON public.enforcement_actions TO authenticated;
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON public.enforcement_actions TO service_role;
-- external_data_calls (append-only: no UPDATE/DELETE grants)
-- Grants already set in 0201, but reinforce here
REVOKE ALL ON public.external_data_calls
FROM PUBLIC;
REVOKE ALL ON public.external_data_calls
FROM anon;
GRANT SELECT ON public.external_data_calls TO authenticated;
GRANT SELECT,
    INSERT ON public.external_data_calls TO service_role;
-- communications (append-only: no UPDATE/DELETE grants)
-- Grants already set in 0202, but reinforce here
REVOKE ALL ON public.communications
FROM PUBLIC;
REVOKE ALL ON public.communications
FROM anon;
GRANT SELECT ON public.communications TO authenticated;
GRANT SELECT,
    INSERT ON public.communications TO service_role;
-- ============================================================================
-- RELOAD POSTGREST SCHEMA CACHE
-- ============================================================================
SELECT public.pgrst_reload();
COMMIT;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
