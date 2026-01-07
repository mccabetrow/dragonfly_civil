-- 0111_plaintiff_schema_alignment.sql
-- Reinforce plaintiff-facing tables so dashboards + doctor checks see the expected columns.
-- migrate:up
BEGIN;
-- Ensure plaintiffs expose a canonical tier column for downstream tooling.
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS tier text;
ALTER TABLE public.plaintiffs
ALTER COLUMN tier
SET DEFAULT 'unknown';
UPDATE public.plaintiffs
SET tier = COALESCE(NULLIF(tier, ''), 'unknown')
WHERE tier IS NULL
    OR btrim(tier) = '';
-- Provide lightweight contact-kind/value projections alongside legacy columns.
ALTER TABLE public.plaintiff_contacts
ADD COLUMN IF NOT EXISTS kind text,
    ADD COLUMN IF NOT EXISTS value text;
WITH resolved AS (
    SELECT id,
        CASE
            WHEN email IS NOT NULL
            AND btrim(email) <> '' THEN 'email'
            WHEN phone IS NOT NULL
            AND btrim(phone) <> '' THEN 'phone'
            WHEN role IS NOT NULL
            AND btrim(role) <> '' THEN lower(role)
            WHEN name IS NOT NULL
            AND btrim(name) <> '' THEN 'name'
            ELSE 'other'
        END AS derived_kind,
        COALESCE(
            NULLIF(email, ''),
            NULLIF(phone, ''),
            NULLIF(name, ''),
            NULLIF(role, '')
        ) AS derived_value
    FROM public.plaintiff_contacts
)
UPDATE public.plaintiff_contacts pc
SET kind = COALESCE(pc.kind, resolved.derived_kind),
    value = COALESCE(pc.value, resolved.derived_value)
FROM resolved
WHERE resolved.id = pc.id
    AND (
        pc.kind IS DISTINCT
        FROM resolved.derived_kind
            OR pc.value IS DISTINCT
        FROM resolved.derived_value
    );
-- Mirror historical naming by exposing recorded_at alongside changed_at.
ALTER TABLE public.plaintiff_status_history
ADD COLUMN IF NOT EXISTS recorded_at timestamptz;
UPDATE public.plaintiff_status_history
SET recorded_at = COALESCE(recorded_at, changed_at, timezone('utc', now()))
WHERE recorded_at IS NULL;
ALTER TABLE public.plaintiff_status_history
ALTER COLUMN recorded_at
SET DEFAULT timezone('utc', now()),
    ALTER COLUMN recorded_at
SET NOT NULL;
-- Surface call_outcome/called_at aliases for call attempt auditing without renaming legacy columns.
ALTER TABLE public.plaintiff_call_attempts
ADD COLUMN IF NOT EXISTS call_outcome text GENERATED ALWAYS AS (outcome) STORED;
ALTER TABLE public.plaintiff_call_attempts
ADD COLUMN IF NOT EXISTS called_at timestamptz GENERATED ALWAYS AS (attempted_at) STORED;
-- Ensure import runs expose a lightweight source column for analytics joins.
ALTER TABLE public.import_runs
ADD COLUMN IF NOT EXISTS source text;
COMMIT;
-- migrate:down
BEGIN;
ALTER TABLE public.plaintiff_status_history DROP COLUMN IF EXISTS recorded_at;
ALTER TABLE public.plaintiff_contacts DROP COLUMN IF EXISTS value;
ALTER TABLE public.plaintiff_contacts DROP COLUMN IF EXISTS kind;
ALTER TABLE public.plaintiffs DROP COLUMN IF EXISTS tier;
ALTER TABLE public.plaintiff_call_attempts DROP COLUMN IF EXISTS call_outcome;
ALTER TABLE public.plaintiff_call_attempts DROP COLUMN IF EXISTS called_at;
ALTER TABLE public.import_runs DROP COLUMN IF EXISTS source;
COMMIT;
