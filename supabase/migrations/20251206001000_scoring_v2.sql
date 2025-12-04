-- Migration: Scoring v2 with Explainable Breakdown
-- Version: Dragonfly Engine v0.2.x
-- Description: Adds score breakdown columns to judgments and creates scorecard view
-- ============================================================================
-- ============================================================================
-- 1. Ensure enforcement schema exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS enforcement;
-- ============================================================================
-- 2. Add breakdown columns to public.judgments
-- ============================================================================
-- Add score_employment column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'score_employment'
) THEN
ALTER TABLE public.judgments
ADD COLUMN score_employment INT NOT NULL DEFAULT 0;
END IF;
END $$;
-- Add score_assets column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'score_assets'
) THEN
ALTER TABLE public.judgments
ADD COLUMN score_assets INT NOT NULL DEFAULT 0;
END IF;
END $$;
-- Add score_recency column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'score_recency'
) THEN
ALTER TABLE public.judgments
ADD COLUMN score_recency INT NOT NULL DEFAULT 0;
END IF;
END $$;
-- Add score_banking column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'judgments'
        AND column_name = 'score_banking'
) THEN
ALTER TABLE public.judgments
ADD COLUMN score_banking INT NOT NULL DEFAULT 0;
END IF;
END $$;
-- Add comments for documentation
COMMENT ON COLUMN public.judgments.score_employment IS 'Employment component of collectability score (0-40)';
COMMENT ON COLUMN public.judgments.score_assets IS 'Assets component of collectability score (0-30)';
COMMENT ON COLUMN public.judgments.score_recency IS 'Recency component of collectability score (0-20)';
COMMENT ON COLUMN public.judgments.score_banking IS 'Banking component of collectability score (0-10)';
-- ============================================================================
-- 3. Create scorecard view
-- ============================================================================
CREATE OR REPLACE VIEW enforcement.v_score_card AS
SELECT j.id,
    j.case_number,
    j.plaintiff_name,
    j.defendant_name,
    j.judgment_amount,
    j.collectability_score AS total_score,
    j.score_employment,
    j.score_assets,
    j.score_recency,
    j.score_banking,
    -- Computed validation: breakdown should sum to total
    (
        j.score_employment + j.score_assets + j.score_recency + j.score_banking
    ) AS breakdown_sum,
    CASE
        WHEN j.collectability_score = (
            j.score_employment + j.score_assets + j.score_recency + j.score_banking
        ) THEN TRUE
        ELSE FALSE
    END AS breakdown_matches_total
FROM public.judgments j
ORDER BY j.collectability_score DESC NULLS LAST;
COMMENT ON VIEW enforcement.v_score_card IS 'Explainable score breakdown for each judgment with validation';
-- ============================================================================
-- 4. Grant permissions
-- ============================================================================
GRANT USAGE ON SCHEMA enforcement TO authenticated;
GRANT USAGE ON SCHEMA enforcement TO service_role;
GRANT SELECT ON enforcement.v_score_card TO authenticated;
GRANT SELECT ON enforcement.v_score_card TO service_role;
-- ============================================================================
-- 5. Index for score-based queries (optional but recommended)
-- ============================================================================
CREATE INDEX IF NOT EXISTS idx_judgments_collectability_score ON public.judgments(collectability_score DESC NULLS LAST);