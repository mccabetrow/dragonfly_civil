-- 0072_plaintiffs_and_links.sql
-- Establish core plaintiff tables and link judgments to plaintiffs.

-- migrate:up

-- === plaintiffs table =======================================================
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

-- Ensure newer columns exist when the table predates this migration.
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS id uuid DEFAULT gen_random_uuid(),
ADD COLUMN IF NOT EXISTS firm_name text,
ADD COLUMN IF NOT EXISTS email text,
ADD COLUMN IF NOT EXISTS phone text,
ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'new',
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now(),
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

-- Ensure the canonical UUID id is primary and defaults correctly when legacy ids exist.
DO $$
DECLARE
    v_col_type text;
BEGIN
    SELECT data_type INTO v_col_type
    FROM information_schema.columns
    WHERE table_schema = 'public'
      AND table_name = 'plaintiffs'
      AND column_name = 'id';

    IF v_col_type = 'uuid' THEN
        ALTER TABLE public.plaintiffs
            ALTER COLUMN id SET DEFAULT gen_random_uuid();
    END IF;

    UPDATE public.plaintiffs
    SET status = 'new'
    WHERE status IS NULL;

    ALTER TABLE public.plaintiffs
        ALTER COLUMN status SET DEFAULT 'new',
        ALTER COLUMN status SET NOT NULL;
EXCEPTION
    WHEN undefined_table THEN
        NULL;
END
$$;

DO $$
BEGIN
    ALTER TABLE public.plaintiff_contacts
        ALTER COLUMN created_at SET NOT NULL;
EXCEPTION
    WHEN undefined_table THEN
        -- Table will be created later in this migration when prior schema lacked it.
        NULL;
END
$$;

-- Align timestamps with touch trigger semantics if present.
ALTER TABLE public.plaintiffs
ALTER COLUMN created_at SET DEFAULT now(),
ALTER COLUMN updated_at SET DEFAULT now();

-- === plaintiff_contacts table ===============================================
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

CREATE INDEX IF NOT EXISTS plaintiff_contacts_plaintiff_id_idx
ON public.plaintiff_contacts (plaintiff_id);

ALTER TABLE public.plaintiff_contacts
ADD COLUMN IF NOT EXISTS name text,
ADD COLUMN IF NOT EXISTS email text,
ADD COLUMN IF NOT EXISTS phone text,
ADD COLUMN IF NOT EXISTS role text,
ADD COLUMN IF NOT EXISTS created_at timestamptz NOT NULL DEFAULT now();

DO $$
BEGIN
    ALTER TABLE public.plaintiff_contacts
        ALTER COLUMN created_at SET DEFAULT now();
EXCEPTION
    WHEN undefined_table THEN
        NULL;
END
$$;

DO $$
DECLARE
    has_label boolean;
    has_contact_value boolean;
    update_sql text := 'UPDATE public.plaintiff_contacts SET name = COALESCE(name';
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'plaintiff_contacts'
          AND column_name = 'label'
    ) INTO has_label;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'plaintiff_contacts'
          AND column_name = 'contact_value'
    ) INTO has_contact_value;

    IF has_label THEN
        update_sql := update_sql || ', label';
    END IF;
    IF has_contact_value THEN
        update_sql := update_sql || ', contact_value';
    END IF;

    update_sql := update_sql || ', ''Primary Contact'') WHERE name IS NULL';

    EXECUTE update_sql;

    ALTER TABLE public.plaintiff_contacts
        ALTER COLUMN name SET DEFAULT 'Primary Contact',
        ALTER COLUMN name SET NOT NULL;
EXCEPTION
    WHEN undefined_table THEN
        NULL;
END
$$;

-- === plaintiff_status_history table ========================================
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
ADD COLUMN IF NOT EXISTS note text,
ADD COLUMN IF NOT EXISTS changed_at timestamptz NOT NULL DEFAULT now(),
ADD COLUMN IF NOT EXISTS changed_by text;

ALTER TABLE public.plaintiff_status_history
ALTER COLUMN changed_at SET DEFAULT now();

DO $$
DECLARE
    has_reason boolean;
    has_recorded_at boolean;
    has_recorded_by boolean;
    update_sql text := 'UPDATE public.plaintiff_status_history SET';
    set_clauses text := '';
BEGIN
    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'plaintiff_status_history'
          AND column_name = 'reason'
    ) INTO has_reason;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'plaintiff_status_history'
          AND column_name = 'recorded_at'
    ) INTO has_recorded_at;

    SELECT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'plaintiff_status_history'
          AND column_name = 'recorded_by'
    ) INTO has_recorded_by;

    IF has_reason THEN
        set_clauses := set_clauses || ' note = COALESCE(note, reason)';
    END IF;

    IF has_recorded_at THEN
        IF set_clauses <> '' THEN
            set_clauses := set_clauses || ',';
        END IF;
        set_clauses := set_clauses || ' changed_at = COALESCE(changed_at, recorded_at)';
    END IF;

    IF has_recorded_by THEN
        IF set_clauses <> '' THEN
            set_clauses := set_clauses || ',';
        END IF;
        set_clauses := set_clauses || ' changed_by = COALESCE(changed_by, recorded_by)';
    END IF;

    IF set_clauses <> '' THEN
        update_sql := update_sql || set_clauses || ' WHERE TRUE';
        EXECUTE update_sql;
    END IF;

    UPDATE public.plaintiff_status_history
    SET changed_at = COALESCE(changed_at, now())
    WHERE changed_at IS NULL;

    CREATE INDEX plaintiff_status_history_plaintiff_changed_idx
        ON public.plaintiff_status_history (plaintiff_id, changed_at DESC);
EXCEPTION
    WHEN duplicate_table THEN
        NULL;
    WHEN duplicate_object THEN
        NULL;
END
$$;

ALTER TABLE public.plaintiff_status_history
ALTER COLUMN changed_at SET NOT NULL;

-- === judgments linkage =====================================================
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS plaintiff_id uuid,
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

DO $$
BEGIN
    ALTER TABLE public.judgments
        ADD CONSTRAINT judgments_plaintiff_id_fkey
        FOREIGN KEY (plaintiff_id)
        REFERENCES public.plaintiffs(id)
        ON DELETE SET NULL;
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END
$$;

DO $$
BEGIN
    CREATE INDEX idx_public_judgments_plaintiff_id
        ON public.judgments (plaintiff_id);
EXCEPTION
    WHEN duplicate_object THEN
        NULL;
END
$$;

-- === views ==================================================================
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS plaintiff_id uuid REFERENCES public.plaintiffs (
    id
) ON DELETE SET NULL;

ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();

CREATE INDEX IF NOT EXISTS idx_public_judgments_plaintiff_id
ON public.judgments (plaintiff_id);

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

CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
SELECT
    j.id AS judgment_id,
    j.case_number,
    j.plaintiff_id,
    j.judgment_amount,
    cs.collectability_tier,
    cs.age_days AS collectability_age_days,
    cs.last_enriched_at,
    cs.last_enrichment_status,
    coalesce(p.name, j.plaintiff_name) AS plaintiff_name
FROM public.judgments AS j
LEFT JOIN public.plaintiffs AS p
    ON j.plaintiff_id = p.id
LEFT JOIN public.v_collectability_snapshot AS cs
    ON j.case_number = cs.case_number;

-- === RLS reinforcement ======================================================
ALTER TABLE public.plaintiffs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaintiff_contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.plaintiff_status_history ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiffs'
          AND policyname = 'plaintiffs_select_public'
    ) THEN
        CREATE POLICY plaintiffs_select_public ON public.plaintiffs
            FOR SELECT
            USING (auth.role() IN ('anon', 'authenticated', 'service_role'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiffs'
          AND policyname = 'plaintiffs_insert_service'
    ) THEN
        CREATE POLICY plaintiffs_insert_service ON public.plaintiffs
            FOR INSERT
            WITH CHECK (auth.role() = 'service_role');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiffs'
          AND policyname = 'plaintiffs_update_service'
    ) THEN
        CREATE POLICY plaintiffs_update_service ON public.plaintiffs
            FOR UPDATE
            USING (auth.role() = 'service_role')
            WITH CHECK (auth.role() = 'service_role');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiffs'
          AND policyname = 'plaintiffs_delete_service'
    ) THEN
        CREATE POLICY plaintiffs_delete_service ON public.plaintiffs
            FOR DELETE
            USING (auth.role() = 'service_role');
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_contacts'
          AND policyname = 'plaintiff_contacts_select_public'
    ) THEN
        CREATE POLICY plaintiff_contacts_select_public ON public.plaintiff_contacts
            FOR SELECT
            USING (auth.role() IN ('anon', 'authenticated', 'service_role'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_contacts'
          AND policyname = 'plaintiff_contacts_insert_service'
    ) THEN
        CREATE POLICY plaintiff_contacts_insert_service ON public.plaintiff_contacts
            FOR INSERT
            WITH CHECK (auth.role() = 'service_role');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_contacts'
          AND policyname = 'plaintiff_contacts_update_service'
    ) THEN
        CREATE POLICY plaintiff_contacts_update_service ON public.plaintiff_contacts
            FOR UPDATE
            USING (auth.role() = 'service_role')
            WITH CHECK (auth.role() = 'service_role');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_contacts'
          AND policyname = 'plaintiff_contacts_delete_service'
    ) THEN
        CREATE POLICY plaintiff_contacts_delete_service ON public.plaintiff_contacts
            FOR DELETE
            USING (auth.role() = 'service_role');
    END IF;
END
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_status_history'
          AND policyname = 'plaintiff_status_select_public'
    ) THEN
        CREATE POLICY plaintiff_status_select_public ON public.plaintiff_status_history
            FOR SELECT
            USING (auth.role() IN ('anon', 'authenticated', 'service_role'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_status_history'
          AND policyname = 'plaintiff_status_insert_service'
    ) THEN
        CREATE POLICY plaintiff_status_insert_service ON public.plaintiff_status_history
            FOR INSERT
            WITH CHECK (auth.role() = 'service_role');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_status_history'
          AND policyname = 'plaintiff_status_update_service'
    ) THEN
        CREATE POLICY plaintiff_status_update_service ON public.plaintiff_status_history
            FOR UPDATE
            USING (auth.role() = 'service_role')
            WITH CHECK (auth.role() = 'service_role');
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'plaintiff_status_history'
          AND policyname = 'plaintiff_status_delete_service'
    ) THEN
        CREATE POLICY plaintiff_status_delete_service ON public.plaintiff_status_history
            FOR DELETE
            USING (auth.role() = 'service_role');
    END IF;
END
$$;

GRANT SELECT ON TABLE public.plaintiffs TO anon, authenticated, service_role;
GRANT INSERT, UPDATE, DELETE ON TABLE public.plaintiffs TO service_role;
GRANT SELECT ON TABLE public.plaintiff_contacts TO anon,
authenticated,
service_role;
GRANT INSERT, UPDATE, DELETE ON TABLE public.plaintiff_contacts TO service_role;
GRANT SELECT ON TABLE public.plaintiff_status_history TO anon,
authenticated,
service_role;
GRANT INSERT,
UPDATE,
DELETE ON TABLE public.plaintiff_status_history TO service_role;

-- migrate:down

DROP VIEW IF EXISTS public.v_plaintiffs_overview;
DROP VIEW IF EXISTS public.v_judgment_pipeline;
DROP INDEX IF EXISTS idx_public_judgments_plaintiff_id;
DO $$
BEGIN
    ALTER TABLE public.judgments DROP CONSTRAINT judgments_plaintiff_id_fkey;
EXCEPTION
    WHEN undefined_object THEN
        NULL;
END
$$;
ALTER TABLE public.judgments DROP COLUMN IF EXISTS plaintiff_id;
DROP INDEX IF EXISTS plaintiff_status_history_plaintiff_changed_idx;
DROP TABLE IF EXISTS public.plaintiff_status_history;
DROP INDEX IF EXISTS plaintiff_contacts_plaintiff_id_idx;
DROP TABLE IF EXISTS public.plaintiff_contacts;
DROP TABLE IF EXISTS public.plaintiffs;

-- Purpose: seed plaintiff entities, contacts, status log, and judgment linkage.
-- Dashboard: ensures v_plaintiffs_overview and v_judgment_pipeline exist with expected shapes.
