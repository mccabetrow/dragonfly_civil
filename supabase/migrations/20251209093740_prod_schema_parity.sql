-- 20251209093740_prod_schema_parity.sql
-- Bring prod schema to parity with dev for Schema Guard compatibility
-- 
-- ISSUES ADDRESSED:
-- 1. ops.job_queue missing columns: locked_at, attempts, last_error
-- 2. public.enforcement_cases table missing
-- 3. public.enforcement_events table missing  
-- 4. public.plaintiff_contacts missing columns: phone, email, name, role, kind, value
--
-- This migration is IDEMPOTENT - safe to run on both dev and prod.
BEGIN;
-- ============================================================================
-- SECTION 1: ops.job_queue column additions
-- Add missing columns needed by recovery SQL and workers
-- ============================================================================
-- Add locked_at column (used for job locking mechanism)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
        AND column_name = 'locked_at'
) THEN
ALTER TABLE ops.job_queue
ADD COLUMN locked_at timestamptz;
RAISE NOTICE 'Added ops.job_queue.locked_at';
END IF;
END $$;
-- Add attempts column (tracks retry count)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
        AND column_name = 'attempts'
) THEN
ALTER TABLE ops.job_queue
ADD COLUMN attempts int NOT NULL DEFAULT 0;
RAISE NOTICE 'Added ops.job_queue.attempts';
END IF;
END $$;
-- Add last_error column (stores error details)
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
        AND column_name = 'last_error'
) THEN -- If error_message exists, rename it; otherwise add new column
IF EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'ops'
        AND table_name = 'job_queue'
        AND column_name = 'error_message'
) THEN
ALTER TABLE ops.job_queue
    RENAME COLUMN error_message TO last_error;
RAISE NOTICE 'Renamed ops.job_queue.error_message to last_error';
ELSE
ALTER TABLE ops.job_queue
ADD COLUMN last_error text;
RAISE NOTICE 'Added ops.job_queue.last_error';
END IF;
END IF;
END $$;
-- Create index for job pickup (needed by workers)
CREATE INDEX IF NOT EXISTS idx_job_queue_pending_pickup ON ops.job_queue (status, locked_at, created_at)
WHERE status = 'pending';
-- ============================================================================
-- SECTION 2: public.enforcement_cases table
-- Core enforcement tracking table
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.enforcement_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    judgment_id bigint NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
    case_number text,
    opened_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    current_stage text,
    status text NOT NULL DEFAULT 'open',
    assigned_to text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
-- Indexes
CREATE INDEX IF NOT EXISTS enforcement_cases_judgment_idx ON public.enforcement_cases(judgment_id);
CREATE INDEX IF NOT EXISTS enforcement_cases_status_idx ON public.enforcement_cases(status);
-- Touch trigger (requires tg_touch_updated_at function)
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc
    WHERE proname = 'tg_touch_updated_at'
) THEN DROP TRIGGER IF EXISTS trg_enforcement_cases_touch ON public.enforcement_cases;
CREATE TRIGGER trg_enforcement_cases_touch BEFORE
UPDATE ON public.enforcement_cases FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
END IF;
END $$;
-- RLS
ALTER TABLE public.enforcement_cases ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.enforcement_cases
FROM public;
GRANT SELECT ON TABLE public.enforcement_cases TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE,
    DELETE ON TABLE public.enforcement_cases TO authenticated,
    service_role;
DROP POLICY IF EXISTS enforcement_cases_read ON public.enforcement_cases;
DROP POLICY IF EXISTS enforcement_cases_write ON public.enforcement_cases;
CREATE POLICY enforcement_cases_read ON public.enforcement_cases FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
CREATE POLICY enforcement_cases_write ON public.enforcement_cases FOR ALL USING (auth.role() IN ('authenticated', 'service_role')) WITH CHECK (auth.role() IN ('authenticated', 'service_role'));
-- ============================================================================
-- SECTION 3: public.enforcement_events table
-- Enforcement event tracking
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.enforcement_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    case_id uuid NOT NULL REFERENCES public.enforcement_cases(id) ON DELETE CASCADE,
    event_type text NOT NULL,
    event_date timestamptz NOT NULL DEFAULT timezone('utc', now()),
    notes text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
-- Indexes
CREATE INDEX IF NOT EXISTS enforcement_events_case_idx ON public.enforcement_events(case_id);
CREATE INDEX IF NOT EXISTS enforcement_events_date_idx ON public.enforcement_events(event_date DESC);
-- Touch trigger
DO $$ BEGIN IF EXISTS (
    SELECT 1
    FROM pg_proc
    WHERE proname = 'tg_touch_updated_at'
) THEN DROP TRIGGER IF EXISTS trg_enforcement_events_touch ON public.enforcement_events;
CREATE TRIGGER trg_enforcement_events_touch BEFORE
UPDATE ON public.enforcement_events FOR EACH ROW EXECUTE FUNCTION public.tg_touch_updated_at();
END IF;
END $$;
-- RLS
ALTER TABLE public.enforcement_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON TABLE public.enforcement_events
FROM public;
GRANT SELECT ON TABLE public.enforcement_events TO anon,
    authenticated,
    service_role;
GRANT INSERT,
    UPDATE,
    DELETE ON TABLE public.enforcement_events TO authenticated,
    service_role;
DROP POLICY IF EXISTS enforcement_events_read ON public.enforcement_events;
DROP POLICY IF EXISTS enforcement_events_write ON public.enforcement_events;
CREATE POLICY enforcement_events_read ON public.enforcement_events FOR
SELECT USING (
        auth.role() IN ('anon', 'authenticated', 'service_role')
    );
CREATE POLICY enforcement_events_write ON public.enforcement_events FOR ALL USING (auth.role() IN ('authenticated', 'service_role')) WITH CHECK (auth.role() IN ('authenticated', 'service_role'));
-- ============================================================================
-- SECTION 4: public.plaintiff_contacts column additions
-- Add missing columns needed by enforcement views
-- ============================================================================
-- Add phone column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'phone'
) THEN
ALTER TABLE public.plaintiff_contacts
ADD COLUMN phone text;
RAISE NOTICE 'Added public.plaintiff_contacts.phone';
END IF;
END $$;
-- Add email column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'email'
) THEN
ALTER TABLE public.plaintiff_contacts
ADD COLUMN email text;
RAISE NOTICE 'Added public.plaintiff_contacts.email';
END IF;
END $$;
-- Add name column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'name'
) THEN
ALTER TABLE public.plaintiff_contacts
ADD COLUMN name text;
RAISE NOTICE 'Added public.plaintiff_contacts.name';
END IF;
END $$;
-- Add role column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'role'
) THEN
ALTER TABLE public.plaintiff_contacts
ADD COLUMN role text;
RAISE NOTICE 'Added public.plaintiff_contacts.role';
END IF;
END $$;
-- Add kind column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'kind'
) THEN
ALTER TABLE public.plaintiff_contacts
ADD COLUMN kind text;
RAISE NOTICE 'Added public.plaintiff_contacts.kind';
END IF;
END $$;
-- Add value column
DO $$ BEGIN IF NOT EXISTS (
    SELECT 1
    FROM information_schema.columns
    WHERE table_schema = 'public'
        AND table_name = 'plaintiff_contacts'
        AND column_name = 'value'
) THEN
ALTER TABLE public.plaintiff_contacts
ADD COLUMN value text;
RAISE NOTICE 'Added public.plaintiff_contacts.value';
END IF;
END $$;
-- ============================================================================
-- SECTION 5: Verification queries
-- ============================================================================
DO $$
DECLARE v_job_queue_ok boolean;
v_enforcement_ok boolean;
v_contacts_ok boolean;
BEGIN -- Check ops.job_queue
SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'ops'
            AND table_name = 'job_queue'
            AND column_name = 'locked_at'
    ) INTO v_job_queue_ok;
-- Check enforcement_cases
SELECT EXISTS (
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = 'public'
            AND table_name = 'enforcement_cases'
    ) INTO v_enforcement_ok;
-- Check plaintiff_contacts
SELECT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
            AND table_name = 'plaintiff_contacts'
            AND column_name = 'phone'
    ) INTO v_contacts_ok;
RAISE NOTICE 'Schema parity verification:';
RAISE NOTICE '  ops.job_queue.locked_at: %',
v_job_queue_ok;
RAISE NOTICE '  public.enforcement_cases: %',
v_enforcement_ok;
RAISE NOTICE '  public.plaintiff_contacts.phone: %',
v_contacts_ok;
IF NOT (
    v_job_queue_ok
    AND v_enforcement_ok
    AND v_contacts_ok
) THEN RAISE EXCEPTION 'Schema parity verification failed';
END IF;
END $$;
COMMIT;