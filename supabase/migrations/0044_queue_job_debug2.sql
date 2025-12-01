-- migrate:up

DO $$
DECLARE
  rec record;
BEGIN
  FOR rec IN
    SELECT
      n.nspname AS schema_name,
      p.proname AS function_name,
      pg_get_function_arguments(p.oid) AS arguments,
      pg_get_function_result(p.oid) AS result_type
    FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proname = 'queue_job'
  LOOP
    RAISE NOTICE 'queue_job variant -> %.%(%): %', rec.schema_name, rec.function_name, rec.arguments, rec.result_type;
  END LOOP;
  IF NOT FOUND THEN
    RAISE NOTICE 'No queue_job variants present';
  END IF;
END;
$$;

-- migrate:down

DO $$ BEGIN END $$;
