-- 0019_insert_case_not_null.sql

create or replace function public.insert_case(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  new_id uuid;
  has_source_system boolean;
  case_source text;
  case_title text;
  case_court text;
  case_payload jsonb := coalesce(payload, '{}'::jsonb);
  filing date := nullif(case_payload->>'filing_date', '')::date;
  judgment date := nullif(case_payload->>'judgment_date', '')::date;
  awarded numeric := nullif(case_payload->>'amount_awarded', '')::numeric;
  case_currency text := coalesce(case_payload->>'currency', 'USD');
begin
  case_source := coalesce(nullif(case_payload->>'source', ''), 'unknown');
  case_title := coalesce(nullif(case_payload->>'title', ''), case_payload->>'case_number', 'Untitled Case');
  case_court := coalesce(nullif(case_payload->>'court', ''), 'Unknown Court');

  select exists (
    select 1
    from information_schema.columns
    where table_schema = 'judgments'
      and table_name = 'cases'
      and column_name = 'source_system'
  ) into has_source_system;

  if has_source_system then
    insert into judgments.cases (
      case_number, source, source_system, title, court_name, court, filing_date, judgment_date,
      amount_awarded, currency, raw
    )
    values (
      case_payload->>'case_number',
      case_source,
      case_source,
      case_title,
      case_court,
      case_court,
      filing,
      judgment,
      awarded,
      case_currency,
      case_payload
    )
    returning case_id into new_id;
  else
    insert into judgments.cases (
      case_number, source, title, court, filing_date, judgment_date,
      amount_awarded, currency, raw
    )
    values (
      case_payload->>'case_number',
      case_source,
      case_title,
      case_court,
      filing,
      judgment,
      awarded,
      case_currency,
      case_payload
    )
    returning case_id into new_id;
  end if;

  return new_id;
end $$;

