-- 0213_enrichment_contact_kind_type.sql
-- Ensure enrichment.contact_kind enum type exists for upsert_enrichment_bundle RPC.
-- This type is required by the enrichment contacts table and RPCs.
BEGIN;
-- Create the type if it doesn't exist
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
    WHERE n.nspname = 'enrichment'
        AND t.typname = 'contact_kind'
) THEN CREATE TYPE enrichment.contact_kind AS ENUM ('phone', 'email', 'address');
END IF;
END $$;
COMMIT;
