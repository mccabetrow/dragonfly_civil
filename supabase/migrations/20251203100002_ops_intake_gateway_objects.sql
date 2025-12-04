-- ============================================================================
-- 0306b_ops_intake_gateway_objects.sql
-- OPS Intake Gateway: Tables, Views, Functions, and Policies
-- ============================================================================
-- NOTE: Enum additions are in 0306a_ops_intake_gateway_enums.sql
--       (separated to avoid PostgreSQL "unsafe use of new value" error)
--
-- PURPOSE:
--   Enables automated daily intake validation workflow where:
--   1. New candidate judgments are validated via AI
--   2. Validation results are stored for ops review
--   3. Dashboard shows intake queue for human verification
--
-- WORKFLOW:
--   n8n cron (10 AM) → fetch new_candidate → AI validate → store results
--   → notify ops → await human review → approve/reject
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- TABLE: public.intake_results
-- ============================================================================
-- Stores AI validation results for each new candidate judgment.
-- One row per validation run (supports re-validation if needed).
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.intake_results (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Link to the judgment being validated
    judgment_id uuid NOT NULL REFERENCES public.core_judgments(id) ON DELETE CASCADE,
    -- Validation metadata
    validated_at timestamptz NOT NULL DEFAULT now(),
    validation_source text NOT NULL DEFAULT 'n8n_intake_gateway',
    -- AI validation result
    result public.intake_validation_result NOT NULL,
    -- Individual check results (stored for audit/debugging)
    name_check_passed boolean,
    name_check_note text,
    address_check_passed boolean,
    address_check_note text,
    case_number_check_passed boolean,
    case_number_check_note text,
    -- Confidence score from AI (0-100)
    confidence_score integer CHECK (
        confidence_score BETWEEN 0 AND 100
    ),
    -- Raw AI response for debugging
    ai_response jsonb DEFAULT '{}'::jsonb,
    -- Human review fields
    reviewed_by uuid,
    -- auth.uid() of ops reviewer
    reviewed_at timestamptz,
    review_decision text,
    -- 'approved', 'rejected', 'flagged'
    review_notes text,
    -- Audit
    created_at timestamptz NOT NULL DEFAULT now()
);
-- Indexes
CREATE INDEX IF NOT EXISTS idx_intake_results_judgment_id ON public.intake_results(judgment_id);
CREATE INDEX IF NOT EXISTS idx_intake_results_result ON public.intake_results(result);
CREATE INDEX IF NOT EXISTS idx_intake_results_validated_at ON public.intake_results(validated_at DESC);
CREATE INDEX IF NOT EXISTS idx_intake_results_pending_review ON public.intake_results(result, reviewed_at)
WHERE reviewed_at IS NULL;
-- Comments
COMMENT ON TABLE public.intake_results IS 'AI validation results for new candidate judgments. Supports ops review workflow.';
COMMENT ON COLUMN public.intake_results.result IS 'Overall validation result: valid, invalid, or needs_review.';
COMMENT ON COLUMN public.intake_results.confidence_score IS 'AI confidence in the validation (0-100). Lower scores should default to needs_review.';
COMMENT ON COLUMN public.intake_results.reviewed_by IS 'Supabase auth user who reviewed this validation.';
COMMENT ON COLUMN public.intake_results.review_decision IS 'Human decision: approved, rejected, or flagged for further investigation.';
-- ============================================================================
-- VIEW: v_intake_queue
-- ============================================================================
-- Dashboard view for ops intake queue. Shows all cases awaiting review.
-- ============================================================================
CREATE OR REPLACE VIEW public.v_intake_queue AS
SELECT cj.id AS judgment_id,
    cj.case_index_number,
    cj.debtor_name,
    cj.original_creditor,
    cj.judgment_date,
    cj.principal_amount,
    cj.county,
    cj.status,
    cj.created_at AS imported_at,
    -- Latest validation result
    ir.id AS validation_id,
    ir.validated_at,
    ir.result AS validation_result,
    ir.confidence_score,
    ir.name_check_passed,
    ir.name_check_note,
    ir.address_check_passed,
    ir.address_check_note,
    ir.case_number_check_passed,
    ir.case_number_check_note,
    -- Review status
    ir.reviewed_by,
    ir.reviewed_at,
    ir.review_decision,
    ir.review_notes,
    -- Derived flags for dashboard
    CASE
        WHEN ir.reviewed_at IS NOT NULL THEN 'reviewed'
        WHEN ir.result = 'valid' THEN 'auto_valid'
        WHEN ir.result = 'invalid' THEN 'auto_invalid'
        ELSE 'pending_review'
    END AS queue_status,
    -- Priority score for sorting (higher = more urgent)
    CASE
        ir.result
        WHEN 'needs_review' THEN 100
        WHEN 'valid' THEN 50
        WHEN 'invalid' THEN 25
    END + COALESCE(ir.confidence_score, 50) AS review_priority
FROM public.core_judgments cj
    LEFT JOIN LATERAL (
        SELECT *
        FROM public.intake_results
        WHERE judgment_id = cj.id
        ORDER BY validated_at DESC
        LIMIT 1
    ) ir ON true
WHERE cj.status IN ('new_candidate', 'awaiting_ops_review')
ORDER BY CASE
        WHEN ir.reviewed_at IS NULL THEN 0
        ELSE 1
    END,
    CASE
        ir.result
        WHEN 'needs_review' THEN 1
        WHEN 'valid' THEN 2
        WHEN 'invalid' THEN 3
    END,
    cj.created_at DESC;
COMMENT ON VIEW public.v_intake_queue IS 'Dashboard view for ops intake queue. Shows new candidates and validation results for review.';
-- Make view accessible to dashboard (security invoker = false for RLS bypass)
ALTER VIEW public.v_intake_queue
SET (security_invoker = false);
-- ============================================================================
-- FUNCTION: fetch_new_candidates
-- ============================================================================
-- RPC for n8n to fetch judgments needing validation.
-- Returns new_candidate judgments that haven't been validated today.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.fetch_new_candidates(_limit integer DEFAULT 100) RETURNS TABLE (
        id uuid,
        case_index_number text,
        debtor_name text,
        original_creditor text,
        judgment_date date,
        principal_amount numeric,
        county text,
        court_name text,
        created_at timestamptz
    ) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$ BEGIN RETURN QUERY
SELECT cj.id,
    cj.case_index_number,
    cj.debtor_name,
    cj.original_creditor,
    cj.judgment_date,
    cj.principal_amount,
    cj.county,
    cj.court_name,
    cj.created_at
FROM public.core_judgments cj
WHERE cj.status = 'new_candidate'::public.judgment_status_enum
    AND NOT EXISTS (
        SELECT 1
        FROM public.intake_results ir
        WHERE ir.judgment_id = cj.id
            AND ir.validated_at > now() - INTERVAL '24 hours'
    )
ORDER BY cj.created_at ASC
LIMIT _limit;
END;
$$;
COMMENT ON FUNCTION public.fetch_new_candidates IS 'Fetch new_candidate judgments for AI validation. Excludes those validated in last 24h.';
-- Grants
REVOKE ALL ON FUNCTION public.fetch_new_candidates(integer)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.fetch_new_candidates(integer) TO service_role;
-- ============================================================================
-- FUNCTION: store_intake_validation
-- ============================================================================
-- RPC for n8n to store AI validation results.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.store_intake_validation(
        _judgment_id uuid,
        _result text,
        _confidence_score integer DEFAULT NULL,
        _name_check_passed boolean DEFAULT NULL,
        _name_check_note text DEFAULT NULL,
        _address_check_passed boolean DEFAULT NULL,
        _address_check_note text DEFAULT NULL,
        _case_number_check_passed boolean DEFAULT NULL,
        _case_number_check_note text DEFAULT NULL,
        _ai_response jsonb DEFAULT '{}'::jsonb
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _result_id uuid;
_result_enum public.intake_validation_result;
BEGIN -- Validate result
IF _result NOT IN ('valid', 'invalid', 'needs_review') THEN RAISE EXCEPTION 'Invalid result: %. Must be valid, invalid, or needs_review',
_result;
END IF;
_result_enum := _result::public.intake_validation_result;
-- Insert validation result
INSERT INTO public.intake_results (
        judgment_id,
        result,
        confidence_score,
        name_check_passed,
        name_check_note,
        address_check_passed,
        address_check_note,
        case_number_check_passed,
        case_number_check_note,
        ai_response
    )
VALUES (
        _judgment_id,
        _result_enum,
        _confidence_score,
        _name_check_passed,
        _name_check_note,
        _address_check_passed,
        _address_check_note,
        _case_number_check_passed,
        _case_number_check_note,
        COALESCE(_ai_response, '{}'::jsonb)
    )
RETURNING id INTO _result_id;
-- Update judgment status to awaiting_ops_review
UPDATE public.core_judgments
SET status = 'awaiting_ops_review'::public.judgment_status_enum,
    updated_at = now()
WHERE id = _judgment_id
    AND status = 'new_candidate'::public.judgment_status_enum;
RETURN _result_id;
END;
$$;
COMMENT ON FUNCTION public.store_intake_validation IS 'Store AI validation result for a judgment. Updates judgment status to awaiting_ops_review.';
-- Grants
REVOKE ALL ON FUNCTION public.store_intake_validation(
    uuid,
    text,
    integer,
    boolean,
    text,
    boolean,
    text,
    boolean,
    text,
    jsonb
)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.store_intake_validation(
        uuid,
        text,
        integer,
        boolean,
        text,
        boolean,
        text,
        boolean,
        text,
        jsonb
    ) TO service_role;
-- ============================================================================
-- FUNCTION: submit_intake_review
-- ============================================================================
-- RPC for dashboard to submit human review decision.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.submit_intake_review(
        _validation_id uuid,
        _decision text,
        _notes text DEFAULT NULL
    ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _judgment_id uuid;
_reviewer_id uuid;
_new_status public.judgment_status_enum;
BEGIN -- Validate decision
IF _decision NOT IN ('approved', 'rejected', 'flagged') THEN RAISE EXCEPTION 'Invalid decision: %. Must be approved, rejected, or flagged',
_decision;
END IF;
-- Get reviewer ID
BEGIN _reviewer_id := auth.uid();
EXCEPTION
WHEN OTHERS THEN _reviewer_id := NULL;
END;
-- Update intake_results with review
UPDATE public.intake_results
SET reviewed_by = _reviewer_id,
    reviewed_at = now(),
    review_decision = _decision,
    review_notes = _notes
WHERE id = _validation_id
RETURNING judgment_id INTO _judgment_id;
IF _judgment_id IS NULL THEN RAISE EXCEPTION 'Validation record not found: %',
_validation_id;
END IF;
-- Determine new judgment status based on decision
_new_status := CASE
    _decision
    WHEN 'approved' THEN 'ops_approved'::public.judgment_status_enum
    WHEN 'rejected' THEN 'ops_rejected'::public.judgment_status_enum
    WHEN 'flagged' THEN 'on_hold'::public.judgment_status_enum
END;
-- Update judgment status
UPDATE public.core_judgments
SET status = _new_status,
    updated_at = now()
WHERE id = _judgment_id;
RETURN true;
END;
$$;
COMMENT ON FUNCTION public.submit_intake_review IS 'Submit ops review decision for a validated intake. Updates judgment status accordingly.';
-- Grants
REVOKE ALL ON FUNCTION public.submit_intake_review(uuid, text, text)
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.submit_intake_review(uuid, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.submit_intake_review(uuid, text, text) TO authenticated;
-- ============================================================================
-- FUNCTION: get_intake_stats
-- ============================================================================
-- RPC for dashboard to get intake queue statistics.
-- ============================================================================
CREATE OR REPLACE FUNCTION public.get_intake_stats() RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _stats jsonb;
BEGIN
SELECT jsonb_build_object(
        'new_candidates',
        COUNT(*) FILTER (
            WHERE status = 'new_candidate'
        ),
        'awaiting_review',
        COUNT(*) FILTER (
            WHERE status = 'awaiting_ops_review'
        ),
        'approved_today',
        COUNT(*) FILTER (
            WHERE status = 'ops_approved'
                AND updated_at > now() - INTERVAL '24 hours'
        ),
        'rejected_today',
        COUNT(*) FILTER (
            WHERE status = 'ops_rejected'
                AND updated_at > now() - INTERVAL '24 hours'
        ),
        'validation_results',
        (
            SELECT jsonb_build_object(
                    'valid',
                    COUNT(*) FILTER (
                        WHERE result = 'valid'
                            AND validated_at > now() - INTERVAL '24 hours'
                    ),
                    'invalid',
                    COUNT(*) FILTER (
                        WHERE result = 'invalid'
                            AND validated_at > now() - INTERVAL '24 hours'
                    ),
                    'needs_review',
                    COUNT(*) FILTER (
                        WHERE result = 'needs_review'
                            AND validated_at > now() - INTERVAL '24 hours'
                    )
                )
            FROM public.intake_results
        ),
        'pending_human_review',
        (
            SELECT COUNT(*)
            FROM public.intake_results
            WHERE reviewed_at IS NULL
                AND validated_at > now() - INTERVAL '7 days'
        ),
        'generated_at',
        now()
    ) INTO _stats
FROM public.core_judgments;
RETURN _stats;
END;
$$;
COMMENT ON FUNCTION public.get_intake_stats IS 'Get intake queue statistics for dashboard display.';
-- Grants
REVOKE ALL ON FUNCTION public.get_intake_stats()
FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.get_intake_stats() TO service_role;
GRANT EXECUTE ON FUNCTION public.get_intake_stats() TO authenticated;
-- ============================================================================
-- RLS: intake_results
-- ============================================================================
ALTER TABLE public.intake_results ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.intake_results FORCE ROW LEVEL SECURITY;
-- Drop existing policies
DROP POLICY IF EXISTS intake_results_select_policy ON public.intake_results;
DROP POLICY IF EXISTS intake_results_insert_policy ON public.intake_results;
DROP POLICY IF EXISTS intake_results_update_policy ON public.intake_results;
-- SELECT: admin, ops, and service_role can read
CREATE POLICY intake_results_select_policy ON public.intake_results FOR
SELECT USING (
        public.dragonfly_is_admin()
        OR public.dragonfly_has_role('ops')
        OR auth.role() = 'service_role'
    );
-- INSERT: service_role only (n8n)
CREATE POLICY intake_results_insert_policy ON public.intake_results FOR
INSERT WITH CHECK (auth.role() = 'service_role');
-- UPDATE: admin, ops for review fields only
CREATE POLICY intake_results_update_policy ON public.intake_results FOR
UPDATE USING (
        public.dragonfly_is_admin()
        OR public.dragonfly_has_role('ops')
    ) WITH CHECK (
        public.dragonfly_is_admin()
        OR public.dragonfly_has_role('ops')
    );
-- ============================================================================
-- GRANTS
-- ============================================================================
GRANT SELECT ON public.intake_results TO authenticated;
GRANT SELECT ON public.intake_results TO service_role;
GRANT INSERT ON public.intake_results TO service_role;
GRANT UPDATE (
        reviewed_by,
        reviewed_at,
        review_decision,
        review_notes
    ) ON public.intake_results TO authenticated;
GRANT SELECT ON public.v_intake_queue TO authenticated;
GRANT SELECT ON public.v_intake_queue TO service_role;
-- ============================================================================
-- RELOAD POSTGREST
-- ============================================================================
SELECT public.pgrst_reload();
COMMIT;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================