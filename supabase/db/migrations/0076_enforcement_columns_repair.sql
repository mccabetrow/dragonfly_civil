-- 0076_enforcement_columns_repair.sql
-- Ensures enforcement_stage columns exist on public.judgments in all environments.

-- migrate:up

alter table public.judgments
add column if not exists enforcement_stage text,
add column if not exists enforcement_stage_updated_at timestamptz;

-- migrate:down

-- No-op: safety migration only.
