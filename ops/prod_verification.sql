-- ============================================================================
-- PRODUCTION SECURITY VERIFICATION QUERIES
-- ============================================================================
-- Purpose: Post-migration verification of Zero Trust security invariants
-- Usage:   Run in Supabase SQL Editor (Dashboard > SQL Editor) after deployment
-- Date:    2024-12-26
-- ============================================================================
-- ============================================================================
-- QUERY 1: RLS COMPLIANCE (Target: 0 violations)
-- ============================================================================
-- Every table in audited schemas MUST have:
--   - RLS enabled (has_rls = true)
--   - FORCE RLS enabled (force_rls = true) 
--   - compliance_status = 'COMPLIANT'
--
-- If this returns any rows, you have a security vulnerability.
-- ============================================================================
SELECT count(*) AS violations,
    'RLS COMPLIANCE CHECK' AS check_name,
    CASE
        WHEN count(*) = 0 THEN '✅ PASS: All tables have RLS enforced'
        ELSE '❌ FAIL: ' || count(*) || ' tables missing RLS enforcement'
    END AS result
FROM ops.v_rls_coverage
WHERE compliance_status != 'COMPLIANT';
-- Show violation details if any exist:
SELECT schema_name,
    table_name,
    has_rls,
    force_rls,
    compliance_status,
    owner
FROM ops.v_rls_coverage
WHERE compliance_status != 'COMPLIANT'
ORDER BY compliance_status,
    schema_name,
    table_name;
-- ============================================================================
-- QUERY 2: PUBLIC EXPOSURE AUDIT (Target: Only intentional dashboard views)
-- ============================================================================
-- Lists all grants to 'anon' or 'public' roles.
-- 
-- EXPECTED: Only dashboard views should appear here.
-- DANGEROUS: Any table with direct anon/public access is a vulnerability.
--
-- Acceptable entries (read-only dashboard views):
--   - public.v_plaintiffs_overview (SELECT only)
--   - public.v_judgment_pipeline (SELECT only)
--   - public.v_enforcement_overview (SELECT only)
--   - public.v_enforcement_recent (SELECT only)
--   - public.v_plaintiff_call_queue (SELECT only)
-- ============================================================================
SELECT schema_name,
    table_name,
    grantee,
    privileges,
    risk_level,
    CASE
        WHEN risk_level = 'DANGEROUS' THEN '❌ REVIEW REQUIRED'
        ELSE '✅ OK'
    END AS action
FROM ops.v_public_grants
WHERE grantee IN ('anon', 'public')
ORDER BY risk_level DESC,
    schema_name,
    table_name;
-- ============================================================================
-- QUERY 3: SECURITY DEFINER AUDIT (Target: Only whitelisted RPCs)
-- ============================================================================
-- SECURITY DEFINER functions execute with owner privileges, bypassing RLS.
-- This is powerful and dangerous if misused.
--
-- ALLOWED statuses:
--   - ALLOWED: Functions in 'ops' schema (admin tooling)
--   - WHITELISTED: Approved public RPCs for job queue, intake, etc.
--
-- REVIEW_REQUIRED: Any function not on the whitelist needs manual review
--                  before production deployment.
-- ============================================================================
SELECT schema_name,
    function_name AS name,
    owner,
    arguments,
    return_type,
    security_status,
    CASE
        WHEN security_status = 'REVIEW_REQUIRED' THEN '❌ NEEDS REVIEW'
        ELSE '✅ Approved'
    END AS action
FROM ops.v_security_definers
ORDER BY security_status DESC,
    schema_name,
    function_name;
-- ============================================================================
-- SUMMARY: One-Shot Health Check
-- ============================================================================
-- Run this single query for a quick pass/fail summary
WITH rls_check AS (
    SELECT count(*) AS violations
    FROM ops.v_rls_coverage
    WHERE compliance_status != 'COMPLIANT'
),
grant_check AS (
    SELECT count(*) AS dangerous_grants
    FROM ops.v_public_grants
    WHERE grantee IN ('anon', 'public')
        AND risk_level = 'DANGEROUS'
),
definer_check AS (
    SELECT count(*) AS unreviewed
    FROM ops.v_security_definers
    WHERE security_status = 'REVIEW_REQUIRED'
)
SELECT 'PRODUCTION SECURITY AUDIT' AS report,
    rls_check.violations AS rls_violations,
    grant_check.dangerous_grants AS dangerous_grants,
    definer_check.unreviewed AS unreviewed_definers,
    CASE
        WHEN rls_check.violations = 0
        AND grant_check.dangerous_grants = 0
        AND definer_check.unreviewed = 0 THEN '✅ ALL CHECKS PASSED'
        ELSE '❌ SECURITY ISSUES DETECTED'
    END AS overall_status
FROM rls_check,
    grant_check,
    definer_check;