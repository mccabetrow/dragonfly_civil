-- Migration: 20251215000000_cases_source_system.sql
-- Purpose: Add source_system column to judgments.cases for tracking data origin
-- Idempotent: Safe to run multiple times
-- Add source_system column to judgments.cases if it doesn't exist
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'judgments'
        AND table_name = 'cases'
        AND column_name = 'source_system'
) THEN
ALTER TABLE judgments.cases
ADD COLUMN source_system text;
COMMENT ON COLUMN judgments.cases.source_system IS 'Tracks the origin system of the case data (e.g., simplicity, jbi, manual)';
END IF;
END $$;
