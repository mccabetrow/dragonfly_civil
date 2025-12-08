-- ============================================================================
-- Migration: Collectability Scores Analytics View
-- ============================================================================
-- Creates analytics.v_collectability_scores for scoring judgments based on
-- available data signals. Designed for future ML model swap.
--
-- SCORING MODEL (v1 - Rule-Based)
-- ================================
-- Total Score: 0-100 points
--
-- COMPONENT WEIGHTS:
--   1. Amount Factor (0-25 pts) - Higher amounts = more incentive to collect
--   2. Age Factor (0-20 pts) - Fresher judgments = better recovery odds
--   3. Intel Factor (0-25 pts) - Employment/bank intel = actionable pathways
--   4. Tier Factor (0-15 pts) - Existing tier classification signal
--   5. County Factor (0-10 pts) - NY metro counties = better enforcement infra
--   6. Status Factor (0-5 pts) - Active enforcement = momentum bonus
--
-- RISK BANDS:
--   A (80-100): High confidence - prioritize for immediate enforcement
--   B (60-79):  Medium confidence - standard workflow
--   C (40-59):  Lower confidence - enrichment recommended
--   D (0-39):   Low confidence - hold for additional research
--
-- FUTURE ML INTEGRATION:
--   - This view's score_* subqueries can be replaced with ml.predict_score()
--   - The factors JSON captures feature inputs for model training
--   - score_version column tracks which model produced the score
-- ============================================================================
-- Ensure analytics schema exists
CREATE SCHEMA IF NOT EXISTS analytics;
GRANT USAGE ON SCHEMA analytics TO authenticated,
    service_role;
-- ============================================================================
-- VIEW: analytics.v_collectability_scores
-- ============================================================================
CREATE OR REPLACE VIEW analytics.v_collectability_scores AS WITH base_data AS (
        -- Gather all source data in one place
        SELECT j.id AS judgment_id,
            j.plaintiff_id,
            j.case_number,
            j.judgment_amount,
            j.judgment_date,
            j.status,
            j.enforcement_stage,
            j.collectability_score AS existing_score,
            j.county,
            j.created_at,
            -- Plaintiff tier
            p.tier AS plaintiff_tier,
            p.name AS plaintiff_name,
            -- Calculate age
            CASE
                WHEN j.judgment_date IS NOT NULL THEN EXTRACT(
                    DAYS
                    FROM (CURRENT_DATE - j.judgment_date)
                )::int
                ELSE NULL
            END AS age_days,
            -- Employment intel
            di.employer_name,
            di.employer_address,
            di.income_band,
            di.bank_name,
            di.bank_address,
            di.home_ownership,
            di.is_verified AS intel_verified,
            di.confidence_score AS intel_confidence
        FROM public.judgments j
            LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
            LEFT JOIN public.debtor_intelligence di ON di.judgment_id = j.id::uuid
        WHERE j.status NOT IN ('satisfied', 'vacated', 'expired', 'closed')
    ),
    -- COMPONENT 1: Amount Factor (0-25 points)
    -- Higher judgment amounts = more incentive to pursue
    score_amount AS (
        SELECT judgment_id,
            CASE
                WHEN judgment_amount >= 50000 THEN 25
                WHEN judgment_amount >= 25000 THEN 22
                WHEN judgment_amount >= 10000 THEN 18
                WHEN judgment_amount >= 5000 THEN 14
                WHEN judgment_amount >= 2000 THEN 10
                WHEN judgment_amount >= 1000 THEN 5
                ELSE 2
            END AS amount_score,
            judgment_amount AS amount_value
        FROM base_data
    ),
    -- COMPONENT 2: Age Factor (0-20 points)
    -- Fresher judgments have better recovery rates
    score_age AS (
        SELECT judgment_id,
            CASE
                WHEN age_days IS NULL THEN 5 -- Unknown = neutral
                WHEN age_days <= 365 THEN 20 -- < 1 year = excellent
                WHEN age_days <= 730 THEN 16 -- 1-2 years = good
                WHEN age_days <= 1095 THEN 12 -- 2-3 years = fair
                WHEN age_days <= 1825 THEN 8 -- 3-5 years = declining
                WHEN age_days <= 3650 THEN 4 -- 5-10 years = poor
                ELSE 1 -- 10+ years = minimal
            END AS age_score,
            age_days AS age_value
        FROM base_data
    ),
    -- COMPONENT 3: Intel Factor (0-25 points)
    -- Known employer/bank = actionable enforcement pathways
    score_intel AS (
        SELECT judgment_id,
            -- Base intel score
            (
                CASE
                    WHEN employer_name IS NOT NULL THEN 10
                    ELSE 0
                END + CASE
                    WHEN bank_name IS NOT NULL THEN 8
                    ELSE 0
                END + CASE
                    WHEN income_band IS NOT NULL THEN 4
                    ELSE 0
                END + CASE
                    WHEN home_ownership = 'owner' THEN 3
                    ELSE 0
                END + CASE
                    WHEN intel_verified THEN 5
                    ELSE 0
                END
            )::int AS intel_raw,
            LEAST(
                25,
                (
                    CASE
                        WHEN employer_name IS NOT NULL THEN 10
                        ELSE 0
                    END + CASE
                        WHEN bank_name IS NOT NULL THEN 8
                        ELSE 0
                    END + CASE
                        WHEN income_band IS NOT NULL THEN 4
                        ELSE 0
                    END + CASE
                        WHEN home_ownership = 'owner' THEN 3
                        ELSE 0
                    END + CASE
                        WHEN intel_verified THEN 5
                        ELSE 0
                    END
                )
            )::int AS intel_score,
            -- Feature flags for JSON
            employer_name IS NOT NULL AS has_employer,
            bank_name IS NOT NULL AS has_bank,
            income_band IS NOT NULL AS has_income_band,
            home_ownership = 'owner' AS is_homeowner,
            COALESCE(intel_verified, false) AS is_verified
        FROM base_data
    ),
    -- COMPONENT 4: Tier Factor (0-15 points)
    -- Existing tier classification as signal
    score_tier AS (
        SELECT judgment_id,
            CASE
                upper(COALESCE(plaintiff_tier, ''))
                WHEN 'A' THEN 15
                WHEN 'B' THEN 10
                WHEN 'C' THEN 5
                ELSE 3 -- Unknown tier
            END AS tier_score,
            COALESCE(plaintiff_tier, 'unknown') AS tier_value
        FROM base_data
    ),
    -- COMPONENT 5: County Factor (0-10 points)
    -- NY metro counties have better enforcement infrastructure
    score_county AS (
        SELECT judgment_id,
            CASE
                upper(COALESCE(county, '')) -- NYC counties (best enforcement)
                WHEN 'NEW YORK' THEN 10
                WHEN 'KINGS' THEN 10
                WHEN 'QUEENS' THEN 10
                WHEN 'BRONX' THEN 9
                WHEN 'RICHMOND' THEN 9 -- Long Island (good)
                WHEN 'NASSAU' THEN 8
                WHEN 'SUFFOLK' THEN 7 -- Hudson Valley (fair)
                WHEN 'WESTCHESTER' THEN 7
                WHEN 'ROCKLAND' THEN 6 -- Other NY counties (baseline)
                ELSE 4
            END AS county_score,
            COALESCE(county, 'unknown') AS county_value
        FROM base_data
    ),
    -- COMPONENT 6: Status Factor (0-5 points)
    -- Active enforcement = momentum bonus
    score_status AS (
        SELECT judgment_id,
            CASE
                WHEN enforcement_stage IN ('levy_issued', 'garnishment_active') THEN 5
                WHEN enforcement_stage IN ('payment_plan', 'waiting_payment') THEN 4
                WHEN enforcement_stage IN ('paperwork_filed') THEN 3
                WHEN enforcement_stage IN ('pre_enforcement') THEN 2
                ELSE 1
            END AS status_score,
            COALESCE(enforcement_stage, 'none') AS status_value
        FROM base_data
    ),
    -- COMBINE ALL SCORES
    combined AS (
        SELECT bd.judgment_id,
            bd.plaintiff_id,
            bd.case_number,
            bd.plaintiff_name,
            bd.judgment_amount,
            bd.judgment_date,
            bd.age_days,
            bd.county,
            bd.status,
            bd.enforcement_stage,
            bd.existing_score,
            bd.employer_name,
            bd.bank_name,
            bd.created_at,
            -- Component scores
            COALESCE(sa.amount_score, 0) AS amount_score,
            COALESCE(sag.age_score, 0) AS age_score,
            COALESCE(si.intel_score, 0) AS intel_score,
            COALESCE(st.tier_score, 0) AS tier_score,
            COALESCE(sc.county_score, 0) AS county_score,
            COALESCE(ss.status_score, 0) AS status_score,
            -- Intel flags
            COALESCE(si.has_employer, false) AS has_employer,
            COALESCE(si.has_bank, false) AS has_bank,
            COALESCE(si.is_homeowner, false) AS is_homeowner,
            COALESCE(si.is_verified, false) AS intel_verified,
            -- Tier value
            st.tier_value AS plaintiff_tier
        FROM base_data bd
            LEFT JOIN score_amount sa ON sa.judgment_id = bd.judgment_id
            LEFT JOIN score_age sag ON sag.judgment_id = bd.judgment_id
            LEFT JOIN score_intel si ON si.judgment_id = bd.judgment_id
            LEFT JOIN score_tier st ON st.judgment_id = bd.judgment_id
            LEFT JOIN score_county sc ON sc.judgment_id = bd.judgment_id
            LEFT JOIN score_status ss ON ss.judgment_id = bd.judgment_id
    )
SELECT c.plaintiff_id,
    c.case_number,
    c.plaintiff_name,
    -- Total score (0-100)
    (
        c.amount_score + c.age_score + c.intel_score + c.tier_score + c.county_score + c.status_score
    )::int AS score,
    -- Risk band classification
    CASE
        WHEN (
            c.amount_score + c.age_score + c.intel_score + c.tier_score + c.county_score + c.status_score
        ) >= 80 THEN 'A'
        WHEN (
            c.amount_score + c.age_score + c.intel_score + c.tier_score + c.county_score + c.status_score
        ) >= 60 THEN 'B'
        WHEN (
            c.amount_score + c.age_score + c.intel_score + c.tier_score + c.county_score + c.status_score
        ) >= 40 THEN 'C'
        ELSE 'D'
    END AS risk_band,
    -- Factors JSON (for ML training + explainability)
    jsonb_build_object(
        'score_version',
        'v1_rule_based',
        'computed_at',
        timezone('utc', now()),
        'components',
        jsonb_build_object(
            'amount',
            jsonb_build_object(
                'score',
                c.amount_score,
                'max',
                25,
                'value',
                c.judgment_amount
            ),
            'age',
            jsonb_build_object(
                'score',
                c.age_score,
                'max',
                20,
                'value',
                c.age_days
            ),
            'intel',
            jsonb_build_object(
                'score',
                c.intel_score,
                'max',
                25,
                'has_employer',
                c.has_employer,
                'has_bank',
                c.has_bank,
                'is_homeowner',
                c.is_homeowner,
                'is_verified',
                c.intel_verified
            ),
            'tier',
            jsonb_build_object(
                'score',
                c.tier_score,
                'max',
                15,
                'value',
                c.plaintiff_tier
            ),
            'county',
            jsonb_build_object(
                'score',
                c.county_score,
                'max',
                10,
                'value',
                c.county
            ),
            'status',
            jsonb_build_object(
                'score',
                c.status_score,
                'max',
                5,
                'value',
                c.enforcement_stage
            )
        ),
        'features',
        jsonb_build_object(
            'judgment_amount',
            c.judgment_amount,
            'age_days',
            c.age_days,
            'county',
            c.county,
            'plaintiff_tier',
            c.plaintiff_tier,
            'enforcement_stage',
            c.enforcement_stage,
            'has_employer',
            c.has_employer,
            'has_bank',
            c.has_bank,
            'is_homeowner',
            c.is_homeowner,
            'intel_verified',
            c.intel_verified
        )
    ) AS factors,
    -- Additional context
    c.judgment_id,
    c.judgment_amount,
    c.judgment_date,
    c.age_days,
    c.county,
    c.enforcement_stage,
    c.employer_name,
    c.bank_name,
    c.existing_score,
    c.created_at
FROM combined c
ORDER BY (
        c.amount_score + c.age_score + c.intel_score + c.tier_score + c.county_score + c.status_score
    ) DESC,
    c.judgment_amount DESC;
COMMENT ON VIEW analytics.v_collectability_scores IS 'Judgment collectability scoring (v1 rule-based). ' 'Outputs: plaintiff_id, case_number, score, risk_band, factors JSON. ' 'Designed for future ML model integration via score_version.';
-- ============================================================================
-- GRANTS
-- ============================================================================
GRANT SELECT ON analytics.v_collectability_scores TO authenticated,
    service_role;
-- Anon may need read access for dashboard
GRANT SELECT ON analytics.v_collectability_scores TO anon;
-- ============================================================================
-- Notify PostgREST to reload schema cache
-- ============================================================================
NOTIFY pgrst,
'reload schema';