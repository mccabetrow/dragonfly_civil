-- 0074_plaintiffs_repair.sql
-- Ensures public plaintiff tables exist and connect to judgments in prod-safe fashion.

-- migrate:up

-- Establish canonical plaintiffs table and ensure expected columns/defaults.
CREATE TABLE IF NOT EXISTS public.plaintiffs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    name text NOT NULL,
    firm_name text,
    email text,
    phone text,
    status text NOT NULL DEFAULT 'new',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS firm_name text,
ADD COLUMN IF NOT EXISTS email text,
ADD COLUMN IF NOT EXISTS phone text,
ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'new',
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE public.plaintiffs
ALTER COLUMN status SET DEFAULT 'new';

UPDATE public.plaintiffs
SET status = 'new'
WHERE status IS NULL;

ALTER TABLE public.plaintiffs
ALTER COLUMN status SET NOT NULL,
ALTER COLUMN created_at SET DEFAULT now(),
ALTER COLUMN updated_at SET DEFAULT now(),
ALTER COLUMN id SET DEFAULT gen_random_uuid();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conrelid = 'public.plaintiffs'::regclass
          AND contype = 'p'
    ) THEN
        ALTER TABLE public.plaintiffs
            ADD CONSTRAINT plaintiffs_pkey PRIMARY KEY (id);
    END IF;
END
$$;

-- Contacts table and supporting index.
CREATE TABLE IF NOT EXISTS public.plaintiff_contacts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs (
        id
    ) ON DELETE CASCADE,
    name text NOT NULL,
    email text,
    phone text,
    role text,
    created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE public.plaintiff_contacts
ADD COLUMN IF NOT EXISTS plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs (
    id
) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS name text NOT NULL,
ADD COLUMN IF NOT EXISTS email text,
ADD COLUMN IF NOT EXISTS phone text,
ADD COLUMN IF NOT EXISTS role text,
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

ALTER TABLE public.plaintiff_contacts
ALTER COLUMN created_at SET DEFAULT now(),
ALTER COLUMN name SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_plaintiff_contacts_plaintiff_id
ON public.plaintiff_contacts (plaintiff_id);

-- Status history table and supporting index.
CREATE TABLE IF NOT EXISTS public.plaintiff_status_history (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs (
        id
    ) ON DELETE CASCADE,
    status text NOT NULL,
    note text,
    changed_at timestamptz NOT NULL DEFAULT now(),
    changed_by text
);

ALTER TABLE public.plaintiff_status_history
ADD COLUMN IF NOT EXISTS plaintiff_id uuid NOT NULL REFERENCES public.plaintiffs (
    id
) ON DELETE CASCADE,
ADD COLUMN IF NOT EXISTS status text NOT NULL,
ADD COLUMN IF NOT EXISTS note text,
ADD COLUMN IF NOT EXISTS changed_at timestamptz NOT NULL DEFAULT now(),
ADD COLUMN IF NOT EXISTS changed_by text;

ALTER TABLE public.plaintiff_status_history
ALTER COLUMN changed_at SET DEFAULT now(),
ALTER COLUMN status SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_plaintiff_status_history_plaintiff_id_changed_at
ON public.plaintiff_status_history (plaintiff_id, changed_at DESC);

-- Ensure judgments table has plaintiff linkage.
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS plaintiff_id uuid;

CREATE INDEX IF NOT EXISTS idx_judgments_plaintiff_id
ON public.judgments (plaintiff_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'judgments_plaintiff_id_fkey'
    ) THEN
        ALTER TABLE public.judgments
            ADD CONSTRAINT judgments_plaintiff_id_fkey
            FOREIGN KEY (plaintiff_id)
            REFERENCES public.plaintiffs(id)
            ON DELETE SET NULL;
    END IF;
END
$$;

-- Recreate view expected by dashboards.
CREATE OR REPLACE VIEW public.v_plaintiffs_overview AS
SELECT
    p.id AS plaintiff_id,
    p.name AS plaintiff_name,
    p.firm_name,
    p.status,
    coalesce(sum(j.judgment_amount), 0)::numeric AS total_judgment_amount,
    count(DISTINCT j.id) AS case_count
FROM public.plaintiffs AS p
LEFT JOIN public.judgments AS j
    ON p.id = j.plaintiff_id
GROUP BY
    p.id,
    p.name,
    p.firm_name,
    p.status;

-- migrate:down

DROP VIEW IF EXISTS public.v_plaintiffs_overview;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'judgments_plaintiff_id_fkey'
    ) THEN
        ALTER TABLE public.judgments
            DROP CONSTRAINT judgments_plaintiff_id_fkey;
    END IF;
END
$$;

DROP INDEX IF EXISTS idx_judgments_plaintiff_id;
ALTER TABLE public.judgments
DROP COLUMN IF EXISTS plaintiff_id;

DROP INDEX IF EXISTS idx_plaintiff_status_history_plaintiff_id_changed_at;
DROP TABLE IF EXISTS public.plaintiff_status_history;

DROP INDEX IF EXISTS idx_plaintiff_contacts_plaintiff_id;
DROP TABLE IF EXISTS public.plaintiff_contacts;

DROP TABLE IF EXISTS public.plaintiffs;

-- 0074_plaintiffs_repair.sql
-- Ensures public.plaintiffs and related tables/views exist for ETL and dashboards on all environments.
