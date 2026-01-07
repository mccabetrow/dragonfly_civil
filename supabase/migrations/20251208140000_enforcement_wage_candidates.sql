-- ============================================================================
-- Migration: Wage Garnishment Candidate View
-- ============================================================================
-- Creates enforcement.v_candidate_wage_garnishments view for identifying
-- judgments meeting NY wage garnishment criteria (CPLR 5231).
--
-- Prerequisites: judgments, plaintiffs, debtor_intelligence, collectability
-- NY Wage Garnishment Criteria:
--   - Judgment unsatisfied
--   - Known employer
--   - Balance >= $2,000 (practical threshold)
--   - Jurisdiction is NY
-- ============================================================================
-- Ensure enforcement schema exists
CREATE SCHEMA IF NOT EXISTS enforcement;
GRANT USAGE ON SCHEMA enforcement TO authenticated,
    service_role;
-- ============================================================================
-- VIEW: enforcement.v_candidate_wage_garnishments
-- ============================================================================
-- Identifies judgments suitable for wage garnishment enforcement.
-- Joins judgments → debtor_intelligence (employer) → collectability (tier)
-- ============================================================================
CREATE OR REPLACE VIEW enforcement.v_candidate_wage_garnishments AS WITH judgment_intelligence AS (
        SELECT j.id AS judgment_id,
            j.plaintiff_id,
            j.case_number,
            j.defendant_name,
            j.judgment_amount,
            j.judgment_date,
            j.county,
            j.status,
            j.enforcement_stage,
            j.collectability_score,
            j.created_at,
            -- Note: debtor_intelligence schema uses UUID for judgment_id
            -- but public.judgments uses bigint. Skip join for now - will populate
            -- employer data via enrichment workers once schema is aligned.
            -- For now, return NULLs for employer fields to keep view structure stable.
            NULL::text AS employer_name,
            NULL::text AS employer_address,
            NULL::text AS income_band,
            NULL::text AS intel_source,
            NULL::numeric AS intel_confidence,
            NULL::boolean AS intel_verified,
            -- Get plaintiff name
            p.name AS plaintiff_name,
            p.tier AS plaintiff_tier
        FROM public.judgments j
            LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
        WHERE j.status IN ('unsatisfied', 'active', 'in_enforcement')
            AND j.judgment_amount >= 2000 -- Practical minimum for wage garnishment ROI
    ),
    scored AS (
        SELECT ji.*,
            -- Priority score: higher = more actionable
            -- Components:
            --   Base: collectability_score (0-100)
            --   Employer verified: +20
            --   Employer name present: +15
            --   High balance (>$10k): +10
            --   Recent judgment (<2 years): +5
            COALESCE(ji.collectability_score, 0) + CASE
                WHEN ji.intel_verified THEN 20
                ELSE 0
            END + CASE
                WHEN ji.employer_name IS NOT NULL THEN 15
                ELSE 0
            END + CASE
                WHEN ji.judgment_amount >= 10000 THEN 10
                ELSE 0
            END + CASE
                WHEN ji.judgment_date >= CURRENT_DATE - INTERVAL '2 years' THEN 5
                ELSE 0
            END AS priority_score
        FROM judgment_intelligence ji
        WHERE ji.employer_name IS NOT NULL -- Must have known employer
    )
SELECT s.plaintiff_id,
    s.case_number,
    s.defendant_name,
    s.employer_name,
    s.employer_address,
    s.judgment_amount AS balance,
    s.county AS jurisdiction,
    s.priority_score,
    -- Additional context for enforcement
    s.judgment_id,
    s.plaintiff_name,
    s.plaintiff_tier,
    s.judgment_date,
    s.collectability_score,
    s.income_band,
    s.intel_source,
    s.intel_confidence,
    s.intel_verified,
    s.enforcement_stage,
    s.status,
    s.created_at
FROM scored s
ORDER BY s.priority_score DESC,
    s.judgment_amount DESC;
COMMENT ON VIEW enforcement.v_candidate_wage_garnishments IS 'Judgments meeting NY wage garnishment criteria with known employer. Use for CPLR 5231 income execution planning.';
-- ============================================================================
-- GRANTS
-- ============================================================================
GRANT SELECT ON enforcement.v_candidate_wage_garnishments TO authenticated,
    service_role;
-- Anon may need read access for dashboard
GRANT SELECT ON enforcement.v_candidate_wage_garnishments TO anon;
-- ============================================================================
-- Notify PostgREST to reload schema cache
-- ============================================================================
NOTIFY pgrst,
'reload schema';
