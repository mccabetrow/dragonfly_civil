-- Migration: Event Stream for Intelligence Graph
-- Version: Dragonfly Engine v0.2.x
-- Description: Append-only event log for enforcement lifecycle tracking
-- ============================================================================
-- Purpose: Record every important enforcement event (new judgment, job found,
-- assets found, offer made, packet sent) so we can show a defendant timeline
-- in the CEO cockpit.
-- ============================================================================
-- ============================================================================
-- 1. Ensure schema exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS intelligence;
-- ============================================================================
-- 2. Create event_type enum safely (wrapped in DO block for idempotency)
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'event_type'
        AND typnamespace = (
            SELECT oid
            FROM pg_namespace
            WHERE nspname = 'intelligence'
        )
) THEN CREATE TYPE intelligence.event_type AS ENUM (
    'new_judgment',
    'job_found',
    'asset_found',
    'offer_made',
    'offer_accepted',
    'packet_sent'
);
END IF;
END $$;
-- ============================================================================
-- 3. intelligence.events - Append-only event log
-- ============================================================================
CREATE TABLE IF NOT EXISTS intelligence.events (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id UUID NOT NULL REFERENCES intelligence.entities(id) ON DELETE CASCADE,
    event_type intelligence.event_type NOT NULL,
    payload JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE intelligence.events IS 'Append-only event log for enforcement lifecycle tracking';
COMMENT ON COLUMN intelligence.events.entity_id IS 'The entity (typically defendant) this event relates to';
COMMENT ON COLUMN intelligence.events.event_type IS 'Type of enforcement event (new_judgment, job_found, asset_found, offer_made, offer_accepted, packet_sent)';
COMMENT ON COLUMN intelligence.events.payload IS 'Event-specific data as JSON';
COMMENT ON COLUMN intelligence.events.created_at IS 'When the event occurred';
-- ============================================================================
-- 4. Indexes for efficient timeline queries
-- ============================================================================
-- Primary index: fetch timeline for an entity ordered by time
CREATE INDEX IF NOT EXISTS idx_events_entity_created_at ON intelligence.events(entity_id, created_at);
-- Secondary index: filter by event type across all entities
CREATE INDEX IF NOT EXISTS idx_events_type_created_at ON intelligence.events(event_type, created_at);
-- ============================================================================
-- 5. Grant permissions for service role access
-- ============================================================================
GRANT USAGE ON SCHEMA intelligence TO service_role;
GRANT ALL ON intelligence.events TO service_role;
-- ============================================================================
-- 6. View: Recent events for ops debugging
-- ============================================================================
CREATE OR REPLACE VIEW intelligence.v_recent_events AS
SELECT e.id,
    e.entity_id,
    ent.raw_name AS entity_name,
    ent.type AS entity_type,
    e.event_type,
    e.payload,
    e.created_at,
    -- Human-readable summary
    CASE
        e.event_type
        WHEN 'new_judgment' THEN 'Judgment created for ' || COALESCE(e.payload->>'amount', '?') || ' in ' || COALESCE(e.payload->>'county', '?')
        WHEN 'job_found' THEN 'Job found at ' || COALESCE(e.payload->>'employer_name', 'unknown employer')
        WHEN 'asset_found' THEN 'Asset found: ' || COALESCE(e.payload->>'asset_type', 'unknown asset')
        WHEN 'offer_made' THEN 'Offer made: $' || COALESCE(e.payload->>'amount', '?')
        WHEN 'offer_accepted' THEN 'Offer ACCEPTED for $' || COALESCE(e.payload->>'amount', '?')
        WHEN 'packet_sent' THEN 'Packet sent: ' || COALESCE(e.payload->>'packet_type', 'unknown type')
        ELSE e.event_type::text
    END AS summary
FROM intelligence.events e
    LEFT JOIN intelligence.entities ent ON ent.id = e.entity_id
WHERE e.created_at > now() - INTERVAL '30 days'
ORDER BY e.created_at DESC;
GRANT SELECT ON intelligence.v_recent_events TO service_role;
COMMENT ON VIEW intelligence.v_recent_events IS 'Recent events (last 30 days) with human-readable summaries for ops debugging';
-- ============================================================================
-- 7. Helper function to get entity_id from judgment_id
-- ============================================================================
-- This function finds the defendant entity for a judgment by looking up
-- the 'defendant_in' relationship in the intelligence graph.
CREATE OR REPLACE FUNCTION intelligence.get_defendant_entity_for_judgment(p_judgment_id BIGINT) RETURNS UUID AS $$
DECLARE v_entity_id UUID;
BEGIN -- Find the defendant entity that has a 'defendant_in' relationship to this judgment
SELECT r.source_entity_id INTO v_entity_id
FROM intelligence.relationships r
WHERE r.source_judgment_id = p_judgment_id
    AND r.relation = 'defendant_in'
LIMIT 1;
RETURN v_entity_id;
END;
$$ LANGUAGE plpgsql STABLE;
COMMENT ON FUNCTION intelligence.get_defendant_entity_for_judgment IS 'Find the defendant entity ID for a given judgment';
GRANT EXECUTE ON FUNCTION intelligence.get_defendant_entity_for_judgment TO service_role;