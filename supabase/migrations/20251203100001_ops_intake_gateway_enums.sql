-- ============================================================================
-- 0306a_ops_intake_gateway_enums.sql
-- Split from 0306 to avoid "unsafe use of new value" enum issue
-- ============================================================================
-- PostgreSQL requires enum value additions to be in a separate transaction
-- from any objects that use those values.
-- ============================================================================
BEGIN;
-- ============================================================================
-- EXTEND: judgment_status_enum with intake statuses
-- ============================================================================
-- Add new intake-related status values to the existing enum.
-- Note: PostgreSQL enum extension is safe (no data migration needed)
-- ============================================================================
-- Add 'new_candidate' for freshly imported leads
DO $$ BEGIN ALTER TYPE public.judgment_status_enum
ADD VALUE IF NOT EXISTS 'new_candidate' BEFORE 'unsatisfied';
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- Add 'awaiting_ops_review' for AI-validated leads pending human check
DO $$ BEGIN ALTER TYPE public.judgment_status_enum
ADD VALUE IF NOT EXISTS 'awaiting_ops_review'
AFTER 'new_candidate';
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- Add 'ops_approved' for human-verified leads ready for enrichment
DO $$ BEGIN ALTER TYPE public.judgment_status_enum
ADD VALUE IF NOT EXISTS 'ops_approved'
AFTER 'awaiting_ops_review';
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
-- Add 'ops_rejected' for leads that failed human verification
DO $$ BEGIN ALTER TYPE public.judgment_status_enum
ADD VALUE IF NOT EXISTS 'ops_rejected'
AFTER 'ops_approved';
EXCEPTION
WHEN duplicate_object THEN NULL;
END $$;
COMMENT ON TYPE public.judgment_status_enum IS 'Lifecycle status of a judgment record. Includes intake stages: new_candidate → awaiting_ops_review → ops_approved/ops_rejected → unsatisfied → enforcement stages.';
-- ============================================================================
-- ENUM: intake_validation_result
-- ============================================================================
-- Result classification from AI validation
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'intake_validation_result'
) THEN CREATE TYPE public.intake_validation_result AS ENUM (
    'valid',
    -- All checks passed
    'invalid',
    -- One or more critical issues
    'needs_review' -- Ambiguous, requires human judgment
);
END IF;
END $$;
COMMENT ON TYPE public.intake_validation_result IS 'AI validation result: valid (auto-approve), invalid (auto-reject), needs_review (human required).';
COMMIT;
