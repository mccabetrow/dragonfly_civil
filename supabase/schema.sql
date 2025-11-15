





































-- =====================================================
-- Dragonfly Civil Judgment Enforcement Database Schema
-- Provisioning DDL (idempotent where possible)
-- =====================================================

-- Extensions ---------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";
CREATE EXTENSION IF NOT EXISTS "pgmq";

-- Schemas -----------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS judgments;
CREATE SCHEMA IF NOT EXISTS ingestion;

-- Utility functions -------------------------------------------------------
CREATE OR REPLACE FUNCTION public.touch_updated_at() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
	NEW.updated_at = NOW();
	RETURN NEW;
END;
$$;

-- ========================================================================
-- ingestion.runs
-- ========================================================================
CREATE TABLE IF NOT EXISTS ingestion.runs (
	id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	source          text,
	source_name     text,
	run_key         text UNIQUE,
	status          text DEFAULT 'running',
	started_at      timestamptz DEFAULT NOW(),
	finished_at     timestamptz,
	rows_ok         integer DEFAULT 0,
	rows_err        integer DEFAULT 0,
	records_processed integer DEFAULT 0,
	records_inserted  integer DEFAULT 0,
	records_updated   integer DEFAULT 0,
	error_log       jsonb,
	notes           jsonb,
	metadata        jsonb,
	created_at      timestamptz NOT NULL DEFAULT NOW(),
	updated_at      timestamptz NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_source_started
	ON ingestion.runs (COALESCE(source_name, source), started_at DESC);

DROP TRIGGER IF EXISTS trg_runs_touch_updated ON ingestion.runs;
CREATE TRIGGER trg_runs_touch_updated
	BEFORE UPDATE ON ingestion.runs
	FOR EACH ROW
	EXECUTE FUNCTION public.touch_updated_at();

-- ========================================================================
-- judgments.cases
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.cases (
	id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	source           text,
	external_id      text,
	state            text NOT NULL,
	county           text NOT NULL,
	court_name       text,
	docket_number    text NOT NULL,
	case_number      text,
	case_type        text,
	case_status      text,
	case_url         text,
	filing_date      date,
	owner            text,
	metadata         jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE SET NULL,
	created_at       timestamptz NOT NULL DEFAULT NOW(),
	updated_at       timestamptz NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_state_county_docket
	ON judgments.cases (state, county, docket_number);

CREATE INDEX IF NOT EXISTS ix_cases_external_id
	ON judgments.cases (external_id);

ALTER TABLE judgments.cases
	ADD COLUMN IF NOT EXISTS case_type text,
	ADD COLUMN IF NOT EXISTS case_status text,
	ADD COLUMN IF NOT EXISTS case_url text,
	ADD COLUMN IF NOT EXISTS filing_date date,
	ADD COLUMN IF NOT EXISTS owner text,
	ADD COLUMN IF NOT EXISTS metadata jsonb;

CREATE OR REPLACE FUNCTION judgments.apply_case_defaults() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
	IF NEW.docket_number IS NULL OR btrim(NEW.docket_number) = '' THEN
		NEW.docket_number := COALESCE(NULLIF(NEW.case_number, ''), NEW.external_id);
	END IF;
	IF NEW.docket_number IS NULL OR btrim(NEW.docket_number) = '' THEN
		RAISE EXCEPTION 'docket_number is required';
	END IF;
	IF NEW.case_number IS NULL OR btrim(NEW.case_number) = '' THEN
		NEW.case_number := NEW.docket_number;
	END IF;
	IF NEW.state IS NOT NULL THEN
		NEW.state := upper(trim(NEW.state));
	END IF;
	IF NEW.county IS NOT NULL THEN
		NEW.county := initcap(trim(NEW.county));
	END IF;
	RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_cases_defaults ON judgments.cases;
CREATE TRIGGER trg_cases_defaults
	BEFORE INSERT OR UPDATE ON judgments.cases
	FOR EACH ROW
	EXECUTE FUNCTION judgments.apply_case_defaults();

DROP TRIGGER IF EXISTS trg_cases_touch_updated ON judgments.cases;
CREATE TRIGGER trg_cases_touch_updated
	BEFORE UPDATE ON judgments.cases
	FOR EACH ROW
	EXECUTE FUNCTION public.touch_updated_at();

-- ========================================================================
-- judgments.judgments
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.judgments (
	id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	case_id          uuid NOT NULL REFERENCES judgments.cases(id) ON DELETE CASCADE,
	judgment_number  text,
	judgment_date    date NOT NULL,
	amount           numeric(12, 2) NOT NULL,
	amount_awarded   numeric(12, 2),
	amount_remaining numeric(12, 2),
	interest_rate    numeric(5, 2),
	judgment_type    text,
	status           text NOT NULL DEFAULT 'unsatisfied',
	judgment_status  text DEFAULT 'unsatisfied',
	renewal_date     date,
	expiration_date  date,
	metadata         jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE SET NULL,
	notes            text,
	created_at       timestamptz NOT NULL DEFAULT NOW(),
	updated_at       timestamptz NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_judgments_case_date_amount
	ON judgments.judgments (case_id, judgment_date, amount);

CREATE INDEX IF NOT EXISTS ix_judgments_case
	ON judgments.judgments (case_id);

ALTER TABLE judgments.judgments
	ADD COLUMN IF NOT EXISTS amount_awarded numeric(12, 2),
	ADD COLUMN IF NOT EXISTS amount_remaining numeric(12, 2),
	ADD COLUMN IF NOT EXISTS interest_rate numeric(5, 2),
	ADD COLUMN IF NOT EXISTS judgment_type text,
	ADD COLUMN IF NOT EXISTS status text DEFAULT 'unsatisfied',
	ADD COLUMN IF NOT EXISTS judgment_status text DEFAULT 'unsatisfied',
	ADD COLUMN IF NOT EXISTS renewal_date date,
	ADD COLUMN IF NOT EXISTS expiration_date date,
	ADD COLUMN IF NOT EXISTS metadata jsonb,
	ADD COLUMN IF NOT EXISTS notes text;

CREATE OR REPLACE FUNCTION judgments.apply_judgment_defaults() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
	IF NEW.amount IS NULL AND NEW.amount_awarded IS NOT NULL THEN
		NEW.amount := NEW.amount_awarded;
	ELSIF NEW.amount_awarded IS NULL AND NEW.amount IS NOT NULL THEN
		NEW.amount_awarded := NEW.amount;
	END IF;
	IF NEW.amount_remaining IS NULL THEN
		NEW.amount_remaining := NEW.amount_awarded;
	END IF;
	RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_judgments_defaults ON judgments.judgments;
CREATE TRIGGER trg_judgments_defaults
	BEFORE INSERT OR UPDATE ON judgments.judgments
	FOR EACH ROW
	EXECUTE FUNCTION judgments.apply_judgment_defaults();

DROP TRIGGER IF EXISTS trg_judgments_touch_updated ON judgments.judgments;
CREATE TRIGGER trg_judgments_touch_updated
	BEFORE UPDATE ON judgments.judgments
	FOR EACH ROW
	EXECUTE FUNCTION public.touch_updated_at();

-- ========================================================================
-- judgments.parties
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.parties (
	id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	case_id          uuid NOT NULL REFERENCES judgments.cases(id) ON DELETE CASCADE,
	role             text NOT NULL CHECK (role IN ('plaintiff', 'defendant')),
	party_role       text,
	party_type       text,
	name             text,
	name_full        text,
	name_first       text,
	name_last        text,
	name_business    text,
	name_normalized  text,
	address_raw      text,
	address_line1    text,
	address_line2    text,
	city             text,
	state            text,
	zip              text,
	is_business      boolean DEFAULT FALSE,
	email            text,
	phone            text,
	metadata         jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE SET NULL,
	created_at       timestamptz NOT NULL DEFAULT NOW(),
	updated_at       timestamptz NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_parties_case_role_name
	ON judgments.parties (case_id, role, COALESCE(name_normalized, name));

CREATE INDEX IF NOT EXISTS ix_parties_case
	ON judgments.parties (case_id);

ALTER TABLE judgments.parties
	ADD COLUMN IF NOT EXISTS party_role text,
	ADD COLUMN IF NOT EXISTS party_type text,
	ADD COLUMN IF NOT EXISTS name text,
	ADD COLUMN IF NOT EXISTS name_full text,
	ADD COLUMN IF NOT EXISTS name_first text,
	ADD COLUMN IF NOT EXISTS name_last text,
	ADD COLUMN IF NOT EXISTS name_business text,
	ADD COLUMN IF NOT EXISTS name_normalized text,
	ADD COLUMN IF NOT EXISTS address_line1 text,
	ADD COLUMN IF NOT EXISTS address_line2 text,
	ADD COLUMN IF NOT EXISTS city text,
	ADD COLUMN IF NOT EXISTS state text,
	ADD COLUMN IF NOT EXISTS zip text,
	ADD COLUMN IF NOT EXISTS is_business boolean DEFAULT FALSE,
	ADD COLUMN IF NOT EXISTS email text,
	ADD COLUMN IF NOT EXISTS phone text,
	ADD COLUMN IF NOT EXISTS metadata jsonb;

CREATE OR REPLACE FUNCTION judgments.apply_party_defaults() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
	IF NEW.role IS NULL THEN
		NEW.role := lower(COALESCE(NEW.party_role, NEW.party_type));
	END IF;
	IF NEW.role NOT IN ('plaintiff', 'defendant') THEN
		NEW.role := 'defendant';
	END IF;
	IF NEW.name IS NULL THEN
		NEW.name := COALESCE(NEW.name_full, NEW.name);
	END IF;
	IF NEW.name_full IS NULL THEN
		NEW.name_full := NEW.name;
	END IF;
	IF NEW.name_normalized IS NULL AND NEW.name_full IS NOT NULL THEN
		NEW.name_normalized := regexp_replace(lower(NEW.name_full), '[^a-z0-9]', '', 'g');
	END IF;
	IF NEW.address_raw IS NULL AND NEW.address_line1 IS NOT NULL THEN
		NEW.address_raw := trim(concat_ws(' ', NEW.address_line1, NEW.address_line2, NEW.city, NEW.state, NEW.zip));
	END IF;
	RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_parties_defaults ON judgments.parties;
CREATE TRIGGER trg_parties_defaults
	BEFORE INSERT OR UPDATE ON judgments.parties
	FOR EACH ROW
	EXECUTE FUNCTION judgments.apply_party_defaults();

DROP TRIGGER IF EXISTS trg_parties_touch_updated ON judgments.parties;
CREATE TRIGGER trg_parties_touch_updated
	BEFORE UPDATE ON judgments.parties
	FOR EACH ROW
	EXECUTE FUNCTION public.touch_updated_at();

-- ========================================================================
-- judgments.contacts
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.contacts (
	id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	party_id         uuid NOT NULL REFERENCES judgments.parties(id) ON DELETE CASCADE,
	phone_raw        text,
	phone_e164       text,
	email            text,
	preferred_channel text,
	contact_type     text,
	contact_value    text,
	contact_label    text,
	is_verified      boolean DEFAULT FALSE,
	is_primary       boolean DEFAULT FALSE,
	source           text,
	last_verified_at timestamptz,
	notes            text,
	metadata         jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE SET NULL,
	created_at       timestamptz NOT NULL DEFAULT NOW(),
	updated_at       timestamptz NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_party_phone
	ON judgments.contacts (party_id, phone_e164)
	WHERE phone_e164 IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_party_email
	ON judgments.contacts (party_id, email)
	WHERE email IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_type_value
	ON judgments.contacts (party_id, contact_type, contact_value)
	WHERE contact_type IS NOT NULL AND contact_value IS NOT NULL;

ALTER TABLE judgments.contacts
	ADD COLUMN IF NOT EXISTS phone_raw text,
	ADD COLUMN IF NOT EXISTS phone_e164 text,
	ADD COLUMN IF NOT EXISTS email text,
	ADD COLUMN IF NOT EXISTS preferred_channel text,
	ADD COLUMN IF NOT EXISTS contact_type text,
	ADD COLUMN IF NOT EXISTS contact_value text,
	ADD COLUMN IF NOT EXISTS contact_label text,
	ADD COLUMN IF NOT EXISTS is_verified boolean DEFAULT FALSE,
	ADD COLUMN IF NOT EXISTS is_primary boolean DEFAULT FALSE,
	ADD COLUMN IF NOT EXISTS source text,
	ADD COLUMN IF NOT EXISTS last_verified_at timestamptz,
	ADD COLUMN IF NOT EXISTS notes text,
	ADD COLUMN IF NOT EXISTS metadata jsonb;

CREATE OR REPLACE FUNCTION judgments.apply_contact_defaults() RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
	IF NEW.contact_type IS NULL THEN
		IF NEW.phone_e164 IS NOT NULL OR NEW.phone_raw IS NOT NULL THEN
			NEW.contact_type := 'phone';
		ELSIF NEW.email IS NOT NULL THEN
			NEW.contact_type := 'email';
		END IF;
	END IF;
	IF NEW.contact_value IS NULL THEN
		IF NEW.contact_type = 'phone' THEN
			NEW.contact_value := COALESCE(NEW.phone_e164, NEW.phone_raw);
		ELSIF NEW.contact_type = 'email' THEN
			NEW.contact_value := NEW.email;
		END IF;
	END IF;
	IF NEW.contact_type = 'phone' AND NEW.phone_e164 IS NULL THEN
		NEW.phone_e164 := NEW.contact_value;
	END IF;
	IF NEW.contact_type = 'email' AND NEW.email IS NULL THEN
		NEW.email := NEW.contact_value;
	END IF;
	RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_contacts_defaults ON judgments.contacts;
CREATE TRIGGER trg_contacts_defaults
	BEFORE INSERT OR UPDATE ON judgments.contacts
	FOR EACH ROW
	EXECUTE FUNCTION judgments.apply_contact_defaults();

DROP TRIGGER IF EXISTS trg_contacts_touch_updated ON judgments.contacts;
CREATE TRIGGER trg_contacts_touch_updated
	BEFORE UPDATE ON judgments.contacts
	FOR EACH ROW
	EXECUTE FUNCTION public.touch_updated_at();

-- ========================================================================
-- judgments.foil_responses
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.foil_responses (
	id            bigserial PRIMARY KEY,
	case_id       uuid NOT NULL REFERENCES judgments.cases(case_id) ON DELETE CASCADE,
	created_at    timestamptz NOT NULL DEFAULT timezone('utc', now()),
	received_date date,
	agency        text,
	payload       jsonb NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_judgments_foil_responses_case_id
	ON judgments.foil_responses (case_id);
CREATE INDEX IF NOT EXISTS idx_judgments_foil_responses_agency_date
	ON judgments.foil_responses (agency, received_date);

ALTER TABLE judgments.foil_responses ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
	IF NOT EXISTS (
		SELECT 1
		FROM pg_policies
		WHERE schemaname = 'judgments'
		  AND tablename = 'foil_responses'
		  AND policyname = 'service_foil_responses_rw'
	) THEN
		CREATE POLICY service_foil_responses_rw ON judgments.foil_responses
			FOR ALL
			USING (auth.role() = 'service_role')
			WITH CHECK (auth.role() = 'service_role');
	END IF;
END;
$$;

REVOKE ALL ON judgments.foil_responses FROM public;
REVOKE ALL ON judgments.foil_responses FROM anon;
REVOKE ALL ON judgments.foil_responses FROM authenticated;

GRANT SELECT, INSERT, UPDATE, DELETE ON judgments.foil_responses TO service_role;

DO $$
BEGIN
	IF EXISTS (
		SELECT 1
		FROM pg_class c
		JOIN pg_namespace n ON n.oid = c.relnamespace
		WHERE c.relkind = 'S'
		  AND n.nspname = 'judgments'
		  AND c.relname = 'foil_responses_id_seq'
	) THEN
		EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE judgments.foil_responses_id_seq TO service_role';
	END IF;
END;
$$;

-- ========================================================================
-- public.foil_responses
-- ========================================================================
CREATE OR REPLACE VIEW public.foil_responses AS
SELECT
	id,
	case_id,
	created_at,
	received_date,
	agency,
	payload
FROM judgments.foil_responses;

REVOKE ALL ON public.foil_responses FROM public;
REVOKE ALL ON public.foil_responses FROM anon;
REVOKE ALL ON public.foil_responses FROM authenticated;
GRANT SELECT ON public.foil_responses TO anon;
GRANT SELECT ON public.foil_responses TO authenticated;
GRANT SELECT ON public.foil_responses TO service_role;

-- ========================================================================
-- judgments.v_collectability_snapshot
-- ========================================================================
CREATE OR REPLACE VIEW judgments.v_collectability_snapshot AS
WITH latest_enrichment AS (
	SELECT
		er.case_id,
		er.created_at,
		er.status,
		ROW_NUMBER() OVER (
			PARTITION BY er.case_id
			ORDER BY er.created_at DESC, er.id DESC
		) AS row_num
	FROM judgments.enrichment_runs er
)
SELECT
	c.case_id,
	c.case_number,
	c.amount_awarded AS judgment_amount,
	c.judgment_date,
	CASE
		WHEN c.judgment_date IS NOT NULL THEN (CURRENT_DATE - c.judgment_date)
		ELSE NULL
	END AS age_days,
	le.created_at AS last_enriched_at,
	le.status AS last_enrichment_status,
	CASE
		WHEN COALESCE(c.amount_awarded, 0) >= 3000
			 AND c.judgment_date IS NOT NULL
			 AND (CURRENT_DATE - c.judgment_date) <= 365 THEN 'A'
		WHEN (COALESCE(c.amount_awarded, 0) BETWEEN 1000 AND 2999)
		  OR (c.judgment_date IS NOT NULL
			  AND (CURRENT_DATE - c.judgment_date) BETWEEN 366 AND 1095)
			THEN 'B'
		ELSE 'C'
	END AS collectability_tier
FROM judgments.cases c
LEFT JOIN latest_enrichment le ON le.case_id = c.case_id AND le.row_num = 1;

GRANT SELECT ON judgments.v_collectability_snapshot TO service_role;

-- ========================================================================
-- public.v_collectability_snapshot
-- ========================================================================
CREATE OR REPLACE VIEW public.v_collectability_snapshot AS
SELECT *
FROM judgments.v_collectability_snapshot;

REVOKE ALL ON public.v_collectability_snapshot FROM public;
REVOKE ALL ON public.v_collectability_snapshot FROM anon;
REVOKE ALL ON public.v_collectability_snapshot FROM authenticated;

GRANT SELECT ON public.v_collectability_snapshot TO anon;
GRANT SELECT ON public.v_collectability_snapshot TO authenticated;
GRANT SELECT ON public.v_collectability_snapshot TO service_role;

-- Ensure pgmq queues exist for the worker pipeline
DO $$
DECLARE
	queue_name text;
	queue_regclass text;
BEGIN
	FOR queue_name IN SELECT unnest(ARRAY['enrich', 'outreach', 'enforce']) LOOP
		queue_regclass := format('pgmq.q_%I', queue_name);
		IF to_regclass(queue_regclass) IS NOT NULL THEN
			CONTINUE;
		END IF;

		BEGIN
			PERFORM pgmq.create(queue_name);
		EXCEPTION
			WHEN undefined_function THEN
				BEGIN
					PERFORM pgmq.create_queue(queue_name);
				EXCEPTION
					WHEN undefined_function THEN
						RAISE NOTICE 'pgmq.create and pgmq.create_queue unavailable; queue % not created', queue_name;
						CONTINUE;
					END;
			WHEN others THEN
				IF SQLSTATE IN ('42710', '42P07') THEN
					CONTINUE;
				ELSE
					RAISE;
				END IF;
		END;

		IF to_regclass(queue_regclass) IS NULL THEN
			RAISE NOTICE 'Queue % still missing after create attempt', queue_name;
		END IF;
	END LOOP;
END;
$$;

-- ========================================================================
-- public.dequeue_job
-- ========================================================================
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
	msg record;
BEGIN
	IF kind IS NULL OR length(trim(kind)) = 0 THEN
		raise exception 'dequeue_job: missing kind';
	END IF;

	IF kind NOT IN ('enrich', 'outreach', 'enforce') THEN
		raise exception 'dequeue_job: unsupported kind %', kind;
	END IF;

	SELECT *
	  INTO msg
	  FROM pgmq.read(kind, 1, 30);

	IF msg IS NULL THEN
		RETURN NULL;
	END IF;

	RETURN jsonb_build_object(
		'msg_id', msg.msg_id,
		'vt', msg.vt,
		'read_ct', msg.read_ct,
		'enqueued_at', msg.enqueued_at,
		'payload', msg.message,
		'body', msg.message
	);
END;
$$;

GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;

