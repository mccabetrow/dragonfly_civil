-- 0214_enrichment_contacts_table.sql
-- Ensure enrichment.contacts table exists for upsert_enrichment_bundle RPC.
-- This table stores contact information (phone, email, address) for entities.
BEGIN;
-- Create the contacts table if it doesn't exist
CREATE TABLE IF NOT EXISTS enrichment.contacts (
    contact_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    entity_id uuid NOT NULL REFERENCES parties.entities(entity_id) ON DELETE CASCADE,
    kind enrichment.contact_kind NOT NULL,
    value text NOT NULL,
    source text,
    validated_bool boolean DEFAULT false,
    score numeric(5, 2) DEFAULT 0,
    created_at timestamptz DEFAULT now(),
    UNIQUE (entity_id, kind, value)
);
-- Grant permissions
GRANT SELECT,
    INSERT,
    UPDATE,
    DELETE ON enrichment.contacts TO service_role;
GRANT SELECT ON enrichment.contacts TO anon,
    authenticated;
COMMIT;
