-- ============================================================================
-- ROLLBACK MIGRATION TEMPLATE
-- ============================================================================
--
-- PURPOSE: Template for creating rollback migrations that revert schema changes.
--
-- HOW TO USE:
-- 1. Copy this template to a new file named:
--    rollback_<current_timestamp>_from_<forward_migration_id>.sql
--
-- 2. Fill in the sections below with the INVERSE operations of your forward migration.
--
-- 3. Test in DEV first: Run against dev, then verify with:
--    python scripts/verify_db_contract.py --env dev
--
-- 4. Apply to PROD only after dev verification.
--
-- IMPORTANT:
-- - Rollbacks are DESTRUCTIVE. They may drop tables/columns and lose data.
-- - Always ensure you have a database backup before applying.
-- - Each operation should be idempotent (safe to run twice).
--
-- ============================================================================
-- ============================================================================
-- SECTION 1: REVERT TABLE CHANGES
-- ============================================================================
-- If your forward migration created new tables, DROP them here.
-- If it added columns, use ALTER TABLE ... DROP COLUMN.
-- If it modified column types, revert to the original type.
-- Example: Drop a table created in forward migration
-- DROP TABLE IF EXISTS public.new_feature_table;
-- Example: Drop a column added in forward migration
-- ALTER TABLE public.existing_table
-- DROP COLUMN IF EXISTS new_column;
-- Example: Revert column type change
-- ALTER TABLE public.existing_table
-- ALTER COLUMN modified_column TYPE varchar(100);
-- ============================================================================
-- SECTION 2: REVERT RPC FUNCTION SIGNATURES
-- ============================================================================
-- If your forward migration changed function signatures, restore the OLD version.
-- CRITICAL: ops.* functions are contract-bound. Their signatures must match
-- what the OLD code expects.
--
-- Use CREATE OR REPLACE FUNCTION to overwrite with the previous signature.
-- Example: Restore previous function signature
/*
 CREATE OR REPLACE FUNCTION ops.example_function(
 -- OLD argument list (before forward migration)
 p_old_arg1 TEXT,
 p_old_arg2 INTEGER
 )
 RETURNS JSONB
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path = ops, public
 AS $$
 BEGIN
 -- OLD function body
 RETURN jsonb_build_object('status', 'ok');
 END;
 $$;
 
 -- Grant execute permission
 GRANT EXECUTE ON FUNCTION ops.example_function(TEXT, INTEGER) TO service_role;
 */
-- ============================================================================
-- SECTION 3: REVERT VIEW CHANGES
-- ============================================================================
-- If your forward migration modified views, restore the OLD definition.
-- Example: Drop view created in forward migration
-- DROP VIEW IF EXISTS public.new_dashboard_view;
-- Example: Restore previous view definition
/*
 CREATE OR REPLACE VIEW public.restored_view AS
 SELECT
 id,
 -- OLD column list
 original_column1,
 original_column2
 FROM public.source_table;
 */
-- ============================================================================
-- SECTION 4: REVERT INDEX/CONSTRAINT CHANGES
-- ============================================================================
-- If your forward migration added indexes or constraints, drop them.
-- If it dropped indexes, recreate them.
-- Example: Drop index created in forward migration
-- DROP INDEX IF EXISTS public.idx_new_index;
-- Example: Recreate index dropped in forward migration
-- CREATE INDEX IF NOT EXISTS idx_restored_index
-- ON public.existing_table(column_name);
-- ============================================================================
-- SECTION 5: REVERT PERMISSION CHANGES
-- ============================================================================
-- If your forward migration changed grants, revert them.
-- Example: Revoke permissions granted in forward migration
-- REVOKE SELECT ON public.new_table FROM anon;
-- Example: Re-grant permissions revoked in forward migration
-- GRANT SELECT ON public.restored_table TO anon;
-- ============================================================================
-- SECTION 6: DATA MIGRATION (OPTIONAL)
-- ============================================================================
-- If your forward migration included data transformations, you may need
-- to restore the original data state. This is often not possible and should
-- be handled carefully.
--
-- CAUTION: Data rollbacks can be complex and may require backups.
-- Example: Restore data from backup column
/*
 UPDATE public.existing_table
 SET original_column = backup_column
 WHERE backup_column IS NOT NULL;
 
 ALTER TABLE public.existing_table
 DROP COLUMN IF EXISTS backup_column;
 */
-- ============================================================================
-- VERIFICATION
-- ============================================================================
-- After running this rollback, verify with:
--
-- 1. Check RPC signatures:
--    python scripts/verify_db_contract.py --env <env>
--
-- 2. Run doctor:
--    python -m tools.doctor --env <env>
--
-- 3. Run contract tests:
--    pytest tests/test_rpc_contract.py -v
--
-- Expected: All checks should pass, matching the OLD code version.
-- ============================================================================
-- Placeholder to prevent empty migration file error
SELECT 'Rollback template - replace this with actual rollback operations';