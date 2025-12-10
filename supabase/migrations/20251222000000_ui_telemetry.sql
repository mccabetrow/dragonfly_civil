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
-- Grant INSERT to authenticated (logged-in users) and service_role (backend).
-- No SELECT grant by default; use privileged access for analytics.
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
-- Grant INSERT to authenticated users and service_role
-- No SELECT grant - analytics access through privileged roles only
GRANT INSERT ON ops.ui_actions TO authenticated;
GRANT INSERT ON ops.ui_actions TO service_role;
-- service_role can also SELECT for backend analytics
GRANT SELECT ON ops.ui_actions TO service_role;
COMMIT;