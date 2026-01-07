-- ============================================================================
-- Migration: Fix SECURITY DEFINER functions in judgments schema
-- Purpose:   Add search_path to prevent SQL injection vectors
-- Author:    DevSecOps Lead
-- Date:      2026-01-07
-- ============================================================================
-- 
-- SECURITY ISSUE:
-- SECURITY DEFINER functions execute with the privileges of the function owner.
-- Without a locked search_path, an attacker could:
--   1. Create a malicious function in a schema they control
--   2. Manipulate search_path to make that function execute instead
--
-- FIX: Set search_path explicitly to trusted schemas only
-- ============================================================================
-- Fix judgments.get_case_statistics
ALTER FUNCTION judgments.get_case_statistics(uuid)
SET search_path = judgments,
    public,
    pg_temp;
-- Fix judgments.log_event
ALTER FUNCTION judgments.log_event(text, text, uuid, jsonb)
SET search_path = judgments,
    public,
    pg_temp;
-- Fix judgments.refresh_search_index
ALTER FUNCTION judgments.refresh_search_index()
SET search_path = judgments,
    public,
    pg_temp;
-- ============================================================================
-- Verify the fix
-- ============================================================================
DO $$
DECLARE v_count INT;
BEGIN
SELECT COUNT(*) INTO v_count
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.prosecdef = true
    AND n.nspname = 'judgments'
    AND (
        p.proconfig IS NULL
        OR NOT EXISTS (
            SELECT 1
            FROM unnest(p.proconfig) AS cfg
            WHERE cfg LIKE 'search_path=%'
        )
    );
IF v_count > 0 THEN RAISE EXCEPTION 'Still have % SECURITY DEFINER functions without search_path!',
v_count;
END IF;
RAISE NOTICE '✓ All judgments SECURITY DEFINER functions now have search_path';
END $$;