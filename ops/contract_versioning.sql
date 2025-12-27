-- =============================================================================
-- Migration: System Contract Versioning
-- =============================================================================
-- Provides a mechanism to detect API drift between database schema and
-- application code. The contract hash changes whenever:
-- - An RPC signature changes (name, arguments, return type)
-- - A view is added, removed, or its columns change
-- - The api schema structure changes
--
-- Usage:
--   SELECT ops.get_system_contract_hash();
--   -- Returns: 'a1b2c3d4e5f6...' (32-char MD5 hash)
--
-- The deploy script compares this hash against the expected value in code.
-- If they differ, deployment is blocked until the code is updated.
-- =============================================================================
-- =============================================================================
-- Contract Hash Function
-- =============================================================================
CREATE OR REPLACE FUNCTION ops.get_system_contract_hash() RETURNS text LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,
    ops AS $$
DECLARE contract_string text := '';
rpc_row record;
view_row record;
col_row record;
BEGIN -- =========================================================================
-- Part 1: API Schema RPCs (SECURITY DEFINER functions in api.*)
-- =========================================================================
-- Collect function signatures: name, argument types, return type
FOR rpc_row IN
SELECT p.proname AS func_name,
    pg_get_function_arguments(p.oid) AS args,
    pg_get_function_result(p.oid) AS returns
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'api'
ORDER BY p.proname LOOP contract_string := contract_string || 'RPC:' || rpc_row.func_name || '(' || COALESCE(rpc_row.args, '') || ')' || '->' || rpc_row.returns || ';';
END LOOP;
-- =========================================================================
-- Part 2: Public Schema RPCs (business logic functions)
-- =========================================================================
-- Include key public RPCs that the frontend depends on
FOR rpc_row IN
SELECT p.proname AS func_name,
    pg_get_function_arguments(p.oid) AS args,
    pg_get_function_result(p.oid) AS returns
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.proname IN (
        -- Core business RPCs
        'ceo_12_metrics',
        'ceo_command_center_metrics',
        'insert_case',
        'insert_case_with_entities',
        'get_enforcement_timeline',
        'get_intake_stats',
        'get_litigation_budget',
        'score_case_collectability',
        'set_plaintiff_status',
        'portfolio_judgments_paginated'
    )
ORDER BY p.proname LOOP contract_string := contract_string || 'PUB_RPC:' || rpc_row.func_name || '(' || COALESCE(rpc_row.args, '') || ')' || '->' || rpc_row.returns || ';';
END LOOP;
-- =========================================================================
-- Part 3: Dashboard Views (intake/ops/public views)
-- =========================================================================
-- Include views that the dashboard directly consumes
FOR view_row IN
SELECT table_schema,
    table_name
FROM information_schema.views
WHERE table_schema IN (
        'intake',
        'ops',
        'public',
        'analytics',
        'enforcement'
    )
    AND table_name LIKE 'v_%'
ORDER BY table_schema,
    table_name LOOP contract_string := contract_string || 'VIEW:' || view_row.table_schema || '.' || view_row.table_name || '(';
-- Add column names and types for each view
FOR col_row IN
SELECT column_name,
    data_type
FROM information_schema.columns
WHERE table_schema = view_row.table_schema
    AND table_name = view_row.table_name
ORDER BY ordinal_position LOOP contract_string := contract_string || col_row.column_name || ':' || col_row.data_type || ',';
END LOOP;
contract_string := contract_string || ');';
END LOOP;
-- =========================================================================
-- Part 4: Core Tables (schema fingerprint)
-- =========================================================================
-- Include critical table structures
FOR col_row IN
SELECT c.table_schema,
    c.table_name,
    c.column_name,
    c.data_type,
    c.is_nullable
FROM information_schema.columns c
WHERE c.table_schema = 'public'
    AND c.table_name IN ('judgments', 'plaintiffs', 'debtors', 'entities')
ORDER BY c.table_schema,
    c.table_name,
    c.ordinal_position LOOP contract_string := contract_string || 'COL:' || col_row.table_schema || '.' || col_row.table_name || '.' || col_row.column_name || ':' || col_row.data_type || ':' || col_row.is_nullable || ';';
END LOOP;
-- Return MD5 hash of the contract string
RETURN md5(contract_string);
END;
$$;
COMMENT ON FUNCTION ops.get_system_contract_hash() IS 'Returns an MD5 hash of the system public interface (RPCs, views, core tables). 
Used for contract versioning to detect API drift between deployments.';
-- =============================================================================
-- Contract Details Function (for debugging)
-- =============================================================================
CREATE OR REPLACE FUNCTION ops.get_system_contract_details() RETURNS TABLE (
        component_type text,
        component_name text,
        signature text
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,
    ops AS $$ BEGIN -- API RPCs
    RETURN QUERY
SELECT 'api_rpc'::text AS component_type,
    p.proname::text AS component_name,
    (
        '(' || COALESCE(pg_get_function_arguments(p.oid), '') || ') -> ' || pg_get_function_result(p.oid)
    )::text AS signature
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'api'
ORDER BY p.proname;
-- Public RPCs (key ones)
RETURN QUERY
SELECT 'public_rpc'::text,
    p.proname::text,
    (
        '(' || COALESCE(pg_get_function_arguments(p.oid), '') || ') -> ' || pg_get_function_result(p.oid)
    )::text
FROM pg_proc p
    JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE n.nspname = 'public'
    AND p.proname IN (
        'ceo_12_metrics',
        'ceo_command_center_metrics',
        'insert_case',
        'insert_case_with_entities',
        'get_enforcement_timeline',
        'get_intake_stats',
        'get_litigation_budget',
        'score_case_collectability',
        'set_plaintiff_status',
        'portfolio_judgments_paginated'
    )
ORDER BY p.proname;
-- Views
RETURN QUERY
SELECT 'view'::text,
    (table_schema || '.' || table_name)::text,
    (
        SELECT string_agg(
                column_name || ':' || data_type,
                ', '
                ORDER BY ordinal_position
            )
        FROM information_schema.columns c
        WHERE c.table_schema = v.table_schema
            AND c.table_name = v.table_name
    )::text
FROM information_schema.views v
WHERE table_schema IN (
        'intake',
        'ops',
        'public',
        'analytics',
        'enforcement'
    )
    AND table_name LIKE 'v_%'
ORDER BY table_schema,
    table_name;
END;
$$;
COMMENT ON FUNCTION ops.get_system_contract_details() IS 'Returns detailed breakdown of all components included in the system contract hash. 
Useful for debugging contract mismatches.';
-- =============================================================================
-- Contract Version Table (for tracking changes)
-- =============================================================================
CREATE TABLE IF NOT EXISTS ops.contract_versions (
    id serial PRIMARY KEY,
    contract_hash text NOT NULL,
    component_count integer NOT NULL,
    captured_at timestamptz NOT NULL DEFAULT now(),
    captured_by text DEFAULT current_user,
    notes text
);
COMMENT ON TABLE ops.contract_versions IS 'Historical record of contract hashes for tracking API evolution.';
-- =============================================================================
-- Capture Contract Snapshot Function
-- =============================================================================
CREATE OR REPLACE FUNCTION ops.capture_contract_snapshot(p_notes text DEFAULT NULL) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog,
    ops AS $$
DECLARE v_hash text;
v_count integer;
BEGIN -- Get current hash
v_hash := ops.get_system_contract_hash();
-- Count components
SELECT COUNT(*) INTO v_count
FROM ops.get_system_contract_details();
-- Insert snapshot
INSERT INTO ops.contract_versions (contract_hash, component_count, notes)
VALUES (v_hash, v_count, p_notes);
RETURN v_hash;
END;
$$;
COMMENT ON FUNCTION ops.capture_contract_snapshot(text) IS 'Captures the current contract hash and stores it in ops.contract_versions for historical tracking.';
-- =============================================================================
-- Security: Grants
-- =============================================================================
-- Allow service role and anon to check contract hash
GRANT EXECUTE ON FUNCTION ops.get_system_contract_hash() TO anon,
    authenticated,
    service_role;
GRANT EXECUTE ON FUNCTION ops.get_system_contract_details() TO service_role;
GRANT EXECUTE ON FUNCTION ops.capture_contract_snapshot(text) TO service_role;
-- Table access for service role only
GRANT SELECT,
    INSERT ON ops.contract_versions TO service_role;
GRANT USAGE ON SEQUENCE ops.contract_versions_id_seq TO service_role;
-- =============================================================================
-- RLS on contract_versions
-- =============================================================================
ALTER TABLE ops.contract_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_contract_versions" ON ops.contract_versions;
CREATE POLICY "service_role_contract_versions" ON ops.contract_versions FOR ALL TO service_role USING (true) WITH CHECK (true);