-- ════════════════════════════════════════════════════════════════════════════
-- Migration: 20251210140000_ui_telemetry.sql
-- Purpose:   Create ops.ui_actions table for UI telemetry tracking
-- Author:    Dragonfly Engineering
-- ════════════════════════════════════════════════════════════════════════════
--
-- This table captures UI interaction events from the dashboard, enabling:
--   - User behavior analytics
--   - Feature usage tracking
--   - Debugging user-reported issues
--   - Compliance audit trails
--
-- Design decisions:
--   - Placed in ops schema (operational telemetry, not business data)
--   - context is JSONB for flexible event payloads
--   - session_id enables cross-event correlation without requiring auth
--   - user_id nullable to allow anonymous telemetry if needed
--   - Index on created_at for time-range queries
--   - Index on event_name for filtering by event type
--
-- Security model:
--   - authenticated users call ops.log_ui_action() RPC (SECURITY DEFINER)
--   - NO direct INSERT grant to authenticated (follows least-privilege model)
--   - service_role has full access for backend analytics
-- ════════════════════════════════════════════════════════════════════════════
BEGIN;
-- Ensure ops schema exists
CREATE SCHEMA IF NOT EXISTS ops;
-- Create the UI actions telemetry table
CREATE TABLE IF NOT EXISTS ops.ui_actions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    user_id uuid NULL,
    -- Optional: link to auth.users if authenticated
    session_id text NULL,
    -- Client-generated session identifier
    event_name text NOT NULL,
    context jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Constraints
    CONSTRAINT ui_actions_event_name_not_empty CHECK (event_name <> ''),
    CONSTRAINT ui_actions_context_is_object CHECK (jsonb_typeof(context) = 'object')
);
-- Comment for documentation
COMMENT ON TABLE ops.ui_actions IS 'UI telemetry events from the Dragonfly dashboard';
COMMENT ON COLUMN ops.ui_actions.id IS 'Unique identifier for the event';
COMMENT ON COLUMN ops.ui_actions.created_at IS 'Timestamp when the event occurred';
COMMENT ON COLUMN ops.ui_actions.user_id IS 'Optional user ID if authenticated';
COMMENT ON COLUMN ops.ui_actions.session_id IS 'Client-side session identifier for event correlation';
COMMENT ON COLUMN ops.ui_actions.event_name IS 'Event type identifier (e.g., intake.upload_submitted)';
COMMENT ON COLUMN ops.ui_actions.context IS 'Event-specific metadata as JSONB';
-- Indexes for query performance
CREATE INDEX IF NOT EXISTS idx_ui_actions_created_at ON ops.ui_actions (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ui_actions_event_name ON ops.ui_actions (event_name);
CREATE INDEX IF NOT EXISTS idx_ui_actions_session_id ON ops.ui_actions (session_id)
WHERE session_id IS NOT NULL;
-- =============================================================================
-- SECURITY: Revoke direct table access from public roles
-- =============================================================================
REVOKE
INSERT,
    UPDATE,
    DELETE ON ops.ui_actions
FROM authenticated,
    anon;
-- Grant full access to privileged roles only
GRANT ALL ON ops.ui_actions TO postgres;
GRANT ALL ON ops.ui_actions TO service_role;
-- =============================================================================
-- SECURITY DEFINER RPC: log_ui_action
-- =============================================================================
-- Authenticated users insert telemetry through this function, not directly
CREATE OR REPLACE FUNCTION ops.log_ui_action(
        p_event_name text,
        p_context jsonb DEFAULT '{}'::jsonb,
        p_session_id text DEFAULT NULL
    ) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = ops,
    public AS $$
DECLARE v_user_id uuid;
v_action_id uuid;
BEGIN -- Get current user ID from auth context (NULL if not authenticated)
v_user_id := auth.uid();
-- Validate event_name
IF p_event_name IS NULL
OR p_event_name = '' THEN RAISE EXCEPTION 'event_name is required';
END IF;
-- Validate context is an object
IF jsonb_typeof(p_context) != 'object' THEN RAISE EXCEPTION 'context must be a JSON object';
END IF;
-- Insert the telemetry event
INSERT INTO ops.ui_actions (user_id, session_id, event_name, context)
VALUES (v_user_id, p_session_id, p_event_name, p_context)
RETURNING id INTO v_action_id;
RETURN v_action_id;
END;
$$;
COMMENT ON FUNCTION ops.log_ui_action IS 'Log a UI telemetry event (SECURITY DEFINER - safe for authenticated)';
-- Grant EXECUTE to authenticated users (the RPC validates and inserts safely)
GRANT EXECUTE ON FUNCTION ops.log_ui_action(text, jsonb, text) TO authenticated;
GRANT EXECUTE ON FUNCTION ops.log_ui_action(text, jsonb, text) TO service_role;
COMMIT;