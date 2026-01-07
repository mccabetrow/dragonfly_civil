-- Migration: Judgment Intelligence Graph
-- Version: Dragonfly Engine v0.2.x
-- Description: Creates schema, types, and tables for the entity/relationship graph
-- ============================================================================
-- ============================================================================
-- 1. Ensure schema exists
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS intelligence;
-- ============================================================================
-- 2. Create enums safely (wrapped in DO blocks for idempotency)
-- ============================================================================
-- Entity type enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'entity_type'
        AND typnamespace = (
            SELECT oid
            FROM pg_namespace
            WHERE nspname = 'intelligence'
        )
) THEN CREATE TYPE intelligence.entity_type AS ENUM (
    'person',
    'company',
    'address',
    'court',
    'attorney'
);
END IF;
END $$;
-- Relation type enum
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type
    WHERE typname = 'relation_type'
        AND typnamespace = (
            SELECT oid
            FROM pg_namespace
            WHERE nspname = 'intelligence'
        )
) THEN CREATE TYPE intelligence.relation_type AS ENUM (
    'plaintiff_in',
    'defendant_in',
    'located_at',
    'employed_by',
    'sued_at'
);
END IF;
END $$;
-- ============================================================================
-- 3. intelligence.entities - Core entity table
-- ============================================================================
CREATE TABLE IF NOT EXISTS intelligence.entities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    type intelligence.entity_type NOT NULL,
    raw_name TEXT NOT NULL,
    normalized_name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Uniqueness constraint for deduplication
    CONSTRAINT uq_entities_normalized_name_type UNIQUE (normalized_name, type)
);
COMMENT ON TABLE intelligence.entities IS 'Core entities in the judgment intelligence graph (people, companies, courts, etc.)';
COMMENT ON COLUMN intelligence.entities.type IS 'Entity type: person, company, address, court, attorney';
COMMENT ON COLUMN intelligence.entities.raw_name IS 'Original name as found in source data';
COMMENT ON COLUMN intelligence.entities.normalized_name IS 'Normalized name for matching (uppercase, trimmed, collapsed spaces)';
COMMENT ON COLUMN intelligence.entities.metadata IS 'Additional entity attributes as JSON';
-- Index for fast lookups by normalized_name
CREATE INDEX IF NOT EXISTS idx_entities_normalized_name ON intelligence.entities(normalized_name);
-- Index for type-based queries
CREATE INDEX IF NOT EXISTS idx_entities_type ON intelligence.entities(type);
-- ============================================================================
-- 4. intelligence.relationships - Relationships between entities
-- ============================================================================
CREATE TABLE IF NOT EXISTS intelligence.relationships (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_entity_id UUID NOT NULL REFERENCES intelligence.entities(id) ON DELETE CASCADE,
    target_entity_id UUID NOT NULL REFERENCES intelligence.entities(id) ON DELETE CASCADE,
    relation intelligence.relation_type NOT NULL,
    source_judgment_id BIGINT REFERENCES public.judgments(id) ON DELETE CASCADE,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE intelligence.relationships IS 'Relationships between entities in the intelligence graph';
COMMENT ON COLUMN intelligence.relationships.source_entity_id IS 'The source entity in the relationship';
COMMENT ON COLUMN intelligence.relationships.target_entity_id IS 'The target entity in the relationship';
COMMENT ON COLUMN intelligence.relationships.relation IS 'Relationship type: plaintiff_in, defendant_in, located_at, employed_by, sued_at';
COMMENT ON COLUMN intelligence.relationships.source_judgment_id IS 'The judgment that established this relationship';
COMMENT ON COLUMN intelligence.relationships.confidence IS 'Confidence score for the relationship (0.0 to 1.0)';
-- Indexes for graph traversal
CREATE INDEX IF NOT EXISTS idx_relationships_source_entity ON intelligence.relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target_entity ON intelligence.relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_source_judgment ON intelligence.relationships(source_judgment_id);
-- Index for relationship type queries
CREATE INDEX IF NOT EXISTS idx_relationships_relation ON intelligence.relationships(relation);
-- ============================================================================
-- 5. Grant permissions for service role access
-- ============================================================================
GRANT USAGE ON SCHEMA intelligence TO service_role;
GRANT ALL ON intelligence.entities TO service_role;
GRANT ALL ON intelligence.relationships TO service_role;
-- ============================================================================
-- 6. Optional: View for entity summary with relationship counts
-- ============================================================================
CREATE OR REPLACE VIEW intelligence.v_entity_summary AS
SELECT e.id,
    e.type,
    e.raw_name,
    e.normalized_name,
    e.metadata,
    e.created_at,
    (
        SELECT COUNT(*)
        FROM intelligence.relationships r
        WHERE r.source_entity_id = e.id
    ) AS outgoing_relationships,
    (
        SELECT COUNT(*)
        FROM intelligence.relationships r
        WHERE r.target_entity_id = e.id
    ) AS incoming_relationships
FROM intelligence.entities e
ORDER BY e.created_at DESC;
GRANT SELECT ON intelligence.v_entity_summary TO service_role;
COMMENT ON VIEW intelligence.v_entity_summary IS 'Entity summary with relationship counts for graph analysis';
