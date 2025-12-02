-- Migration: Add update_enforcement_action_status RPC
-- Purpose: Allow updating the status of an existing enforcement action
-- Used by: Mom's Enforcement Console "Signed & Sent" button
BEGIN;
-- ============================================================================
-- FUNCTION: public.update_enforcement_action_status
-- ============================================================================
-- Updates the status and notes of an existing enforcement action.
-- Used when Mom marks a document as "Signed & Sent" in the console.
--
-- Usage:
--   SELECT public.update_enforcement_action_status(
--       _action_id := 'uuid-here',
--       _status := 'completed',
--       _notes := 'Signed and sent by attorney'
--   );
-- ============================================================================
CREATE OR REPLACE FUNCTION public.update_enforcement_action_status(
        _action_id uuid,
        _status text,
        _notes text DEFAULT NULL
    ) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
    pg_temp AS $$
DECLARE _result jsonb;
_valid_statuses text [] := ARRAY [
        'planned', 'pending', 'served', 'completed', 'failed', 'cancelled', 'expired'
    ];
BEGIN -- Validate status
IF NOT (_status = ANY(_valid_statuses)) THEN RAISE EXCEPTION 'update_enforcement_action_status: invalid status %. Valid values: %',
_status,
_valid_statuses;
END IF;
-- Update the action
UPDATE public.enforcement_actions
SET status = _status::public.enforcement_action_status_enum,
    notes = COALESCE(_notes, notes),
    updated_at = NOW()
WHERE id = _action_id
RETURNING jsonb_build_object(
        'action_id',
        id,
        'judgment_id',
        judgment_id,
        'action_type',
        action_type,
        'status',
        status,
        'updated_at',
        updated_at
    ) INTO _result;
IF _result IS NULL THEN RAISE EXCEPTION 'update_enforcement_action_status: action_id % not found',
_action_id;
END IF;
RETURN _result;
END;
$$;
COMMENT ON FUNCTION public.update_enforcement_action_status IS 'Update the status and notes of an existing enforcement action. Used by Mom Console to mark documents as signed.';
-- Permissions: service_role only (frontend calls through backend API)
REVOKE ALL ON FUNCTION public.update_enforcement_action_status(uuid, text, text)
FROM PUBLIC;
REVOKE ALL ON FUNCTION public.update_enforcement_action_status(uuid, text, text)
FROM anon;
REVOKE ALL ON FUNCTION public.update_enforcement_action_status(uuid, text, text)
FROM authenticated;
GRANT EXECUTE ON FUNCTION public.update_enforcement_action_status(uuid, text, text) TO service_role;
COMMIT;