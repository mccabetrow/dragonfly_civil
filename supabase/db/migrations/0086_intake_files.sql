-- 0086_intake_files.sql
-- migrate:up
create table if not exists public.intake_files (
    id uuid primary key default gen_random_uuid(),
    source text not null,
    file_name text not null,
    batch_name text not null,
    import_run_id uuid,
    status text not null default 'pending',
    processed_at timestamptz,
    metadata jsonb not null default '{}'::jsonb,
    error_message text,
    created_at timestamptz not null default timezone('utc', now()),
    updated_at timestamptz not null default timezone('utc', now())
);
create unique index if not exists idx_intake_files_source_file on public.intake_files (
    source, file_name
);
create index if not exists idx_intake_files_import_run on public.intake_files (
    import_run_id
);
do $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_trigger
    WHERE tgname = 'trg_intake_files_touch'
        AND tgrelid = 'public.intake_files'::regclass
) THEN CREATE TRIGGER trg_intake_files_touch BEFORE
UPDATE ON public.intake_files FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
END IF;
END $$;
alter table public.intake_files enable row level security;
do $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'intake_files'
        AND policyname = 'intake_files_service_rw'
) THEN CREATE POLICY intake_files_service_rw ON public.intake_files FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
END IF;
END $$;
revoke all on public.intake_files
from public;
revoke all on public.intake_files
from anon;
revoke all on public.intake_files
from authenticated;
grant select,
insert,
update,
delete on public.intake_files to service_role;
-- migrate:down
revoke
select,
insert,
update,
delete on public.intake_files
from service_role;
do $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_policies
    WHERE schemaname = 'public'
        AND tablename = 'intake_files'
        AND policyname = 'intake_files_service_rw'
) THEN DROP POLICY intake_files_service_rw ON public.intake_files;
END IF;
END $$;
alter table public.intake_files disable row level security;
drop trigger if exists trg_intake_files_touch on public.intake_files;
drop index if exists idx_intake_files_import_run;
drop index if exists idx_intake_files_source_file;
drop table if exists public.intake_files;
