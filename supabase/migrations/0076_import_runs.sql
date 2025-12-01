-- 0076_import_runs.sql

-- migrate:up

CREATE TABLE IF NOT EXISTS public.import_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    import_kind text NOT NULL,
    source_system text NOT NULL,
    source_reference text,
    file_name text,
    storage_path text,
    status text NOT NULL DEFAULT 'pending',
    total_rows integer CHECK (total_rows IS NULL OR total_rows >= 0),
    inserted_rows integer CHECK (inserted_rows IS NULL OR inserted_rows >= 0),
    skipped_rows integer CHECK (skipped_rows IS NULL OR skipped_rows >= 0),
    error_rows integer CHECK (error_rows IS NULL OR error_rows >= 0),
    started_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    finished_at timestamptz,
    created_by text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_import_runs_touch'
          AND tgrelid = 'public.import_runs'::regclass
    ) THEN
        CREATE TRIGGER trg_import_runs_touch
            BEFORE UPDATE ON public.import_runs
            FOR EACH ROW
            EXECUTE FUNCTION public.tg_touch_updated_at();
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_import_runs_started_at
ON public.import_runs (started_at DESC);

CREATE INDEX IF NOT EXISTS idx_import_runs_status
ON public.import_runs (status);

ALTER TABLE public.import_runs ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'import_runs'
          AND policyname = 'import_runs_service_rw'
    ) THEN
        CREATE POLICY import_runs_service_rw ON public.import_runs
            FOR ALL
            USING (auth.role() = 'service_role')
            WITH CHECK (auth.role() = 'service_role');
    END IF;
END
$$;

REVOKE ALL ON public.import_runs FROM public;
REVOKE ALL ON public.import_runs FROM anon;
REVOKE ALL ON public.import_runs FROM authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.import_runs TO service_role;

-- migrate:down

REVOKE SELECT, INSERT, UPDATE, DELETE ON public.import_runs FROM service_role;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM pg_policies
        WHERE schemaname = 'public'
          AND tablename = 'import_runs'
          AND policyname = 'import_runs_service_rw'
    ) THEN
        DROP POLICY import_runs_service_rw ON public.import_runs;
    END IF;
END
$$;

ALTER TABLE public.import_runs DISABLE ROW LEVEL SECURITY;

DROP INDEX IF EXISTS idx_import_runs_status;
DROP INDEX IF EXISTS idx_import_runs_started_at;

DROP TRIGGER IF EXISTS trg_import_runs_touch ON public.import_runs;

DROP TABLE IF EXISTS public.import_runs;
