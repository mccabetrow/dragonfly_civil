-- 0076_enforcement_columns_repair.sql
-- Ensures enforcement_stage columns exist on public.judgments in all environments.

-- migrate:up

ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS enforcement_stage text,
ADD COLUMN IF NOT EXISTS enforcement_stage_updated_at timestamptz;

-- migrate:down

-- No-op: safety migration only.
