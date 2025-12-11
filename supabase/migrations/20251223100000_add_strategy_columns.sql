-- ============================================================================
-- Migration: Add Strategy Columns to enforcement_plans
-- Created: 2025-12-21
-- Purpose: Add strategy_type and strategy_reason columns for Smart Strategy Agent
-- ============================================================================
-- 
-- The Smart Strategy Agent automatically determines the best recovery method
-- based on debtor intelligence. These columns track:
--   - strategy_type: The chosen enforcement action (wage_garnishment, bank_levy, etc.)
--   - strategy_reason: Human-readable explanation of why this strategy was chosen
--
-- Decision logic:
--   1. IF employer found → wage_garnishment
--   2. ELIF bank_name found → bank_levy  
--   3. ELIF home_ownership = 'owner' → property_lien
--   4. ELSE → surveillance (queue for enrichment)
--
-- ============================================================================
-- Add strategy_type column
ALTER TABLE enforcement.enforcement_plans
ADD COLUMN IF NOT EXISTS strategy_type text;
COMMENT ON COLUMN enforcement.enforcement_plans.strategy_type IS 'Enforcement strategy: wage_garnishment, bank_levy, property_lien, surveillance';
-- Add strategy_reason column
ALTER TABLE enforcement.enforcement_plans
ADD COLUMN IF NOT EXISTS strategy_reason text;
COMMENT ON COLUMN enforcement.enforcement_plans.strategy_reason IS 'Human-readable explanation of why this strategy was chosen by the Smart Strategy Agent';
-- Add judgment_id column (enforcement_plans currently has case_id but not judgment_id)
-- Some workflows pass judgment_id directly
ALTER TABLE enforcement.enforcement_plans
ADD COLUMN IF NOT EXISTS judgment_id uuid;
COMMENT ON COLUMN enforcement.enforcement_plans.judgment_id IS 'Link to core_judgments.id for direct judgment association';
-- Create index for strategy_type queries
CREATE INDEX IF NOT EXISTS idx_enforcement_plans_strategy_type ON enforcement.enforcement_plans (strategy_type)
WHERE strategy_type IS NOT NULL;
-- Create index for judgment_id lookups
CREATE INDEX IF NOT EXISTS idx_enforcement_plans_judgment_id ON enforcement.enforcement_plans (judgment_id)
WHERE judgment_id IS NOT NULL;
-- ============================================================================
-- GRANTS
-- ============================================================================
-- Ensure authenticated and service_role can access these columns
GRANT SELECT,
    INSERT,
    UPDATE ON enforcement.enforcement_plans TO authenticated,
    service_role;