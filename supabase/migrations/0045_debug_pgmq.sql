-- migrate:up

DO $$
BEGIN
  PERFORM pgmq.send('diagnostic_queue', jsonb_build_object('ping', now()));
  RAISE NOTICE 'pgmq.send exists';
EXCEPTION
  WHEN undefined_function THEN
    RAISE NOTICE 'pgmq.send is missing';
  WHEN undefined_table THEN
    RAISE NOTICE 'pgmq queue diagnostic_queue is missing';
END;
$$;

-- migrate:down

DO $$ BEGIN END $$;
