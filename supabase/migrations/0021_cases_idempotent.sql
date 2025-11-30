-- 0021_cases_idempotent.sql

-- Ensure deterministic uniqueness for case ingestion
create unique index if not exists ux_cases_org_src_num
on judgments.cases (org_id, source, case_number);

-- Optional guard: prevent negative awarded amounts
do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conrelid = 'judgments.cases'::regclass
      and conname = 'cases_amount_awarded_nonnegative'
  ) then
    alter table judgments.cases
      add constraint cases_amount_awarded_nonnegative
      check (amount_awarded is null or amount_awarded >= 0);
  end if;
end;
$$;

-- Idempotent insert wrapper
create or replace function public.insert_or_get_case(payload jsonb)
returns uuid
language plpgsql
security definer
as $$
declare
  v_payload jsonb := coalesce(payload, '{}'::jsonb);
  v_case_id uuid;
  v_org_id uuid := nullif(v_payload->>'org_id', '')::uuid;
  v_source text := coalesce(nullif(v_payload->>'source', ''), 'unknown');
  v_case_number text := v_payload->>'case_number';
begin
  begin
    v_case_id := public.insert_case(v_payload);

    if v_org_id is not null then
      update judgments.cases c
      set org_id = v_org_id
      where c.case_id = v_case_id
      returning c.case_id into v_case_id;
    end if;

    return v_case_id;
  exception
    when unique_violation then
      select c.case_id
        into v_case_id
      from judgments.cases c
      where c.source = v_source
        and c.case_number = v_case_number
        and (v_org_id is null or c.org_id = v_org_id)
      order by c.created_at desc
      limit 1;

      if v_case_id is null then
        raise;
      end if;

      return v_case_id;
  end;
end;
$$;

-- Grant execution to standard roles
grant execute on function public.insert_or_get_case(jsonb) to anon,
authenticated,
service_role;
