-- 0124_simplicity_import_support.sql
-- Harden plaintiff + contact tables for Simplicity importer idempotency.
BEGIN;
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS source_reference text;
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS lead_metadata jsonb;
ALTER TABLE public.plaintiffs
ALTER COLUMN lead_metadata
SET DEFAULT '{}'::jsonb;
UPDATE public.plaintiffs
SET lead_metadata = '{}'::jsonb
WHERE lead_metadata IS NULL;
ALTER TABLE public.plaintiffs
ALTER COLUMN lead_metadata
SET NOT NULL;
ALTER TABLE public.plaintiff_contacts
ADD COLUMN IF NOT EXISTS kind text,
ADD COLUMN IF NOT EXISTS value text;
CREATE UNIQUE INDEX IF NOT EXISTS ux_plaintiff_contacts_plaintiff_kind_value ON public.plaintiff_contacts (
    plaintiff_id, kind, value
)
WHERE kind IS NOT NULL
AND value IS NOT NULL;
ALTER TABLE judgments.judgments
ADD COLUMN IF NOT EXISTS judgment_number text;
COMMIT;
-- NOTE: Simplicity importer support migration.
-- Adds source_reference + contact uniqueness to support idempotent ingest of external leads.

