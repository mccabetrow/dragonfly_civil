-- 0086_intake_files.sql
-- migrate:up
CREATE TABLE IF NOT EXISTS public.intake_files (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    source text NOT NULL,
    file_name text NOT NULL,
    batch_name text NOT NULL,
    import_run_id uuid,
    status text NOT NULL DEFAULT 'pending',
    processed_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_intake_files_source_file ON public.intake_files (
    source, file_name
);
CREATE INDEX IF NOT EXISTS idx_intake_files_import_run ON public.intake_files (
    import_run_id
);
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgname = 'trg_intake_files_touch'
        AND tgrelid = 'public.intake_files'::regclass
) THEN CREATE TRIGGER trg_intake_files_touch BEFORE
UPDATE ON public.intake_files FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
END IF;
END $$;
ALTER TABLE public.intake_files ENABLE ROW LEVEL SECURITY;
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'intake_files'
        AND policyname = 'intake_files_service_rw'
) THEN CREATE POLICY intake_files_service_rw ON public.intake_files FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
END $$;
REVOKE ALL ON public.intake_files
FROM public;
REVOKE ALL ON public.intake_files
FROM anon;
REVOKE ALL ON public.intake_files
FROM authenticated;
GRANT SELECT,
INSERT,
UPDATE,
DELETE ON public.intake_files TO service_role;
-- migrate:down
REVOKE
SELECT,
INSERT,
UPDATE,
DELETE ON public.intake_files
FROM service_role;
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'intake_files'
        AND policyname = 'intake_files_service_rw'
) THEN DROP POLICY intake_files_service_rw ON public.intake_files;
END IF;
END $$;
ALTER TABLE public.intake_files DISABLE ROW LEVEL SECURITY;
DROP TRIGGER IF EXISTS trg_intake_files_touch ON public.intake_files;
DROP INDEX IF EXISTS idx_intake_files_import_run;
DROP INDEX IF EXISTS idx_intake_files_source_file;
DROP TABLE IF EXISTS public.intake_files;
