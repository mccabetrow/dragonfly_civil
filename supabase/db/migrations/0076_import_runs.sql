-- 0076_import_runs.sql

-- migrate:up

create table if not exists public.import_runs (
    id uuid primary key default gen_random_uuid(),
    import_kind text not null,
    source_system text not null,
    source_reference text,
    file_name text,
    storage_path text,
    status text not null default 'pending',
    total_rows integer check (total_rows is NULL or total_rows >= 0),
    inserted_rows integer check (inserted_rows is NULL or inserted_rows >= 0),
    skipped_rows integer check (skipped_rows is NULL or skipped_rows >= 0),
    error_rows integer check (error_rows is NULL or error_rows >= 0),
    started_at timestamptz not null default timezone('utc', now()),
    finished_at timestamptz,
    created_by text,
    metadata jsonb not null default '{}'::jsonb,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);

do $$
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

create index if not exists idx_import_runs_started_at
on public.import_runs (started_at desc);

create index if not exists idx_import_runs_status
on public.import_runs (status);

alter table public.import_runs enable row level security;

do $$
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

revoke all on public.import_runs from public;
revoke all on public.import_runs from anon;
revoke all on public.import_runs from authenticated;
grant select, insert, update, delete on public.import_runs to service_role;

-- migrate:down

revoke select, insert, update, delete on public.import_runs from service_role;

do $$
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

alter table public.import_runs disable row level security;

drop index if exists idx_import_runs_status;
drop index if exists idx_import_runs_started_at;

drop trigger if exists trg_import_runs_touch on public.import_runs;

drop table if exists public.import_runs;
