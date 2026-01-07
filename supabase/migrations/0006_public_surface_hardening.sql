-- Reassert the public REST surface idempotently (no ALTER COLUMN RENAME on views).

-- === Recreate public.v_cases safely ========================================
DO $$
DECLARE
  has_cases BOOLEAN;
  id_col TEXT;
  idx_col TEXT;
  cols TEXT := '';
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'judgments' AND table_name = 'cases'
  ) INTO has_cases;

  IF NOT has_cases THEN
    EXECUTE $DDL$
      CREATE OR REPLACE VIEW public.v_cases AS
      SELECT
        NULL::uuid        AS case_id,
        NULL::text        AS index_no,
        NULL::text        AS court,
        NULL::text        AS county,
        NULL::date        AS judgment_at,
        NULL::numeric     AS principal_amt,
        NULL::text        AS status,
        NULL::timestamptz AS created_at,
        NULL::timestamptz AS updated_at
      WHERE FALSE;
    $DDL$;
  ELSE
    -- choose case identifier: case_id or id
    SELECT column_name
      INTO id_col
    FROM information_schema.columns
    WHERE table_schema = 'judgments' AND table_name = 'cases'
      AND column_name IN ('case_id','id')
    ORDER BY CASE WHEN column_name = 'case_id' THEN 0 ELSE 1 END
    LIMIT 1;

    IF id_col IS NULL THEN
      RAISE EXCEPTION 'judgments.cases missing identifier (case_id or id)';
    END IF;

    -- choose index column: index_no or index_number
    SELECT column_name
      INTO idx_col
    FROM information_schema.columns
    WHERE table_schema = 'judgments' AND table_name = 'cases'
      AND column_name IN ('index_no','index_number')
    ORDER BY CASE WHEN column_name = 'index_no' THEN 0 ELSE 1 END
    LIMIT 1;

    WITH wanted(name, typ) AS (
      VALUES
        ('court','text'),
        ('county','text'),
        ('judgment_at','date'),
        ('principal_amt','numeric'),
        ('status','text'),
        ('created_at','timestamptz'),
        ('updated_at','timestamptz')
    )
    SELECT string_agg(
             CASE
               WHEN EXISTS (
                 SELECT 1 FROM information_schema.columns
                 WHERE table_schema = 'judgments' AND table_name = 'cases'
                   AND column_name = name
               )
               THEN format('%I', name)
               ELSE format('NULL::%s AS %I', typ, name)
             END,
             ', ' ORDER BY name
           )
      INTO cols
    FROM wanted;

    EXECUTE format($DDL$
      CREATE OR REPLACE VIEW public.v_cases AS
      SELECT
        %1$s AS case_id,
        %2$s AS index_no,
        %3$s
      FROM judgments.cases;
    $DDL$,
      quote_ident(id_col),
      CASE WHEN idx_col IS NOT NULL THEN quote_ident(idx_col) ELSE 'NULL::text' END,
      cols
    );
  END IF;
END $$;

-- === Recreate public.v_collectability safely ===============================
DO $$
DECLARE
  has_table BOOLEAN;
BEGIN
  SELECT EXISTS (
    SELECT 1 FROM information_schema.tables
    WHERE table_schema = 'enrichment' AND table_name = 'collectability'
  ) INTO has_table;

  IF has_table THEN
    EXECUTE $DDL$
      CREATE OR REPLACE VIEW public.v_collectability AS
      SELECT
        case_id,
        identity_score,
        contactability_score,
        asset_score,
        recency_amount_score,
        adverse_penalty,
        total_score,
        tier,
        updated_at
      FROM enrichment.collectability;
    $DDL$;
  ELSE
    EXECUTE $DDL$
      CREATE OR REPLACE VIEW public.v_collectability AS
      SELECT
        NULL::uuid        AS case_id,
        NULL::numeric     AS identity_score,
        NULL::numeric     AS contactability_score,
        NULL::numeric     AS asset_score,
        NULL::numeric     AS recency_amount_score,
        NULL::numeric     AS adverse_penalty,
        NULL::numeric     AS total_score,
        NULL::text        AS tier,
        NULL::timestamptz AS updated_at
      WHERE FALSE;
    $DDL$;
  END IF;
END $$;

-- === Re-wrap RPCs (don’t fail if originals missing) ========================
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'enrichment' AND p.proname = 'upsert_enrichment_bundle'
          AND pg_catalog.pg_get_function_arguments(p.oid) = 'bundle jsonb'
  ) THEN
    EXECUTE $DDL$
      CREATE OR REPLACE FUNCTION public.upsert_enrichment_bundle(bundle jsonb)
      RETURNS jsonb
      LANGUAGE plpgsql
      SECURITY DEFINER
      AS $FN$
      BEGIN
        RETURN enrichment.upsert_enrichment_bundle(bundle);
      END
      $FN$;
    $DDL$;
  END IF;
END $$;

-- === Grants ================================================================
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT SELECT ON public.v_cases,
public.v_collectability TO anon,
authenticated,
service_role;
GRANT EXECUTE ON FUNCTION public.insert_case(jsonb) TO anon,
authenticated,
service_role;
-- only if it exists:
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE n.nspname = 'public' AND p.proname = 'upsert_enrichment_bundle'
          AND pg_catalog.pg_get_function_arguments(p.oid) = 'bundle jsonb'
  ) THEN
    EXECUTE 'GRANT EXECUTE ON FUNCTION public.upsert_enrichment_bundle(jsonb) TO anon, authenticated, service_role';
  END IF;
END $$;

