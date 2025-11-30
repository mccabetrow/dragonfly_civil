-- 0004_public_api_wrappers.sql
-- Robust public wrappers that tolerate column name differences.

-- === public.v_cases =========================================================
do $$
declare
  has_cases bool;
  id_col text;
  idx_col text;
  cols text := '';
begin
  select exists (
    select 1 from information_schema.tables
    where table_schema='judgments' and table_name='cases'
  ) into has_cases;

  if not has_cases then
    -- If core table is missing, expose an empty, typed view so API doesn't 406.
    execute $DDL$
      create or replace view public.v_cases as
      select
        null::uuid  as case_id,
        null::text  as index_no,
        null::text  as court,
        null::text  as county,
        null::date  as judgment_at,
        null::numeric as principal_amt,
        null::text  as status,
        null::timestamptz as created_at,
        null::timestamptz as updated_at
      where false;
    $DDL$;
    return;
  end if;

  -- Choose identifier column: case_id or id
  select column_name
    into id_col
  from information_schema.columns
  where table_schema='judgments' and table_name='cases'
    and column_name in ('case_id','id')
  order by case when column_name='case_id' then 0 else 1 end
  limit 1;

  if id_col is null then
    raise exception 'judgments.cases lacks case identifier (case_id or id)';
  end if;

  -- Choose index column: index_no or index_number (else NULL::text)
  select column_name
    into idx_col
  from information_schema.columns
  where table_schema='judgments' and table_name='cases'
    and column_name in ('index_no','index_number')
  order by case when column_name='index_no' then 0 else 1 end
  limit 1;

  -- Build safe select list (probe existence; else NULL::type alias)
  with wanted(name, typ) as (
    values
      ('court','text'),
      ('county','text'),
      ('judgment_at','date'),
      ('principal_amt','numeric'),
      ('status','text'),
      ('created_at','timestamptz'),
      ('updated_at','timestamptz')
  )
  select string_agg(
           case
             when exists (
               select 1 from information_schema.columns
               where table_schema='judgments' and table_name='cases'
                 and column_name = name
             )
             then format('%I', name)
             else format('NULL::%s as %I', typ, name)
           end,
           ', ' order by name
         )
    into cols
  from wanted;

  execute format($DDL$
    create or replace view public.v_cases as
    select
      %1$s as case_id,
      %2$s as index_no,
      %3$s
    from judgments.cases;
  $DDL$,
    quote_ident(id_col),
    case when idx_col is not null then quote_ident(idx_col) else 'NULL::text' end,
    cols
  );
end $$;

-- === public.v_collectability ===============================================
do $$
declare
  has_table bool;
begin
  select exists (
    select 1 from information_schema.tables
    where table_schema='enrichment' and table_name='collectability'
  ) into has_table;

  if has_table then
    execute $DDL$
      create or replace view public.v_collectability as
      select
        case_id,
        identity_score,
        contactability_score,
        asset_score,
        recency_amount_score,
        adverse_penalty,
        total_score,
        tier,
        updated_at
      from enrichment.collectability;
    $DDL$;
  else
    execute $DDL$
      create or replace view public.v_collectability as
      select
        null::uuid as case_id,
        null::numeric as identity_score,
        null::numeric as contactability_score,
        null::numeric as asset_score,
        null::numeric as recency_amount_score,
        null::numeric as adverse_penalty,
        null::numeric as total_score,
        null::text   as tier,
        null::timestamptz as updated_at
      where false;
    $DDL$;
  end if;
end $$;

-- === Grants ================================================================
grant usage on schema public to anon, authenticated, service_role;
grant select on public.v_cases,
public.v_collectability to anon,
authenticated,
service_role;
