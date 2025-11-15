-- 0056_enrichment_runs_sequence_grants.sql
-- Ensure service role can use enrichment runs sequence.

-- migrate:up

do $$
begin
    if exists (
        select 1
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'S'
          and n.nspname = 'judgments'
          and c.relname = 'enrichment_runs_id_seq'
    ) then
        execute 'grant usage, select on sequence judgments.enrichment_runs_id_seq to service_role';
    end if;
end;
$$;

-- migrate:down

do $$
begin
    if exists (
        select 1
        from pg_class c
        join pg_namespace n on n.oid = c.relnamespace
        where c.relkind = 'S'
          and n.nspname = 'judgments'
          and c.relname = 'enrichment_runs_id_seq'
    ) then
        execute 'revoke usage, select on sequence judgments.enrichment_runs_id_seq from service_role';
    end if;
end;
$$;
