-- ============================================================================
-- Migration: 20251205000000_dragonfly_brain.sql
-- Dragonfly Brain: Vector-First + Event-Sourced Judgment Infrastructure
-- ============================================================================
-- PURPOSE:
--   1. Enable pgvector for semantic search
--   2. Add description_embedding column to public.judgments
--   3. Add collectability_score column to public.judgments
--   4. Create judgment_history table for audit trail (event-sourcing lite)
--   5. Create trigger to log status changes automatically
-- ============================================================================
-- ============================================================================
-- 1. Enable Required Extensions
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;
-- ============================================================================
-- 2. Augment public.judgments with vector + scoring columns
-- ============================================================================
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS description_embedding vector(1536);
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS collectability_score numeric(5, 2);
COMMENT ON COLUMN public.judgments.description_embedding IS 'OpenAI text-embedding-3-small vector (1536 dims) for semantic search';
COMMENT ON COLUMN public.judgments.collectability_score IS 'Collectability score 0-100; higher = more likely to collect. Filled by enrichment workers.';
-- ============================================================================
-- 3. Create HNSW Index for Fast Semantic Search (cosine similarity)
-- ============================================================================
CREATE INDEX IF NOT EXISTS public_judgments_description_embedding_hnsw_idx ON public.judgments USING hnsw (description_embedding vector_cosine_ops);
-- ============================================================================
-- 4. Create Audit Table: public.judgment_history
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.judgment_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id bigint NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    old_status text,
    new_status text NOT NULL,
    changed_by text NOT NULL,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);
COMMENT ON TABLE public.judgment_history IS 'Event-sourcing audit log for judgment status changes. Every status transition is recorded.';
COMMENT ON COLUMN public.judgment_history.judgment_id IS 'FK to public.judgments(id)';
COMMENT ON COLUMN public.judgment_history.old_status IS 'Previous status value (null for initial insert)';
COMMENT ON COLUMN public.judgment_history.new_status IS 'New status value after change';
COMMENT ON COLUMN public.judgment_history.changed_by IS 'Actor identifier: username, system, or worker name';
COMMENT ON COLUMN public.judgment_history.reason IS 'Optional reason or note for the status change';
-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_judgment_history_judgment_id ON public.judgment_history(judgment_id);
CREATE INDEX IF NOT EXISTS idx_judgment_history_created_at ON public.judgment_history(created_at DESC);
-- Grants for service role
GRANT ALL ON public.judgment_history TO service_role;
-- ============================================================================
-- 5. Create Trigger Function for Status Change Logging
-- ============================================================================
CREATE OR REPLACE FUNCTION public.trg_log_judgment_status_change() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE v_changed_by text;
BEGIN -- Only log if status actually changed
IF OLD.status IS DISTINCT
FROM NEW.status THEN -- Get actor from session setting, fallback to 'system'
    v_changed_by := coalesce(
        nullif(
            current_setting('dragonfly.changed_by', true),
            ''
        ),
        'system'
    );
INSERT INTO public.judgment_history (
        judgment_id,
        old_status,
        new_status,
        changed_by,
        reason
    )
VALUES (
        NEW.id,
        OLD.status,
        NEW.status,
        v_changed_by,
        coalesce(
            nullif(
                current_setting('dragonfly.change_reason', true),
                ''
            ),
            null
        )
    );
END IF;
RETURN NEW;
END;
$$;
COMMENT ON FUNCTION public.trg_log_judgment_status_change() IS 'Trigger function to log status changes to judgment_history. Reads dragonfly.changed_by and dragonfly.change_reason from session settings.';
-- ============================================================================
-- 6. Attach Trigger to public.judgments
-- ============================================================================
DROP TRIGGER IF EXISTS trg_judgments_status_audit ON public.judgments;
CREATE TRIGGER trg_judgments_status_audit
AFTER
UPDATE ON public.judgments FOR EACH ROW EXECUTE FUNCTION public.trg_log_judgment_status_change();
-- ============================================================================
-- 7. Notify PostgREST to reload schema
-- ============================================================================
NOTIFY pgrst,
'reload schema';