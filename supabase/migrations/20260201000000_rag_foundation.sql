-- ============================================================================
-- Migration: RAG Foundation (Citations Enforced)
-- Purpose: Vector storage for document embeddings linked to evidence vault
-- Date: 2026-02-01
-- ============================================================================
--
-- Architecture:
--   evidence.files (source of truth) → rag.documents → rag.chunks
--
-- Key Features:
--   - pgvector for high-dimensional similarity search
--   - HNSW index for fast approximate nearest neighbor
--   - Strict FK to evidence.files for citation integrity
--   - RLS for org-based tenancy isolation
--   - Optimized match_chunks RPC for RAG retrieval
-- ============================================================================
-- ============================================================================
-- PART 1: Enable pgvector Extension
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;
-- ============================================================================
-- PART 2: RAG Schema
-- ============================================================================
CREATE SCHEMA IF NOT EXISTS rag;
COMMENT ON SCHEMA rag IS 'Retrieval-Augmented Generation: document embeddings and vector search';
-- ============================================================================
-- PART 3: Document Processing Status Enum
-- ============================================================================
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
    WHERE t.typname = 'document_status'
        AND n.nspname = 'rag'
) THEN CREATE TYPE rag.document_status AS ENUM (
    'pending',
    -- Queued for processing
    'processing',
    -- Currently being chunked/embedded
    'indexed',
    -- Successfully processed and searchable
    'failed' -- Processing failed (see error_message)
);
END IF;
END $$;
-- ============================================================================
-- PART 4: Documents Table
-- Tracks processing state for each evidence file
-- ============================================================================
CREATE TABLE IF NOT EXISTS rag.documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Link to immutable evidence (citation source)
    evidence_id UUID NOT NULL REFERENCES evidence.files(id) ON DELETE RESTRICT,
    -- Tenancy
    org_id UUID NOT NULL REFERENCES tenant.orgs(id) ON DELETE CASCADE,
    -- Processing state
    status rag.document_status NOT NULL DEFAULT 'pending',
    -- Metrics
    token_count INTEGER CHECK (
        token_count IS NULL
        OR token_count >= 0
    ),
    chunk_count INTEGER CHECK (
        chunk_count IS NULL
        OR chunk_count >= 0
    ),
    -- Embedding model used (for future compatibility)
    embedding_model TEXT DEFAULT 'text-embedding-3-small',
    embedding_dimensions INTEGER DEFAULT 1536,
    -- Error tracking
    error_message TEXT,
    retry_count INTEGER NOT NULL DEFAULT 0,
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Ensure one document record per evidence file
    CONSTRAINT uq_documents_evidence UNIQUE (evidence_id)
);
-- Table comments
COMMENT ON TABLE rag.documents IS '{"description": "Document processing registry for RAG system", "sensitivity": "MEDIUM", "retention": "7_years"}';
COMMENT ON COLUMN rag.documents.evidence_id IS '{"tag": "INTERNAL", "description": "FK to evidence.files - immutable citation source"}';
COMMENT ON COLUMN rag.documents.org_id IS '{"tag": "INTERNAL", "description": "Owning organization for RLS"}';
COMMENT ON COLUMN rag.documents.status IS '{"tag": "INTERNAL", "description": "Processing state machine"}';
COMMENT ON COLUMN rag.documents.token_count IS '{"tag": "INTERNAL", "description": "Total tokens across all chunks"}';
COMMENT ON COLUMN rag.documents.embedding_model IS '{"tag": "INTERNAL", "description": "Model used for embeddings (e.g., text-embedding-3-small)"}';
-- Indexes
CREATE INDEX IF NOT EXISTS idx_rag_documents_org_id ON rag.documents(org_id);
CREATE INDEX IF NOT EXISTS idx_rag_documents_status ON rag.documents(status);
CREATE INDEX IF NOT EXISTS idx_rag_documents_pending ON rag.documents(created_at ASC)
WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_rag_documents_evidence ON rag.documents(evidence_id);
-- ============================================================================
-- PART 5: Chunks Table
-- Individual text segments with vector embeddings
-- ============================================================================
CREATE TABLE IF NOT EXISTS rag.chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    -- Parent document
    document_id UUID NOT NULL REFERENCES rag.documents(id) ON DELETE CASCADE,
    -- Denormalized for RLS efficiency (avoids join to documents)
    org_id UUID NOT NULL REFERENCES tenant.orgs(id) ON DELETE CASCADE,
    -- Position tracking for citations
    chunk_index INTEGER NOT NULL CHECK (chunk_index >= 0),
    page_number INTEGER CHECK (
        page_number IS NULL
        OR page_number >= 1
    ),
    -- Chunk boundaries in source (for highlighting)
    start_char INTEGER CHECK (
        start_char IS NULL
        OR start_char >= 0
    ),
    end_char INTEGER CHECK (
        end_char IS NULL
        OR end_char >= 0
    ),
    -- Content
    content TEXT NOT NULL CHECK (char_length(content) > 0),
    -- Vector embedding (OpenAI text-embedding-3-small = 1536 dimensions)
    embedding vector(1536) NOT NULL,
    -- Metadata for filtering
    metadata JSONB DEFAULT '{}',
    -- Timestamps
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Unique chunk per document
    CONSTRAINT uq_chunks_document_index UNIQUE (document_id, chunk_index),
    -- end_char must be > start_char if both present
    CONSTRAINT chk_char_range CHECK (
        start_char IS NULL
        OR end_char IS NULL
        OR end_char > start_char
    )
);
-- Table comments
COMMENT ON TABLE rag.chunks IS '{"description": "Text chunks with vector embeddings for semantic search", "sensitivity": "MEDIUM", "retention": "7_years"}';
COMMENT ON COLUMN rag.chunks.embedding IS '{"tag": "INTERNAL", "description": "1536-dim vector from text-embedding-3-small"}';
COMMENT ON COLUMN rag.chunks.chunk_index IS '{"tag": "INTERNAL", "description": "0-based index within document for ordering"}';
COMMENT ON COLUMN rag.chunks.page_number IS '{"tag": "INTERNAL", "description": "Source page number for PDF citations"}';
COMMENT ON COLUMN rag.chunks.content IS '{"tag": "CONFIDENTIAL", "sensitivity": "HIGH", "description": "Extracted text content"}';
-- Standard indexes
CREATE INDEX IF NOT EXISTS idx_rag_chunks_document_id ON rag.chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_org_id ON rag.chunks(org_id);
CREATE INDEX IF NOT EXISTS idx_rag_chunks_page ON rag.chunks(document_id, page_number)
WHERE page_number IS NOT NULL;
-- ============================================================================
-- PART 6: HNSW Vector Index
-- Optimized for cosine similarity (used by OpenAI embeddings)
-- ============================================================================
-- HNSW parameters:
--   m = 16: connections per layer (default, good balance)
--   ef_construction = 64: build-time quality (default)
--
-- The index uses cosine distance (<=> operator)
CREATE INDEX IF NOT EXISTS idx_rag_chunks_embedding_hnsw ON rag.chunks USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
-- ============================================================================
-- PART 7: Row-Level Security
-- ============================================================================
ALTER TABLE rag.documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag.chunks ENABLE ROW LEVEL SECURITY;
-- Documents: org-based isolation
CREATE POLICY "documents_org_isolation" ON rag.documents FOR ALL USING (
    org_id = (
        current_setting('request.jwt.claims', true)::jsonb->>'org_id'
    )::uuid
);
-- Chunks: org-based isolation
CREATE POLICY "chunks_org_isolation" ON rag.chunks FOR ALL USING (
    org_id = (
        current_setting('request.jwt.claims', true)::jsonb->>'org_id'
    )::uuid
);
-- Service role bypass for workers
CREATE POLICY "documents_service_role" ON rag.documents FOR ALL TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "chunks_service_role" ON rag.chunks FOR ALL TO service_role USING (true) WITH CHECK (true);
-- ============================================================================
-- PART 8: Updated_at Trigger
-- ============================================================================
CREATE OR REPLACE FUNCTION rag.update_timestamp() RETURNS TRIGGER AS $$ BEGIN NEW.updated_at = now();
RETURN NEW;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS trg_documents_updated_at ON rag.documents;
CREATE TRIGGER trg_documents_updated_at BEFORE
UPDATE ON rag.documents FOR EACH ROW EXECUTE FUNCTION rag.update_timestamp();
-- ============================================================================
-- PART 9: Match Chunks RPC (Semantic Search)
-- ============================================================================
-- Highly optimized function for RAG retrieval
-- Uses cosine similarity with configurable threshold and limit
-- Respects org_id filter for multi-tenant isolation
CREATE OR REPLACE FUNCTION rag.match_chunks(
        query_embedding vector(1536),
        match_threshold float DEFAULT 0.7,
        match_count int DEFAULT 10,
        filter_org_id uuid DEFAULT NULL
    ) RETURNS TABLE (
        id uuid,
        document_id uuid,
        evidence_id uuid,
        chunk_index int,
        page_number int,
        content text,
        similarity float,
        metadata jsonb
    ) LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = rag,
    public AS $$ BEGIN RETURN QUERY
SELECT c.id,
    c.document_id,
    d.evidence_id,
    c.chunk_index,
    c.page_number,
    c.content,
    -- Cosine similarity = 1 - cosine distance
    (1 - (c.embedding <=> query_embedding))::float AS similarity,
    c.metadata
FROM rag.chunks c
    JOIN rag.documents d ON d.id = c.document_id
WHERE -- Org filter (required for multi-tenant)
    c.org_id = filter_org_id -- Status filter (only search indexed documents)
    AND d.status = 'indexed' -- Similarity threshold
    AND (1 - (c.embedding <=> query_embedding)) >= match_threshold
ORDER BY c.embedding <=> query_embedding -- ORDER BY distance (ascending)
LIMIT match_count;
END;
$$;
COMMENT ON FUNCTION rag.match_chunks IS 'Semantic search across document chunks with org isolation. Returns chunks sorted by similarity above threshold.';
-- ============================================================================
-- PART 10: Convenience Functions
-- ============================================================================
-- Get document processing stats by org
CREATE OR REPLACE FUNCTION rag.get_document_stats(p_org_id uuid) RETURNS TABLE (
        status rag.document_status,
        doc_count bigint,
        total_chunks bigint,
        total_tokens bigint
    ) LANGUAGE sql STABLE SECURITY DEFINER
SET search_path = rag,
    public AS $$
SELECT d.status,
    COUNT(DISTINCT d.id) AS doc_count,
    COUNT(c.id) AS total_chunks,
    COALESCE(SUM(d.token_count), 0) AS total_tokens
FROM rag.documents d
    LEFT JOIN rag.chunks c ON c.document_id = d.id
WHERE d.org_id = p_org_id
GROUP BY d.status
ORDER BY d.status;
$$;
-- Queue a document for processing
CREATE OR REPLACE FUNCTION rag.queue_document(p_evidence_id uuid, p_org_id uuid) RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
SET search_path = rag,
    evidence,
    public AS $$
DECLARE v_doc_id uuid;
BEGIN -- Verify evidence file exists and belongs to org
IF NOT EXISTS (
    SELECT 1
    FROM evidence.files
    WHERE id = p_evidence_id
        AND org_id = p_org_id
) THEN RAISE EXCEPTION 'Evidence file % not found or not owned by org %',
p_evidence_id,
p_org_id;
END IF;
-- Insert or get existing document
INSERT INTO rag.documents (evidence_id, org_id, status)
VALUES (p_evidence_id, p_org_id, 'pending') ON CONFLICT (evidence_id) DO
UPDATE
SET status = CASE
        WHEN rag.documents.status = 'failed' THEN 'pending'::rag.document_status
        ELSE rag.documents.status
    END,
    retry_count = CASE
        WHEN rag.documents.status = 'failed' THEN rag.documents.retry_count + 1
        ELSE rag.documents.retry_count
    END,
    error_message = CASE
        WHEN rag.documents.status = 'failed' THEN NULL
        ELSE rag.documents.error_message
    END,
    updated_at = now()
RETURNING id INTO v_doc_id;
RETURN v_doc_id;
END;
$$;
COMMENT ON FUNCTION rag.queue_document IS 'Queue an evidence file for RAG processing. Returns document ID.';
-- Mark document as indexed with chunk count
CREATE OR REPLACE FUNCTION rag.mark_document_indexed(
        p_document_id uuid,
        p_token_count integer,
        p_chunk_count integer
    ) RETURNS void LANGUAGE sql SECURITY DEFINER
SET search_path = rag,
    public AS $$
UPDATE rag.documents
SET status = 'indexed',
    token_count = p_token_count,
    chunk_count = p_chunk_count,
    processed_at = now(),
    error_message = NULL,
    updated_at = now()
WHERE id = p_document_id;
$$;
-- Mark document as failed
CREATE OR REPLACE FUNCTION rag.mark_document_failed(
        p_document_id uuid,
        p_error_message text
    ) RETURNS void LANGUAGE sql SECURITY DEFINER
SET search_path = rag,
    public AS $$
UPDATE rag.documents
SET status = 'failed',
    error_message = p_error_message,
    updated_at = now()
WHERE id = p_document_id;
$$;
-- ============================================================================
-- PART 11: Grants
-- ============================================================================
GRANT USAGE ON SCHEMA rag TO service_role;
GRANT ALL ON ALL TABLES IN SCHEMA rag TO service_role;
GRANT ALL ON ALL SEQUENCES IN SCHEMA rag TO service_role;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA rag TO service_role;
-- Authenticated users can search (RLS will filter)
GRANT USAGE ON SCHEMA rag TO authenticated;
GRANT SELECT ON rag.documents TO authenticated;
GRANT SELECT ON rag.chunks TO authenticated;
GRANT EXECUTE ON FUNCTION rag.match_chunks TO authenticated;
GRANT EXECUTE ON FUNCTION rag.get_document_stats TO authenticated;
-- ============================================================================
-- VERIFICATION QUERIES (run after migration)
-- ============================================================================
-- Check extension:
--   SELECT * FROM pg_extension WHERE extname = 'vector';
--
-- Check HNSW index:
--   SELECT indexname, indexdef FROM pg_indexes 
--   WHERE tablename = 'chunks' AND schemaname = 'rag';
--
-- Test match_chunks (with dummy embedding):
--   SELECT * FROM rag.match_chunks(
--       ARRAY_FILL(0.1, ARRAY[1536])::vector(1536),
--       0.5,
--       5,
--       'your-org-uuid-here'
--   );