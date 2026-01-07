-- 0018_update_insert_case.sql

-- Harmonize source/source_system columns and refresh insert RPC

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source'
  ) then
    update judgments.cases
    set source = coalesce(nullif(source, ''), nullif(source_system, ''), 'unknown')
    where source is null or source = '';

    alter table judgments.cases
      alter column source set default 'unknown';
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source_system'
  ) then
    update judgments.cases
    set source_system = coalesce(nullif(source_system, ''), nullif(source, ''), 'unknown')
    where source_system is null or source_system = '';

    alter table judgments.cases
      alter column source_system set default 'unknown';
  end if;
end $$;

create or replace function public.insert_case(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  new_id uuid;
  has_source_system boolean;
begin
  select exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source_system'
  ) into has_source_system;

  if has_source_system then
    insert into judgments.cases (
      case_number, source, source_system, title, court, filing_date, judgment_date,
      amount_awarded, currency, raw
    )
    values (
      payload->>'case_number',
      coalesce(payload->>'source','unknown'),
      coalesce(payload->>'source','unknown'),
      payload->>'title',
      payload->>'court',
      nullif(payload->>'filing_date','')::date,
      nullif(payload->>'judgment_date','')::date,
      nullif(payload->>'amount_awarded','')::numeric,
      coalesce(payload->>'currency','USD'),
      payload
    )
    returning case_id into new_id;
  else
    insert into judgments.cases (
      case_number, source, title, court, filing_date, judgment_date,
      amount_awarded, currency, raw
    )
    values (
      payload->>'case_number',
      coalesce(payload->>'source','unknown'),
      payload->>'title',
      payload->>'court',
      nullif(payload->>'filing_date','')::date,
      nullif(payload->>'judgment_date','')::date,
      nullif(payload->>'amount_awarded','')::numeric,
      coalesce(payload->>'currency','USD'),
      payload
    )
    returning case_id into new_id;
  end if;

  return new_id;
end $$;

