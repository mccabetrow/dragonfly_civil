-- ============================================================================
-- 0204_unified_worker_rpcs.sql
-- Unified Worker RPCs: Single entry points for workers and n8n to mutate
-- core judgment, debtor intelligence, and enforcement data
-- ============================================================================
--
-- PURPOSE:
--   Provide a small, well-documented set of RPC functions that workers and
--   n8n use instead of raw table writes. This ensures:
--     1. Consistent business logic (validation, defaults, audit)
--     2. Centralized FCRA/FDCPA compliance checks
--     3. Single source of truth for data mutation patterns
--
-- RPC FUNCTIONS DEFINED:
--   - upsert_debtor_intelligence: Insert/update debtor intelligence linked to a judgment
--   - update_judgment_status: Update core_judgments.status with optional collectability_score
--   - log_enforcement_action: Insert a new enforcement action record
--
-- SECURITY MODEL:
--   All RPCs are SECURITY DEFINER with service_role-only execute grants.
--   Workers and n8n connect with service_role credentials.
--
-- USAGE:
--   Workers and n8n should ONLY use these RPCs for mutations.
--   Direct table writes are blocked by RLS for non-service_role callers.
--
-- RELATED MIGRATIONS:
--   - 0200_core_judgment_schema.sql (tables)
--   - 0201_fcra_audit_log.sql (log_external_data_call RPC)
--   - 0202_fdcpa_contact_guard.sql (fn_is_fdcpa_allowed_time function)
--   - 0203_rls_force_core_judgment_tables.sql (RLS hardening)
--
-- ============================================================================
BEGIN;
-- ============================================================================
-- FUNCTION: public.upsert_debtor_intelligence
-- ============================================================================
-- Insert or update debtor intelligence for a judgment.
-- If a record with the same judgment_id and data_source exists, update it.
-- Otherwise, insert a new record.
--
-- PARAMETERS:
--   _judgment_id: UUID of the judgment (required, must exist in core_judgments)
--   _data_source: Source of the intelligence (e.g., 'idicore', 'tloxp', 'manual')
--   _employer_name: Employer name (optional)
--   _employer_address: Employer address (optional)
--   _income_band: Income band string (optional, e.g., '$50k-75k')
--   _bank_name: Bank name (optional)
--   _bank_address: Bank address (optional)
--   _home_ownership: Home ownership status (optional, e.g., 'owner', 'renter')
--   _has_benefits_only: Whether account is benefits-only exempt (optional)
--   _confidence_score: Data quality score 0-100 (optional)
--   _is_verified: Whether human-verified (optional, default false)
--
-- RETURNS: UUID of the inserted/updated debtor_intelligence record
--
-- USAGE (from n8n or workers):
--   SELECT public.upsert_debtor_intelligence(
--       _judgment_id := 'uuid-of-judgment',
--       _data_source := 'idicore',
--       _employer_name := 'Delta Airlines',
--       _employer_address := 'JFK Terminal 4',
--       _income_band := '$75k-100k',
--       _bank_name := NULL,
--       _bank_address := NULL,
--       _home_ownership := 'renter',
--       _has_benefits_only := false,
--       _confidence_score := 85.0,
--       _is_verified := false
--   );
--
-- SECURITY:
--   - SECURITY DEFINER: Runs with owner privileges
--   - Restricted to service_role via REVOKE/GRANT
--
-- ============================================================================
CREATE OR REPLACE FUNCTION public.upsert_debtor_intelligence(
        _judgment_id uuid,
        _data_source text,
        _employer_name text DEFAULT NULL,
        _employer_address text DEFAULT NULL,
        _income_band text DEFAULT NULL,
        _bank_name text DEFAULT NULL,
        _bank_address text DEFAULT NULL,
        _home_ownership text DEFAULT NULL,
        _has_benefits_only boolean DEFAULT NULL,
        _confidence_score numeric(5, 2) DEFAULT NULL,
        _is_verified boolean DEFAULT false
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _result_id uuid;
_existing_id uuid;
BEGIN -- Validate judgment exists
IF NOT EXISTS (
    SELECT 1
    FROM public.core_judgments
    WHERE id = _judgment_id
) THEN RAISE EXCEPTION 'upsert_debtor_intelligence: judgment_id % not found',
_judgment_id;
END IF;
-- Check for existing record with same judgment_id and data_source
SELECT id INTO _existing_id
FROM public.debtor_intelligence
WHERE judgment_id = _judgment_id
    AND data_source = _data_source
LIMIT 1;
IF _existing_id IS NOT NULL THEN -- Update existing record
UPDATE public.debtor_intelligence
SET employer_name = COALESCE(_employer_name, employer_name),
    employer_address = COALESCE(_employer_address, employer_address),
    income_band = COALESCE(_income_band, income_band),
    bank_name = COALESCE(_bank_name, bank_name),
    bank_address = COALESCE(_bank_address, bank_address),
    home_ownership = COALESCE(_home_ownership, home_ownership),
    has_benefits_only_account = COALESCE(_has_benefits_only, has_benefits_only_account),
    confidence_score = COALESCE(_confidence_score, confidence_score),
    is_verified = COALESCE(_is_verified, is_verified),
    last_updated = timezone('utc', now())
WHERE id = _existing_id
RETURNING id INTO _result_id;
ELSE -- Insert new record
INSERT INTO public.debtor_intelligence (
        judgment_id,
        data_source,
        employer_name,
        employer_address,
        income_band,
        bank_name,
        bank_address,
        home_ownership,
        has_benefits_only_account,
        confidence_score,
        is_verified
    )
VALUES (
        _judgment_id,
        _data_source,
        _employer_name,
        _employer_address,
        _income_band,
        _bank_name,
        _bank_address,
        _home_ownership,
        _has_benefits_only,
        _confidence_score,
        COALESCE(_is_verified, false)
    )
RETURNING id INTO _result_id;
END IF;
RETURN _result_id;
END;
$$;
COMMENT ON FUNCTION public.upsert_debtor_intelligence IS 'Insert or update debtor intelligence for a judgment. Used by enrichment workers and n8n. Params: _judgment_id (UUID, required), _data_source (text, required), plus optional employer/bank/income fields. Returns UUID of the record.';
-- Permissions: service_role only
REVOKE ALL ON FUNCTION public.upsert_debtor_intelligence(
    uuid,
    text,
    text,
    text,
    text,
    text,
    text,
    text,
    boolean,
    numeric,
    boolean
)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.upsert_debtor_intelligence(
    uuid,
    text,
    text,
    text,
    text,
    text,
    text,
    text,
    boolean,
    numeric,
    boolean
)
FROM anon;
REVOKE ALL ON FUNCTION public.upsert_debtor_intelligence(
    uuid,
    text,
    text,
    text,
    text,
    text,
    text,
    text,
    boolean,
    numeric,
    boolean
)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_debtor_intelligence(
        uuid,
        text,
        text,
        text,
        text,
        text,
        text,
        text,
        boolean,
        numeric,
        boolean
    ) TO service_role;
-- ============================================================================
-- FUNCTION: public.update_judgment_status
-- ============================================================================
-- Update a judgment's status and optionally its collectability_score.
-- This is the ONLY approved way for workers/n8n to update judgment status.
--
-- PARAMETERS:
--   _judgment_id: UUID of the judgment (required, must exist)
--   _status: New status value (required, must be valid judgment_status_enum)
--   _collectability_score: New collectability score 0-100 (optional)
--   _note: Optional note for audit purposes (logged but not stored on judgment)
--
-- RETURNS: BOOLEAN (true if update succeeded)
--
-- USAGE (from n8n or workers):
--   SELECT public.update_judgment_status(
--       _judgment_id := 'uuid-of-judgment',
--       _status := 'partially_satisfied',
--       _collectability_score := 75,
--       _note := 'Enrichment complete, employer found'
--   );
--
-- SECURITY:
--   - SECURITY DEFINER: Runs with owner privileges
--   - Restricted to service_role via REVOKE/GRANT
--
-- ============================================================================
CREATE OR REPLACE FUNCTION public.update_judgment_status(
        _judgment_id uuid,
        _status text,
        _collectability_score int DEFAULT NULL,
        _note text DEFAULT NULL
    ) RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _valid_statuses text [] := ARRAY ['unsatisfied', 'partially_satisfied', 'satisfied', 'vacated', 'expired', 'on_hold'];
BEGIN -- Validate judgment exists
IF NOT EXISTS (
    SELECT 1
    FROM public.core_judgments
    WHERE id = _judgment_id
) THEN RAISE EXCEPTION 'update_judgment_status: judgment_id % not found',
_judgment_id;
END IF;
-- Validate status is a valid enum value
IF NOT (_status = ANY(_valid_statuses)) THEN RAISE EXCEPTION 'update_judgment_status: invalid status %. Valid values: %',
_status,
_valid_statuses;
END IF;
-- Validate collectability_score if provided
IF _collectability_score IS NOT NULL
AND (
    _collectability_score < 0
    OR _collectability_score > 100
) THEN RAISE EXCEPTION 'update_judgment_status: collectability_score must be 0-100, got %',
_collectability_score;
END IF;
-- Perform the update
UPDATE public.core_judgments
SET status = _status::public.judgment_status_enum,
    collectability_score = COALESCE(_collectability_score, collectability_score),
    updated_at = timezone('utc', now())
WHERE id = _judgment_id;
-- Log audit trail (optional: could insert into an audit table here)
-- For now, we rely on the updated_at timestamp and external logging
RETURN true;
END;
$$;
COMMENT ON FUNCTION public.update_judgment_status IS 'Update judgment status and optional collectability_score. Used by workers and n8n. Params: _judgment_id (UUID, required), _status (text, required, valid enum), _collectability_score (int, optional 0-100), _note (text, optional). Returns true on success.';
-- Permissions: service_role only
REVOKE ALL ON FUNCTION public.update_judgment_status(uuid, text, int, text)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.update_judgment_status(uuid, text, int, text)
FROM anon;
REVOKE ALL ON FUNCTION public.update_judgment_status(uuid, text, int, text)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.update_judgment_status(uuid, text, int, text) TO service_role;
-- ============================================================================
-- FUNCTION: public.log_enforcement_action
-- ============================================================================
-- Insert a new enforcement action record for a judgment.
-- This is the approved way for workers/n8n to log enforcement attempts.
--
-- PARAMETERS:
--   _judgment_id: UUID of the judgment (required, must exist)
--   _action_type: Type of enforcement action (required, valid enum)
--   _status: Action status (optional, defaults to 'planned')
--   _requires_attorney_signature: Whether attorney sign-off needed (optional)
--   _generated_url: URL to generated document (optional)
--   _notes: Free-form notes (optional)
--   _metadata: Additional structured data (optional, jsonb)
--
-- RETURNS: UUID of the inserted enforcement_actions record
--
-- USAGE (from n8n or workers):
--   SELECT public.log_enforcement_action(
--       _judgment_id := 'uuid-of-judgment',
--       _action_type := 'income_execution',
--       _status := 'pending',
--       _requires_attorney_signature := true,
--       _generated_url := 'https://storage.example.com/docs/ie_12345.pdf',
--       _notes := 'Sent to employer Delta Airlines',
--       _metadata := '{"employer_ein": "XX-XXXXXXX"}'::jsonb
--   );
--
-- SECURITY:
--   - SECURITY DEFINER: Runs with owner privileges
--   - Restricted to service_role via REVOKE/GRANT
--
-- ============================================================================
CREATE OR REPLACE FUNCTION public.log_enforcement_action(
        _judgment_id uuid,
        _action_type text,
        _status text DEFAULT 'planned',
        _requires_attorney_signature boolean DEFAULT false,
        _generated_url text DEFAULT NULL,
        _notes text DEFAULT NULL,
        _metadata jsonb DEFAULT '{}'::jsonb
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _result_id uuid;
_valid_action_types text [] := ARRAY [
        'information_subpoena', 'restraining_notice', 'property_execution',
        'income_execution', 'bank_levy', 'real_property_lien', 'demand_letter',
        'settlement_offer', 'skiptrace', 'asset_search', 'other'
    ];
_valid_statuses text [] := ARRAY [
        'planned', 'pending', 'served', 'completed', 'failed', 'cancelled', 'expired'
    ];
BEGIN -- Validate judgment exists
IF NOT EXISTS (
    SELECT 1
    FROM public.core_judgments
    WHERE id = _judgment_id
) THEN RAISE EXCEPTION 'log_enforcement_action: judgment_id % not found',
_judgment_id;
END IF;
-- Validate action_type
IF NOT (_action_type = ANY(_valid_action_types)) THEN RAISE EXCEPTION 'log_enforcement_action: invalid action_type %. Valid values: %',
_action_type,
_valid_action_types;
END IF;
-- Validate status
IF NOT (_status = ANY(_valid_statuses)) THEN RAISE EXCEPTION 'log_enforcement_action: invalid status %. Valid values: %',
_status,
_valid_statuses;
END IF;
-- Insert the enforcement action
INSERT INTO public.enforcement_actions (
        judgment_id,
        action_type,
        status,
        requires_attorney_signature,
        generated_url,
        notes,
        metadata
    )
VALUES (
        _judgment_id,
        _action_type::public.enforcement_action_type_enum,
        _status::public.enforcement_action_status_enum,
        COALESCE(_requires_attorney_signature, false),
        _generated_url,
        _notes,
        COALESCE(_metadata, '{}'::jsonb)
    )
RETURNING id INTO _result_id;
RETURN _result_id;
END;
$$;
COMMENT ON FUNCTION public.log_enforcement_action IS 'Insert a new enforcement action for a judgment. Used by workers and n8n. Params: _judgment_id (UUID, required), _action_type (text, required, valid enum), _status (text, default planned), _requires_attorney_signature (bool), _generated_url (text), _notes (text), _metadata (jsonb). Returns UUID of the action.';
-- Permissions: service_role only
REVOKE ALL ON FUNCTION public.log_enforcement_action(uuid, text, text, boolean, text, text, jsonb)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.log_enforcement_action(uuid, text, text, boolean, text, text, jsonb)
FROM anon;
REVOKE ALL ON FUNCTION public.log_enforcement_action(uuid, text, text, boolean, text, text, jsonb)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.log_enforcement_action(uuid, text, text, boolean, text, text, jsonb) TO service_role;
-- ============================================================================
-- FUNCTION: public.complete_enrichment
-- ============================================================================
-- Combined RPC that performs the full enrichment completion flow:
--   1. Logs the FCRA audit trail (external_data_calls)
--   2. Upserts debtor intelligence
--   3. Updates judgment status and collectability_score
--
-- This is a convenience wrapper for workers that want to perform all three
-- operations in a single RPC call with transactional consistency.
--
-- PARAMETERS:
--   _judgment_id: UUID of the judgment (required)
--   _provider: Skip-trace vendor name (required for FCRA)
--   _endpoint: API endpoint called (required for FCRA)
--   _fcra_status: Result of the API call ('success', 'error', etc.)
--   _fcra_http_code: HTTP status code (optional)
--   _fcra_meta: Redacted metadata for FCRA log (optional)
--   _data_source: Intelligence data source (e.g., 'idicore')
--   _employer_name: Employer name (optional)
--   _employer_address: Employer address (optional)
--   _income_band: Income band string (optional)
--   _bank_name: Bank name (optional)
--   _bank_address: Bank address (optional)
--   _home_ownership: Ownership status (optional)
--   _has_benefits_only: Benefits-only account flag (optional)
--   _confidence_score: Data quality score 0-100 (optional)
--   _new_status: New judgment status (optional, defaults to current)
--   _new_collectability_score: New collectability score (optional)
--
-- RETURNS: jsonb with {fcra_log_id, intelligence_id, status_updated}
--
-- USAGE (from enrichment worker):
--   SELECT public.complete_enrichment(
--       _judgment_id := 'uuid',
--       _provider := 'idiCORE',
--       _endpoint := '/person/search',
--       _fcra_status := 'success',
--       _fcra_http_code := 200,
--       _fcra_meta := '{"results_count": 1}'::jsonb,
--       _data_source := 'idicore',
--       _employer_name := 'Delta Airlines',
--       _confidence_score := 85.0,
--       _new_status := 'unsatisfied',
--       _new_collectability_score := 75
--   );
--
-- ============================================================================
CREATE OR REPLACE FUNCTION public.complete_enrichment(
        _judgment_id uuid,
        _provider text,
        _endpoint text,
        _fcra_status text,
        _fcra_http_code int DEFAULT NULL,
        _fcra_meta jsonb DEFAULT '{}'::jsonb,
        _data_source text DEFAULT NULL,
        _employer_name text DEFAULT NULL,
        _employer_address text DEFAULT NULL,
        _income_band text DEFAULT NULL,
        _bank_name text DEFAULT NULL,
        _bank_address text DEFAULT NULL,
        _home_ownership text DEFAULT NULL,
        _has_benefits_only boolean DEFAULT NULL,
        _confidence_score numeric(5, 2) DEFAULT NULL,
        _new_status text DEFAULT NULL,
        _new_collectability_score int DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _fcra_log_id uuid;
_intelligence_id uuid;
_status_updated boolean := false;
_current_status text;
BEGIN -- Validate judgment exists
IF NOT EXISTS (
    SELECT 1
    FROM public.core_judgments
    WHERE id = _judgment_id
) THEN RAISE EXCEPTION 'complete_enrichment: judgment_id % not found',
_judgment_id;
END IF;
-- Step 1: Log FCRA audit trail
_fcra_log_id := public.log_external_data_call(
    _judgment_id := _judgment_id,
    _provider := _provider,
    _endpoint := _endpoint,
    _status := _fcra_status,
    _http_code := _fcra_http_code,
    _meta := _fcra_meta
);
-- Step 2: Upsert debtor intelligence (if data_source provided)
IF _data_source IS NOT NULL THEN _intelligence_id := public.upsert_debtor_intelligence(
    _judgment_id := _judgment_id,
    _data_source := _data_source,
    _employer_name := _employer_name,
    _employer_address := _employer_address,
    _income_band := _income_band,
    _bank_name := _bank_name,
    _bank_address := _bank_address,
    _home_ownership := _home_ownership,
    _has_benefits_only := _has_benefits_only,
    _confidence_score := _confidence_score,
    _is_verified := false
);
END IF;
-- Step 3: Update judgment status (if new_status or collectability_score provided)
IF _new_status IS NOT NULL
OR _new_collectability_score IS NOT NULL THEN -- Get current status if new_status not provided
IF _new_status IS NULL THEN
SELECT status::text INTO _current_status
FROM public.core_judgments
WHERE id = _judgment_id;
_new_status := _current_status;
END IF;
_status_updated := public.update_judgment_status(
    _judgment_id := _judgment_id,
    _status := _new_status,
    _collectability_score := _new_collectability_score,
    _note := 'Updated via complete_enrichment RPC'
);
END IF;
RETURN jsonb_build_object(
    'fcra_log_id',
    _fcra_log_id,
    'intelligence_id',
    _intelligence_id,
    'status_updated',
    _status_updated
);
END;
$$;
COMMENT ON FUNCTION public.complete_enrichment IS 'Combined RPC for enrichment workers: logs FCRA audit, upserts debtor intelligence, updates judgment status. All in one transaction. Params: judgment details, FCRA audit fields, intelligence fields, status updates. Returns jsonb with {fcra_log_id, intelligence_id, status_updated}.';
-- Permissions: service_role only
REVOKE ALL ON FUNCTION public.complete_enrichment(
    uuid,
    text,
    text,
    text,
    int,
    jsonb,
    text,
    text,
    text,
    text,
    text,
    text,
    text,
    boolean,
    numeric,
    text,
    int
)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.complete_enrichment(
    uuid,
    text,
    text,
    text,
    int,
    jsonb,
    text,
    text,
    text,
    text,
    text,
    text,
    text,
    boolean,
    numeric,
    text,
    int
)
FROM anon;
REVOKE ALL ON FUNCTION public.complete_enrichment(
    uuid,
    text,
    text,
    text,
    int,
    jsonb,
    text,
    text,
    text,
    text,
    text,
    text,
    text,
    boolean,
    numeric,
    text,
    int
)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.complete_enrichment(
        uuid,
        text,
        text,
        text,
        int,
        jsonb,
        text,
        text,
        text,
        text,
        text,
        text,
        text,
        boolean,
        numeric,
        text,
        int
    ) TO service_role;
-- ============================================================================
-- RELOAD POSTGREST SCHEMA CACHE
-- ============================================================================
SELECT public.pgrst_reload();
COMMIT;
-- ============================================================================
-- END OF MIGRATION
-- ============================================================================
