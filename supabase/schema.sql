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
CREATE OR REPLACE FUNCTION public.touch_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN NEW.updated_at = NOW();
RETURN NEW;
END;
$$;
-- Stub RPCs -------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.spawn_enforcement_flow(case_number text, template_code text) RETURNS text [] LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
	judgments AS $$ BEGIN -- Phase 1 stub: return an empty task list while acknowledging the request.
	PERFORM 1;
RETURN ARRAY []::text [];
END;
$$;
GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.spawn_enforcement_flow(text, text) TO anon;
-- ========================================================================
-- public.enforcement task enums
-- ========================================================================
CREATE TYPE IF NOT EXISTS public.enforcement_task_kind AS ENUM (
	'enforcement_phone_attempt',
	'enforcement_phone_follow_up',
	'enforcement_mailer',
	'enforcement_demand_letter',
	'enforcement_wage_garnishment_prep',
	'enforcement_bank_levy_prep',
	'enforcement_skiptrace_refresh'
);
CREATE TYPE IF NOT EXISTS public.enforcement_task_severity AS ENUM ('low', 'medium', 'high');
-- ========================================================================
-- ingestion.runs
-- ========================================================================
CREATE TABLE IF NOT EXISTS ingestion.runs (
	id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	source text,
	source_name text,
	run_key text UNIQUE,
	status text DEFAULT 'running',
	started_at timestamptz DEFAULT NOW(),
	finished_at timestamptz,
	rows_ok integer DEFAULT 0,
	rows_err integer DEFAULT 0,
	records_processed integer DEFAULT 0,
	records_inserted integer DEFAULT 0,
	records_updated integer DEFAULT 0,
	error_log jsonb,
	notes jsonb,
	metadata jsonb,
	created_at timestamptz NOT NULL DEFAULT NOW(),
	updated_at timestamptz NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_runs_source_started ON ingestion.runs (COALESCE(source_name, source), started_at DESC);
DROP TRIGGER IF EXISTS trg_runs_touch_updated ON ingestion.runs;
CREATE TRIGGER trg_runs_touch_updated BEFORE
UPDATE ON ingestion.runs FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
-- ========================================================================
-- public.import_runs
-- ========================================================================
CREATE TABLE IF NOT EXISTS public.import_runs (
	id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	import_kind text NOT NULL,
	source_system text NOT NULL,
	source text,
	source_reference text,
	file_name text,
	storage_path text,
	status text NOT NULL DEFAULT 'pending',
	total_rows integer,
	inserted_rows integer,
	skipped_rows integer,
	error_rows integer,
	started_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
	finished_at timestamptz,
	created_by text,
	metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
	created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
	updated_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);
ALTER TABLE public.import_runs
ALTER COLUMN status
SET DEFAULT 'pending',
	ALTER COLUMN metadata
SET DEFAULT '{}'::jsonb,
	ALTER COLUMN metadata
SET NOT NULL,
	ALTER COLUMN started_at
SET DEFAULT timezone('utc', now()),
	ALTER COLUMN started_at
SET NOT NULL,
	ALTER COLUMN created_at
SET DEFAULT timezone('utc', now()),
	ALTER COLUMN created_at
SET NOT NULL,
	ALTER COLUMN updated_at
SET DEFAULT timezone('utc', now()),
	ALTER COLUMN updated_at
SET NOT NULL;
DO $$ BEGIN IF NOT EXISTS (
	SELECT 1
	FROM pg_constraint
	WHERE conrelid = 'public.import_runs'::regclass
		AND conname = 'import_runs_total_rows_nonneg'
) THEN
ALTER TABLE public.import_runs
ADD CONSTRAINT import_runs_total_rows_nonneg CHECK (
		total_rows IS NULL
		OR total_rows >= 0
	);
END IF;
IF NOT EXISTS (
	SELECT 1
	FROM pg_constraint
	WHERE conrelid = 'public.import_runs'::regclass
		AND conname = 'import_runs_inserted_rows_nonneg'
) THEN
ALTER TABLE public.import_runs
ADD CONSTRAINT import_runs_inserted_rows_nonneg CHECK (
		inserted_rows IS NULL
		OR inserted_rows >= 0
	);
END IF;
IF NOT EXISTS (
	SELECT 1
	FROM pg_constraint
	WHERE conrelid = 'public.import_runs'::regclass
		AND conname = 'import_runs_skipped_rows_nonneg'
) THEN
ALTER TABLE public.import_runs
ADD CONSTRAINT import_runs_skipped_rows_nonneg CHECK (
		skipped_rows IS NULL
		OR skipped_rows >= 0
	);
END IF;
IF NOT EXISTS (
	SELECT 1
	FROM pg_constraint
	WHERE conrelid = 'public.import_runs'::regclass
		AND conname = 'import_runs_error_rows_nonneg'
) THEN
ALTER TABLE public.import_runs
ADD CONSTRAINT import_runs_error_rows_nonneg CHECK (
		error_rows IS NULL
		OR error_rows >= 0
	);
END IF;
END $$;
CREATE INDEX IF NOT EXISTS idx_import_runs_started_at ON public.import_runs (started_at DESC);
CREATE INDEX IF NOT EXISTS idx_import_runs_status ON public.import_runs (status);
DROP TRIGGER IF EXISTS trg_import_runs_touch ON public.import_runs;
CREATE TRIGGER trg_import_runs_touch BEFORE
UPDATE ON public.import_runs FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
ALTER TABLE public.import_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS import_runs_service_rw ON public.import_runs;
CREATE POLICY import_runs_service_rw ON public.import_runs FOR ALL USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
REVOKE ALL ON public.import_runs
FROM public;
REVOKE ALL ON public.import_runs
FROM anon;
REVOKE ALL ON public.import_runs
FROM authenticated;
GRANT SELECT,
	INSERT,
	UPDATE,
	DELETE ON public.import_runs TO service_role;
-- ========================================================================
-- judgments.cases
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.cases (
	case_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	-- expose "id" for PostgREST clients while keeping case_id as the canonical key
	id uuid UNIQUE GENERATED ALWAYS AS (case_id) STORED,
	org_id uuid NOT NULL DEFAULT gen_random_uuid(),
	source text NOT NULL DEFAULT 'unknown',
	source_system text,
	external_id text,
	state text,
	county text,
	court_name text,
	court text,
	docket_number text,
	case_number text NOT NULL,
	title text,
	case_type text,
	case_status text,
	case_url text,
	filing_date date,
	judgment_date date,
	amount_awarded numeric(14, 2),
	currency text DEFAULT 'USD',
	owner text,
	metadata jsonb,
	collectability_score numeric(5, 2) DEFAULT 0,
	raw jsonb NOT NULL DEFAULT '{}'::jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE
	SET NULL,
		created_at timestamptz NOT NULL DEFAULT NOW(),
		updated_at timestamptz NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_state_county_docket ON judgments.cases (state, county, docket_number);
CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_org_src_num ON judgments.cases (org_id, source, case_number);
CREATE INDEX IF NOT EXISTS ix_cases_external_id ON judgments.cases (external_id);
ALTER TABLE judgments.cases
ADD COLUMN IF NOT EXISTS case_type text,
	ADD COLUMN IF NOT EXISTS case_status text,
	ADD COLUMN IF NOT EXISTS case_url text,
	ADD COLUMN IF NOT EXISTS filing_date date,
	ADD COLUMN IF NOT EXISTS owner text,
	ADD COLUMN IF NOT EXISTS metadata jsonb,
	ADD COLUMN IF NOT EXISTS collectability_score numeric(5, 2) DEFAULT 0;
CREATE OR REPLACE FUNCTION judgments.apply_case_defaults() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.docket_number IS NULL
	OR btrim(NEW.docket_number) = '' THEN NEW.docket_number := COALESCE(NULLIF(NEW.case_number, ''), NEW.external_id);
END IF;
IF NEW.docket_number IS NULL
OR btrim(NEW.docket_number) = '' THEN RAISE EXCEPTION 'docket_number is required';
END IF;
IF NEW.case_number IS NULL
OR btrim(NEW.case_number) = '' THEN NEW.case_number := NEW.docket_number;
END IF;
IF NEW.state IS NOT NULL THEN NEW.state := upper(trim(NEW.state));
END IF;
IF NEW.county IS NOT NULL THEN NEW.county := initcap(trim(NEW.county));
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_cases_defaults ON judgments.cases;
CREATE TRIGGER trg_cases_defaults BEFORE
INSERT
	OR
UPDATE ON judgments.cases FOR EACH ROW EXECUTE FUNCTION judgments.apply_case_defaults();
DROP TRIGGER IF EXISTS trg_cases_touch_updated ON judgments.cases;
CREATE TRIGGER trg_cases_touch_updated BEFORE
UPDATE ON judgments.cases FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
-- ========================================================================
-- judgments.judgments
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.judgments (
	id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	case_id uuid NOT NULL REFERENCES judgments.cases(case_id) ON DELETE CASCADE,
	judgment_number text,
	judgment_date date NOT NULL,
	amount numeric(12, 2) NOT NULL,
	amount_awarded numeric(12, 2),
	amount_remaining numeric(12, 2),
	interest_rate numeric(5, 2),
	judgment_type text,
	status text NOT NULL DEFAULT 'unsatisfied',
	judgment_status text DEFAULT 'unsatisfied',
	renewal_date date,
	expiration_date date,
	metadata jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE
	SET NULL,
		notes text,
		created_at timestamptz NOT NULL DEFAULT NOW(),
		updated_at timestamptz NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_judgments_case_date_amount ON judgments.judgments (case_id, judgment_date, amount);
CREATE INDEX IF NOT EXISTS ix_judgments_case ON judgments.judgments (case_id);
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
CREATE OR REPLACE FUNCTION judgments.apply_judgment_defaults() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.amount IS NULL
	AND NEW.amount_awarded IS NOT NULL THEN NEW.amount := NEW.amount_awarded;
ELSIF NEW.amount_awarded IS NULL
AND NEW.amount IS NOT NULL THEN NEW.amount_awarded := NEW.amount;
END IF;
IF NEW.amount_remaining IS NULL THEN NEW.amount_remaining := NEW.amount_awarded;
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_judgments_defaults ON judgments.judgments;
CREATE TRIGGER trg_judgments_defaults BEFORE
INSERT
	OR
UPDATE ON judgments.judgments FOR EACH ROW EXECUTE FUNCTION judgments.apply_judgment_defaults();
DROP TRIGGER IF EXISTS trg_judgments_touch_updated ON judgments.judgments;
CREATE TRIGGER trg_judgments_touch_updated BEFORE
UPDATE ON judgments.judgments FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
-- ========================================================================
-- judgments.parties
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.parties (
	id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	case_id uuid NOT NULL REFERENCES judgments.cases(case_id) ON DELETE CASCADE,
	role text NOT NULL CHECK (role IN ('plaintiff', 'defendant')),
	party_role text,
	party_type text,
	name text,
	name_full text,
	name_first text,
	name_last text,
	name_business text,
	name_normalized text,
	address_raw text,
	address_line1 text,
	address_line2 text,
	city text,
	state text,
	zip text,
	is_business boolean DEFAULT FALSE,
	email text,
	phone text,
	metadata jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE
	SET NULL,
		created_at timestamptz NOT NULL DEFAULT NOW(),
		updated_at timestamptz NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_parties_case_role_name ON judgments.parties (case_id, role, COALESCE(name_normalized, name));
CREATE INDEX IF NOT EXISTS ix_parties_case ON judgments.parties (case_id);
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
CREATE OR REPLACE FUNCTION judgments.apply_party_defaults() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.role IS NULL THEN NEW.role := lower(COALESCE(NEW.party_role, NEW.party_type));
END IF;
IF NEW.role NOT IN ('plaintiff', 'defendant') THEN NEW.role := 'defendant';
END IF;
IF NEW.name IS NULL THEN NEW.name := COALESCE(NEW.name_full, NEW.name);
END IF;
IF NEW.name_full IS NULL THEN NEW.name_full := NEW.name;
END IF;
IF NEW.name_normalized IS NULL
AND NEW.name_full IS NOT NULL THEN NEW.name_normalized := regexp_replace(lower(NEW.name_full), '[^a-z0-9]', '', 'g');
END IF;
IF NEW.address_raw IS NULL
AND NEW.address_line1 IS NOT NULL THEN NEW.address_raw := trim(
	concat_ws(
		' ',
		NEW.address_line1,
		NEW.address_line2,
		NEW.city,
		NEW.state,
		NEW.zip
	)
);
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_parties_defaults ON judgments.parties;
CREATE TRIGGER trg_parties_defaults BEFORE
INSERT
	OR
UPDATE ON judgments.parties FOR EACH ROW EXECUTE FUNCTION judgments.apply_party_defaults();
DROP TRIGGER IF EXISTS trg_parties_touch_updated ON judgments.parties;
CREATE TRIGGER trg_parties_touch_updated BEFORE
UPDATE ON judgments.parties FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
-- ========================================================================
-- judgments.contacts
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.contacts (
	id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
	party_id uuid NOT NULL REFERENCES judgments.parties(id) ON DELETE CASCADE,
	phone_raw text,
	phone_e164 text,
	email text,
	preferred_channel text,
	contact_type text,
	contact_value text,
	contact_label text,
	is_verified boolean DEFAULT FALSE,
	is_primary boolean DEFAULT FALSE,
	source text,
	last_verified_at timestamptz,
	notes text,
	metadata jsonb,
	ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE
	SET NULL,
		created_at timestamptz NOT NULL DEFAULT NOW(),
		updated_at timestamptz NOT NULL DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_party_phone ON judgments.contacts (party_id, phone_e164)
WHERE phone_e164 IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_party_email ON judgments.contacts (party_id, email)
WHERE email IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_type_value ON judgments.contacts (party_id, contact_type, contact_value)
WHERE contact_type IS NOT NULL
	AND contact_value IS NOT NULL;
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
CREATE OR REPLACE FUNCTION judgments.apply_contact_defaults() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN IF NEW.contact_type IS NULL THEN IF NEW.phone_e164 IS NOT NULL
	OR NEW.phone_raw IS NOT NULL THEN NEW.contact_type := 'phone';
ELSIF NEW.email IS NOT NULL THEN NEW.contact_type := 'email';
END IF;
END IF;
IF NEW.contact_value IS NULL THEN IF NEW.contact_type = 'phone' THEN NEW.contact_value := COALESCE(NEW.phone_e164, NEW.phone_raw);
ELSIF NEW.contact_type = 'email' THEN NEW.contact_value := NEW.email;
END IF;
END IF;
IF NEW.contact_type = 'phone'
AND NEW.phone_e164 IS NULL THEN NEW.phone_e164 := NEW.contact_value;
END IF;
IF NEW.contact_type = 'email'
AND NEW.email IS NULL THEN NEW.email := NEW.contact_value;
END IF;
RETURN NEW;
END;
$$;
DROP TRIGGER IF EXISTS trg_contacts_defaults ON judgments.contacts;
CREATE TRIGGER trg_contacts_defaults BEFORE
INSERT
	OR
UPDATE ON judgments.contacts FOR EACH ROW EXECUTE FUNCTION judgments.apply_contact_defaults();
DROP TRIGGER IF EXISTS trg_contacts_touch_updated ON judgments.contacts;
CREATE TRIGGER trg_contacts_touch_updated BEFORE
UPDATE ON judgments.contacts FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
-- ========================================================================
-- public.judgments RLS policies
-- ========================================================================
ALTER TABLE public.judgments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow public read-only access" ON public.judgments;
DROP POLICY IF EXISTS judgments_select_public ON public.judgments;
DROP POLICY IF EXISTS judgments_insert_service ON public.judgments;
DROP POLICY IF EXISTS judgments_update_service ON public.judgments;
DROP POLICY IF EXISTS judgments_delete_service ON public.judgments;
-- Allow dashboard readers (anon/authenticated) and workers to fetch judgments we expose.
CREATE POLICY judgments_select_public ON public.judgments FOR
SELECT USING (
		auth.role() IN ('anon', 'authenticated', 'service_role')
	);
-- Only the service role may insert new judgment rows via the API.
CREATE POLICY judgments_insert_service ON public.judgments FOR
INSERT WITH CHECK (auth.role() = 'service_role');
-- Only the service role may update existing judgment rows via the API.
CREATE POLICY judgments_update_service ON public.judgments FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
-- Only the service role may delete judgment rows via the API.
CREATE POLICY judgments_delete_service ON public.judgments FOR DELETE USING (auth.role() = 'service_role');
ALTER TABLE public.judgments
ADD COLUMN IF NOT EXISTS priority_level text NOT NULL DEFAULT 'normal',
	ADD COLUMN IF NOT EXISTS priority_level_updated_at timestamptz NOT NULL DEFAULT timezone('utc', now());
DO $$ BEGIN IF NOT EXISTS (
	SELECT 1
	FROM pg_constraint
	WHERE conrelid = 'public.judgments'::regclass
		AND contype = 'c'
		AND conname = 'judgments_priority_level_allowed'
) THEN
ALTER TABLE public.judgments
ADD CONSTRAINT judgments_priority_level_allowed CHECK (
		priority_level IN ('low', 'normal', 'high', 'urgent', 'on_hold')
	);
END IF;
END $$;
CREATE TABLE IF NOT EXISTS public.judgment_priority_history (
	id bigint GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
	judgment_id bigint NOT NULL REFERENCES public.judgments(id) ON DELETE CASCADE,
	priority_level text NOT NULL,
	note text,
	changed_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
	changed_by text
);
CREATE INDEX IF NOT EXISTS judgment_priority_history_judgment_id_idx ON public.judgment_priority_history (judgment_id, changed_at DESC);
-- ========================================================================
-- Enforcement stage RPC
-- ========================================================================
CREATE OR REPLACE FUNCTION public.set_enforcement_stage(
		_judgment_id bigint,
		_new_stage text,
		_note text DEFAULT NULL,
		_changed_by text DEFAULT NULL
	) RETURNS public.judgments LANGUAGE plpgsql SECURITY DEFINER AS $$
DECLARE allowed_stages constant text [] := ARRAY [
		'levy_issued',
		'payment_plan',
		'waiting_payment',
		'pre_enforcement',
		'paperwork_filed',
		'collected',
		'closed_no_recovery'
	];
normalized_stage text;
current_row public.judgments %ROWTYPE;
BEGIN IF _judgment_id IS NULL THEN raise exception 'judgment id is required';
END IF;
normalized_stage := trim(lower(coalesce(_new_stage, '')));
IF normalized_stage = '' THEN raise exception 'new stage is required';
END IF;
IF NOT normalized_stage = ANY(allowed_stages) THEN raise exception 'invalid enforcement stage: %',
_new_stage;
END IF;
SELECT * INTO current_row
FROM public.judgments
WHERE id = _judgment_id FOR
UPDATE;
IF NOT FOUND THEN raise exception 'judgment % not found',
_judgment_id;
END IF;
IF coalesce(current_row.enforcement_stage, '') = normalized_stage THEN RETURN current_row;
END IF;
UPDATE public.judgments
SET enforcement_stage = normalized_stage,
	enforcement_stage_updated_at = timezone('utc', now())
WHERE id = _judgment_id
RETURNING * INTO current_row;
INSERT INTO public.enforcement_history (judgment_id, stage, note, changed_at, changed_by)
VALUES (
		_judgment_id,
		normalized_stage,
		nullif(trim(_note), ''),
		timezone('utc', now()),
		nullif(trim(_changed_by), '')
	);
RETURN current_row;
END;
$$;
GRANT EXECUTE ON FUNCTION public.set_enforcement_stage(bigint, text, text, text) TO anon;
GRANT EXECUTE ON FUNCTION public.set_enforcement_stage(bigint, text, text, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.set_enforcement_stage(bigint, text, text, text) TO service_role;
-- ========================================================================
-- judgments.foil_responses
-- ========================================================================
CREATE TABLE IF NOT EXISTS judgments.foil_responses (
	id bigserial PRIMARY KEY,
	case_id uuid NOT NULL REFERENCES judgments.cases(case_id) ON DELETE CASCADE,
	created_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
	received_date date,
	agency text,
	payload jsonb NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_judgments_foil_responses_case_id ON judgments.foil_responses (case_id);
CREATE INDEX IF NOT EXISTS idx_judgments_foil_responses_agency_date ON judgments.foil_responses (agency, received_date);
ALTER TABLE judgments.foil_responses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS service_foil_responses_rw ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_select ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_insert ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_update ON judgments.foil_responses;
DROP POLICY IF EXISTS foil_responses_service_delete ON judgments.foil_responses;
-- Only workers (service role) may read the raw FOIL response payloads.
CREATE POLICY foil_responses_service_select ON judgments.foil_responses FOR
SELECT USING (auth.role() = 'service_role');
-- Restrict inserts to the service role to prevent public writes.
CREATE POLICY foil_responses_service_insert ON judgments.foil_responses FOR
INSERT WITH CHECK (auth.role() = 'service_role');
-- Restrict updates to the service role so audits remain trustworthy.
CREATE POLICY foil_responses_service_update ON judgments.foil_responses FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
-- Restrict deletes to the service role to avoid public data loss.
CREATE POLICY foil_responses_service_delete ON judgments.foil_responses FOR DELETE USING (auth.role() = 'service_role');
REVOKE ALL ON judgments.foil_responses
FROM public;
REVOKE ALL ON judgments.foil_responses
FROM anon;
REVOKE ALL ON judgments.foil_responses
FROM authenticated;
GRANT SELECT,
	INSERT,
	UPDATE,
	DELETE ON judgments.foil_responses TO service_role;
DO $$ BEGIN IF EXISTS (
	SELECT 1
	FROM pg_class c
		JOIN pg_namespace n ON n.oid = c.relnamespace
	WHERE c.relkind = 'S'
		AND n.nspname = 'judgments'
		AND c.relname = 'foil_responses_id_seq'
) THEN EXECUTE 'GRANT USAGE, SELECT ON SEQUENCE judgments.foil_responses_id_seq TO service_role';
END IF;
END;
$$;
-- ========================================================================
-- public.foil_responses
-- ========================================================================
CREATE OR REPLACE VIEW public.foil_responses AS
SELECT id,
	case_id,
	created_at,
	received_date,
	agency,
	payload
FROM judgments.foil_responses;
ALTER VIEW public.foil_responses
SET (security_invoker = true);
REVOKE ALL ON public.foil_responses
FROM public;
REVOKE ALL ON public.foil_responses
FROM anon;
REVOKE ALL ON public.foil_responses
FROM authenticated;
GRANT SELECT ON public.foil_responses TO anon;
GRANT SELECT ON public.foil_responses TO authenticated;
GRANT SELECT ON public.foil_responses TO service_role;
-- ========================================================================
-- judgments.enrichment_runs RLS policies
-- ========================================================================
ALTER TABLE judgments.enrichment_runs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS service_enrichment_runs_rw ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_select ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_insert ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_update ON judgments.enrichment_runs;
DROP POLICY IF EXISTS enrichment_runs_service_delete ON judgments.enrichment_runs;
-- Only backend workers may read individual enrichment run records.
CREATE POLICY enrichment_runs_service_select ON judgments.enrichment_runs FOR
SELECT USING (auth.role() = 'service_role');
-- Only backend workers may insert new enrichment runs.
CREATE POLICY enrichment_runs_service_insert ON judgments.enrichment_runs FOR
INSERT WITH CHECK (auth.role() = 'service_role');
-- Only backend workers may update enrichment runs.
CREATE POLICY enrichment_runs_service_update ON judgments.enrichment_runs FOR
UPDATE USING (auth.role() = 'service_role') WITH CHECK (auth.role() = 'service_role');
-- Only backend workers may delete enrichment runs.
CREATE POLICY enrichment_runs_service_delete ON judgments.enrichment_runs FOR DELETE USING (auth.role() = 'service_role');
-- ========================================================================
-- judgments.v_collectability_snapshot
-- ========================================================================
CREATE OR REPLACE VIEW judgments.v_collectability_snapshot AS WITH latest_enrichment AS (
		SELECT er.case_id,
			er.created_at,
			er.status,
			ROW_NUMBER() OVER (
				PARTITION BY er.case_id
				ORDER BY er.created_at DESC,
					er.id DESC
			) AS row_num
		FROM judgments.enrichment_runs er
	)
SELECT c.case_id,
	c.case_number,
	c.amount_awarded AS judgment_amount,
	c.judgment_date,
	CASE
		WHEN c.judgment_date IS NOT NULL THEN (CURRENT_DATE - c.judgment_date)
	END AS age_days,
	le.created_at AS last_enriched_at,
	le.status AS last_enrichment_status,
	CASE
		WHEN COALESCE(c.amount_awarded, 0) >= 3000
		AND c.judgment_date IS NOT NULL
		AND (CURRENT_DATE - c.judgment_date) <= 365 THEN 'A'
		WHEN (
			COALESCE(c.amount_awarded, 0) BETWEEN 1000 AND 2999
		)
		OR (
			c.judgment_date IS NOT NULL
			AND (CURRENT_DATE - c.judgment_date) BETWEEN 366 AND 1095
		) THEN 'B'
		ELSE 'C'
	END AS collectability_tier
FROM judgments.cases c
	LEFT JOIN latest_enrichment le ON le.case_id = c.case_id
	AND le.row_num = 1;
GRANT SELECT ON judgments.v_collectability_snapshot TO service_role;
-- ========================================================================
-- public.v_collectability_snapshot
-- ========================================================================
CREATE OR REPLACE VIEW public.v_collectability_snapshot AS
SELECT *
FROM judgments.v_collectability_snapshot;
REVOKE ALL ON public.v_collectability_snapshot
FROM public;
REVOKE ALL ON public.v_collectability_snapshot
FROM anon;
REVOKE ALL ON public.v_collectability_snapshot
FROM authenticated;
GRANT SELECT ON public.v_collectability_snapshot TO anon,
	authenticated,
	service_role;
ALTER VIEW public.v_collectability_snapshot
SET (security_invoker = true);
-- Ensure pgmq queues exist for the worker pipeline
DO $$
DECLARE queue_name text;
queue_regclass text;
BEGIN FOR queue_name IN
SELECT unnest(
		ARRAY ['enrich', 'outreach', 'enforce', 'case_copilot', 'collectability']
	) LOOP queue_regclass := format('pgmq.q_%I', queue_name);
IF to_regclass(queue_regclass) IS NOT NULL THEN CONTINUE;
END IF;
BEGIN PERFORM pgmq.create(queue_name);
EXCEPTION
WHEN undefined_function THEN BEGIN PERFORM pgmq.create_queue(queue_name);
EXCEPTION
WHEN undefined_function THEN RAISE NOTICE 'pgmq.create and pgmq.create_queue unavailable; queue % not created',
queue_name;
CONTINUE;
END;
WHEN others THEN IF SQLSTATE IN ('42710', '42P07') THEN CONTINUE;
ELSE RAISE;
END IF;
END;
IF to_regclass(queue_regclass) IS NULL THEN RAISE NOTICE 'Queue % still missing after create attempt',
queue_name;
END IF;
END LOOP;
END;
$$;
-- ========================================================================
-- public.queue_job
-- ========================================================================
CREATE OR REPLACE FUNCTION public.queue_job(payload jsonb) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
	pg_temp AS $$
DECLARE v_kind text;
v_idempotency_key text;
v_body jsonb;
BEGIN v_kind := payload->>'kind';
v_idempotency_key := payload->>'idempotency_key';
v_body := coalesce(payload->'payload', '{}'::jsonb);
IF v_kind IS NULL THEN raise exception 'queue_job: missing kind in payload';
END IF;
IF v_kind NOT IN (
	'enrich',
	'outreach',
	'enforce',
	'case_copilot',
	'collectability'
) THEN raise exception 'queue_job: unsupported kind %',
v_kind;
END IF;
IF v_idempotency_key IS NULL
OR length(v_idempotency_key) = 0 THEN raise exception 'queue_job: missing idempotency_key';
END IF;
RETURN pgmq.send(
	v_kind,
	jsonb_build_object(
		'payload',
		v_body,
		'idempotency_key',
		v_idempotency_key,
		'kind',
		v_kind,
		'enqueued_at',
		now()
	)
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO anon;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO authenticated;
GRANT EXECUTE ON FUNCTION public.queue_job(jsonb) TO service_role;
-- ========================================================================
-- public.pgmq_delete
-- ========================================================================
CREATE OR REPLACE FUNCTION public.pgmq_delete(queue_name text, msg_id bigint) RETURNS boolean LANGUAGE sql SECURITY DEFINER
SET search_path = public,
	pgmq AS $$
SELECT pgmq.delete(queue_name, msg_id);
$$;
GRANT EXECUTE ON FUNCTION public.pgmq_delete(text, bigint) TO anon;
GRANT EXECUTE ON FUNCTION public.pgmq_delete(text, bigint) TO authenticated;
GRANT EXECUTE ON FUNCTION public.pgmq_delete(text, bigint) TO service_role;
-- ========================================================================
-- public.dequeue_job
-- ========================================================================
CREATE OR REPLACE FUNCTION public.dequeue_job(kind text) RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
	pg_temp AS $$
DECLARE msg record;
BEGIN IF kind IS NULL
OR length(trim(kind)) = 0 THEN raise exception 'dequeue_job: missing kind';
END IF;
IF kind NOT IN (
	'enrich',
	'outreach',
	'enforce',
	'case_copilot',
	'collectability'
) THEN raise exception 'dequeue_job: unsupported kind %',
kind;
END IF;
SELECT * INTO msg
FROM pgmq.read(kind, 1, 30);
IF msg IS NULL THEN RETURN NULL;
END IF;
RETURN jsonb_build_object(
	'msg_id',
	msg.msg_id,
	'vt',
	msg.vt,
	'read_ct',
	msg.read_ct,
	'enqueued_at',
	msg.enqueued_at,
	'payload',
	msg.message,
	'body',
	msg.message
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.dequeue_job(text) TO service_role;
-- ========================================================================
-- Case Copilot view + RPC
-- ========================================================================
CREATE OR REPLACE VIEW public.v_case_copilot_latest AS WITH ranked AS (
		SELECT l.id,
			l.case_id,
			l.model,
			l.metadata,
			l.created_at,
			row_number() OVER (
				PARTITION BY l.case_id
				ORDER BY l.created_at DESC,
					l.id DESC
			) AS row_num
		FROM public.case_copilot_logs l
	)
SELECT ec.id AS case_id,
	COALESCE(ec.case_number, j.case_number) AS case_number,
	ec.judgment_id,
	ec.current_stage,
	ec.status AS case_status,
	ec.assigned_to,
	r.model,
	r.created_at AS generated_at,
	r.metadata->>'summary' AS summary,
	COALESCE(actions.actions_array, ARRAY []::text []) AS recommended_actions,
	COALESCE(
		r.metadata->'enforcement_suggestions',
		'[]'::jsonb
	) AS enforcement_suggestions,
	COALESCE(r.metadata->'draft_documents', '[]'::jsonb) AS draft_documents,
	NULLIF(r.metadata->'risk'->>'value', '')::int AS risk_value,
	r.metadata->'risk'->>'label' AS risk_label,
	COALESCE(risk.drivers_array, ARRAY []::text []) AS risk_drivers,
	COALESCE(r.metadata->'timeline_analysis', '[]'::jsonb) AS timeline_analysis,
	COALESCE(r.metadata->'contact_strategy', '[]'::jsonb) AS contact_strategy,
	r.metadata->>'status' AS invocation_status,
	r.metadata->>'error' AS error_message,
	r.metadata->>'env' AS env,
	r.metadata->>'duration_ms' AS duration_ms,
	r.id AS log_id
FROM ranked r
	JOIN public.enforcement_cases ec ON ec.id = r.case_id
	LEFT JOIN public.judgments j ON j.id = ec.judgment_id
	LEFT JOIN LATERAL (
		SELECT array_agg(elem) AS actions_array
		FROM jsonb_array_elements_text(r.metadata->'recommended_actions') elem
	) actions ON (r.metadata ? 'recommended_actions')
	LEFT JOIN LATERAL (
		SELECT array_agg(elem) AS drivers_array
		FROM jsonb_array_elements_text(r.metadata->'risk'->'drivers') elem
	) risk ON (r.metadata->'risk' ? 'drivers')
WHERE r.row_num = 1;
GRANT SELECT ON public.v_case_copilot_latest TO service_role;
DROP FUNCTION IF EXISTS public.request_case_copilot(uuid, text);
CREATE OR REPLACE FUNCTION public.request_case_copilot(p_case_id uuid, requested_by text DEFAULT NULL) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
	pg_temp AS $$
DECLARE v_case record;
v_payload jsonb;
v_key text;
BEGIN IF p_case_id IS NULL THEN raise exception 'request_case_copilot: case_id is required';
END IF;
SELECT ec.id,
	COALESCE(ec.case_number, j.case_number) AS case_number INTO v_case
FROM public.enforcement_cases ec
	JOIN public.judgments j ON j.id = ec.judgment_id
WHERE ec.id = p_case_id
LIMIT 1;
IF v_case.id IS NULL THEN raise exception 'request_case_copilot: case % not found',
p_case_id;
END IF;
v_payload := jsonb_build_object(
	'case_id',
	v_case.id::text,
	'case_number',
	v_case.case_number,
	'requested_by',
	NULLIF(trim(coalesce(requested_by, '')), ''),
	'requested_at',
	timezone('utc', now())
);
v_key := format(
	'case_copilot:%s:%s',
	v_case.id,
	encode(extensions.gen_random_bytes(6), 'hex')
);
RETURN public.queue_job(
	jsonb_build_object(
		'kind',
		'case_copilot',
		'idempotency_key',
		v_key,
		'payload',
		v_payload
	)
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(uuid, text) TO anon;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(uuid, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.request_case_copilot(uuid, text) TO service_role;
-- ========================================================================
-- public.score_case_collectability
-- ========================================================================
CREATE OR REPLACE FUNCTION public.score_case_collectability(
		p_case_id uuid,
		p_force boolean DEFAULT false,
		p_requested_by text DEFAULT NULL
	) RETURNS bigint LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
	pg_temp AS $$
DECLARE v_case record;
v_key text;
v_payload jsonb;
BEGIN IF p_case_id IS NULL THEN raise exception 'score_case_collectability: case_id is required';
END IF;
IF to_regclass('public.cases') IS NOT NULL THEN
SELECT c.id AS case_id,
	COALESCE(c.case_number, j.case_number) AS case_number,
	COALESCE(c.plaintiff_id, j.plaintiff_id) AS plaintiff_id INTO v_case
FROM public.cases c
	LEFT JOIN public.judgments j ON (j.case_number = c.case_number)
WHERE c.id = p_case_id
LIMIT 1;
END IF;
IF v_case.case_id IS NULL THEN
SELECT ec.id AS case_id,
	COALESCE(ec.case_number, j.case_number) AS case_number,
	j.plaintiff_id INTO v_case
FROM public.enforcement_cases ec
	LEFT JOIN public.judgments j ON j.id = ec.judgment_id
WHERE ec.id = p_case_id
LIMIT 1;
END IF;
IF v_case.case_id IS NULL THEN
SELECT c.case_id AS case_id,
	COALESCE(c.case_number, j.case_number) AS case_number,
	j.plaintiff_id INTO v_case
FROM judgments.cases c
	LEFT JOIN public.judgments j ON j.case_number = c.case_number
WHERE c.case_id = p_case_id
LIMIT 1;
END IF;
IF v_case.case_id IS NULL THEN raise exception 'score_case_collectability: case % not found',
p_case_id USING ERRCODE = 'P0002';
END IF;
IF v_case.plaintiff_id IS NULL THEN raise exception 'score_case_collectability: plaintiff missing for case %',
v_case.case_id USING ERRCODE = '23502';
END IF;
v_key := format(
	'collectability:%s:%s',
	v_case.case_id,
	encode(extensions.gen_random_bytes(6), 'hex')
);
v_payload := jsonb_build_object(
	'case_id',
	v_case.case_id,
	'case_number',
	v_case.case_number,
	'plaintiff_id',
	v_case.plaintiff_id,
	'force',
	COALESCE(p_force, false),
	'requested_at',
	timezone('utc', now()),
	'requested_by',
	NULLIF(btrim(COALESCE(p_requested_by, '')), '')
);
RETURN public.queue_job(
	jsonb_build_object(
		'kind',
		'collectability',
		'idempotency_key',
		v_key,
		'payload',
		v_payload
	)
);
END;
$$;
REVOKE ALL ON FUNCTION public.score_case_collectability(uuid, boolean, text)
FROM public;
GRANT EXECUTE ON FUNCTION public.score_case_collectability(uuid, boolean, text) TO authenticated;
GRANT EXECUTE ON FUNCTION public.score_case_collectability(uuid, boolean, text) TO service_role;
-- ========================================================================
-- public.plaintiffs canonical source system column
-- ========================================================================
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS source_system text NOT NULL DEFAULT 'unknown';
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET DEFAULT 'unknown';
ALTER TABLE public.plaintiffs
ALTER COLUMN source_system
SET NOT NULL;
-- ========================================================================
-- public.plaintiffs tier column
-- ========================================================================
ALTER TABLE public.plaintiffs
ADD COLUMN IF NOT EXISTS tier text;
ALTER TABLE public.plaintiffs
ALTER COLUMN tier
SET DEFAULT 'unknown';
-- ========================================================================
-- public.plaintiff_contacts normalized kind/value columns
-- ========================================================================
ALTER TABLE public.plaintiff_contacts
ADD COLUMN IF NOT EXISTS kind text,
	ADD COLUMN IF NOT EXISTS value text;
-- ========================================================================
-- public.plaintiff_status_history recorded_at column
-- ========================================================================
ALTER TABLE public.plaintiff_status_history
ADD COLUMN IF NOT EXISTS recorded_at timestamptz NOT NULL DEFAULT timezone('utc', now());
-- ========================================================================
-- public.plaintiff_call_attempts mirrored columns
-- ========================================================================
ALTER TABLE public.plaintiff_call_attempts
ADD COLUMN IF NOT EXISTS call_outcome text GENERATED ALWAYS AS (outcome) STORED;
ALTER TABLE public.plaintiff_call_attempts
ADD COLUMN IF NOT EXISTS called_at timestamptz GENERATED ALWAYS AS (attempted_at) STORED;
CREATE OR REPLACE FUNCTION public.log_call_outcome(
		_plaintiff_id uuid,
		_task_id uuid,
		_outcome text,
		_interest text,
		_notes text,
		_follow_up_at timestamptz
	) RETURNS jsonb LANGUAGE plpgsql AS $$
DECLARE v_terminal boolean := _outcome IN ('do_not_call', 'bad_number');
v_now timestamptz := timezone('utc', now());
v_status text;
v_follow_up_created boolean := false;
v_attempt_id uuid;
v_follow_up_task_id uuid;
BEGIN IF _outcome = 'do_not_call' THEN v_status := 'do_not_call';
ELSIF _outcome = 'bad_number' THEN v_status := 'bad_number';
ELSIF _outcome = 'reached'
AND _interest = 'hot' THEN v_status := 'reached_hot';
ELSIF _outcome = 'reached'
AND _interest = 'warm' THEN v_status := 'reached_warm';
ELSE v_status := 'contacted';
END IF;
INSERT INTO public.plaintiff_call_attempts (
		plaintiff_id,
		task_id,
		outcome,
		interest_level,
		notes,
		next_follow_up_at,
		attempted_at,
		metadata
	)
VALUES (
		_plaintiff_id,
		_task_id,
		_outcome,
		NULLIF(_interest, ''),
		_notes,
		CASE
			WHEN NOT v_terminal THEN _follow_up_at
			ELSE NULL
		END,
		v_now,
		jsonb_build_object(
			'from_rpc',
			'log_call_outcome',
			'follow_up_at',
			CASE
				WHEN NOT v_terminal THEN _follow_up_at
				ELSE NULL
			END
		)
	)
RETURNING id INTO v_attempt_id;
UPDATE public.plaintiff_tasks t
SET status = 'closed',
	completed_at = v_now,
	closed_at = COALESCE(t.closed_at, v_now),
	result = COALESCE(t.result, _outcome),
	metadata = COALESCE(t.metadata, '{}'::jsonb) || jsonb_build_object(
		'result',
		_outcome,
		'interest_level',
		_interest,
		'closed_by',
		'log_call_outcome',
		'closed_at',
		v_now
	)
WHERE t.id = _task_id;
INSERT INTO public.plaintiff_status_history (
		plaintiff_id,
		status,
		note,
		changed_at,
		changed_by
	)
VALUES (
		_plaintiff_id,
		v_status,
		COALESCE(
			_notes,
			format('Call outcome recorded: %s', _outcome)
		),
		v_now,
		'log_call_outcome'
	);
IF (NOT v_terminal)
AND _follow_up_at IS NOT NULL THEN
INSERT INTO public.plaintiff_tasks (
		plaintiff_id,
		kind,
		status,
		due_at,
		note,
		created_by,
		metadata
	)
VALUES (
		_plaintiff_id,
		'call',
		'open',
		_follow_up_at,
		COALESCE(_notes, 'Follow-up call'),
		'log_call_outcome',
		jsonb_build_object(
			'from_outcome',
			_outcome,
			'interest_level',
			_interest,
			'previous_task_id',
			_task_id
		)
	)
RETURNING id INTO v_follow_up_task_id;
v_follow_up_created := true;
END IF;
RETURN jsonb_build_object(
	'plaintiff_id',
	_plaintiff_id,
	'task_id',
	_task_id,
	'outcome',
	_outcome,
	'interest',
	_interest,
	'status',
	v_status,
	'follow_up_created',
	v_follow_up_created,
	'follow_up_at',
	_follow_up_at,
	'call_attempt_id',
	v_attempt_id,
	'created_follow_up_task_id',
	v_follow_up_task_id
);
END;
$$;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO anon;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO authenticated;
GRANT EXECUTE ON FUNCTION public.log_call_outcome(uuid, uuid, text, text, text, timestamptz) TO service_role;
-- ========================================================================
-- public.plaintiff_tasks enforcement planner columns
-- ========================================================================
ALTER TABLE public.plaintiff_tasks
ADD COLUMN IF NOT EXISTS case_id uuid REFERENCES public.enforcement_cases(id) ON DELETE
SET NULL,
	ADD COLUMN IF NOT EXISTS severity public.enforcement_task_severity NOT NULL DEFAULT 'medium',
	ADD COLUMN IF NOT EXISTS task_code public.enforcement_task_kind,
	ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT timezone('utc', now());
UPDATE public.plaintiff_tasks
SET severity = 'medium'
WHERE severity IS NULL;
DROP TRIGGER IF EXISTS plaintiff_tasks_touch_updated_at ON public.plaintiff_tasks;
CREATE TRIGGER plaintiff_tasks_touch_updated_at BEFORE
UPDATE ON public.plaintiff_tasks FOR EACH ROW EXECUTE FUNCTION public.touch_updated_at();
CREATE UNIQUE INDEX IF NOT EXISTS plaintiff_tasks_case_task_code_open_idx ON public.plaintiff_tasks (case_id, task_code)
WHERE case_id IS NOT NULL
	AND task_code IS NOT NULL
	AND status IN ('open', 'in_progress');
-- ========================================================================
-- Executive metrics + dashboard views
-- ========================================================================
CREATE OR REPLACE VIEW public.v_metrics_intake_daily AS WITH import_rows AS (
		SELECT date_trunc('day', timezone('utc', started_at))::date AS activity_date,
			COALESCE(NULLIF(lower(source_system), ''), 'unknown') AS source_system,
			COUNT(*) AS import_count
		FROM public.import_runs
		GROUP BY 1,
			2
	),
	plaintiff_rows AS (
		SELECT date_trunc('day', timezone('utc', created_at))::date AS activity_date,
			COALESCE(NULLIF(lower(source_system), ''), 'unknown') AS source_system,
			COUNT(*) AS plaintiff_count
		FROM public.plaintiffs
		GROUP BY 1,
			2
	),
	judgment_rows AS (
		SELECT date_trunc(
				'day',
				timezone(
					'utc',
					COALESCE(j.created_at, j.entry_date::timestamptz, now())
				)
			)::date AS activity_date,
			COALESCE(NULLIF(lower(p.source_system), ''), 'unknown') AS source_system,
			COUNT(*) AS judgment_count,
			COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount
		FROM public.judgments j
			LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
		GROUP BY 1,
			2
	),
	combined_keys AS (
		SELECT activity_date,
			source_system
		FROM import_rows
		UNION
		SELECT activity_date,
			source_system
		FROM plaintiff_rows
		UNION
		SELECT activity_date,
			source_system
		FROM judgment_rows
	)
SELECT k.activity_date,
	k.source_system,
	COALESCE(i.import_count, 0) AS import_count,
	COALESCE(pl.plaintiff_count, 0) AS plaintiff_count,
	COALESCE(j.judgment_count, 0) AS judgment_count,
	COALESCE(j.total_judgment_amount, 0)::numeric AS total_judgment_amount
FROM combined_keys k
	LEFT JOIN import_rows i ON i.activity_date = k.activity_date
	AND i.source_system = k.source_system
	LEFT JOIN plaintiff_rows pl ON pl.activity_date = k.activity_date
	AND pl.source_system = k.source_system
	LEFT JOIN judgment_rows j ON j.activity_date = k.activity_date
	AND j.source_system = k.source_system
ORDER BY k.activity_date DESC,
	k.source_system;
COMMENT ON VIEW public.v_metrics_intake_daily IS 'Daily intake funnel rollups by source system for the executive dashboard.';
GRANT SELECT ON public.v_metrics_intake_daily TO anon,
	authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_metrics_pipeline AS
SELECT COALESCE(
		NULLIF(lower(j.enforcement_stage), ''),
		'unknown'
	) AS enforcement_stage,
	COALESCE(
		NULLIF(lower(cs.collectability_tier), ''),
		'unscored'
	) AS collectability_tier,
	COUNT(*) AS judgment_count,
	COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount,
	COALESCE(AVG(j.judgment_amount), 0)::numeric AS average_judgment_amount,
	MAX(j.enforcement_stage_updated_at) AS latest_stage_update
FROM public.judgments j
	LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
GROUP BY 1,
	2;
COMMENT ON VIEW public.v_metrics_pipeline IS 'Current pipeline exposure grouped by enforcement stage and collectability tier.';
GRANT SELECT ON public.v_metrics_pipeline TO anon,
	authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_metrics_enforcement AS WITH case_rows AS (
		SELECT ec.id,
			ec.opened_at,
			ec.updated_at,
			COALESCE(NULLIF(lower(ec.status), ''), 'open') AS status,
			ec.metadata,
			COALESCE(j.judgment_amount, 0)::numeric AS judgment_amount
		FROM public.enforcement_cases ec
			LEFT JOIN public.judgments j ON j.id = ec.judgment_id
	),
	closed_events AS (
		SELECT e.case_id,
			MIN(e.event_date) AS closed_at
		FROM public.enforcement_events e
		WHERE lower(COALESCE(e.event_type, '')) LIKE '%closed%'
		GROUP BY e.case_id
	),
	closed_metadata AS (
		SELECT id AS case_id,
			CASE
				WHEN metadata ? 'closed_at'
				AND jsonb_typeof(metadata->'closed_at') = 'string'
				AND COALESCE(metadata->>'closed_at', '') ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}' THEN (metadata->>'closed_at')::timestamptz
				ELSE NULL
			END AS closed_at
		FROM case_rows
	),
	combined AS (
		SELECT cr.*,
			COALESCE(
				ce.closed_at,
				cm.closed_at,
				CASE
					WHEN cr.status = 'closed' THEN cr.updated_at
					ELSE NULL
				END
			) AS closed_at
		FROM case_rows cr
			LEFT JOIN closed_events ce ON ce.case_id = cr.id
			LEFT JOIN closed_metadata cm ON cm.case_id = cr.id
	),
	opened AS (
		SELECT date_trunc('week', timezone('utc', opened_at))::date AS bucket_week,
			COUNT(*) AS cases_opened,
			COALESCE(SUM(judgment_amount), 0)::numeric AS opened_judgment_amount
		FROM combined
		GROUP BY 1
	),
	closed AS (
		SELECT date_trunc('week', timezone('utc', closed_at))::date AS bucket_week,
			COUNT(*) AS cases_closed,
			COALESCE(SUM(judgment_amount), 0)::numeric AS closed_judgment_amount
		FROM combined
		WHERE closed_at IS NOT NULL
		GROUP BY 1
	),
	active AS (
		SELECT COUNT(*) FILTER (
				WHERE status <> 'closed'
			) AS active_case_count,
			COALESCE(
				SUM(
					CASE
						WHEN status <> 'closed' THEN judgment_amount
						ELSE 0
					END
				),
				0
			)::numeric AS active_judgment_amount
		FROM combined
	),
	seed_week AS (
		SELECT date_trunc('week', timezone('utc', now()))::date AS bucket_week
	),
	week_keys AS (
		SELECT bucket_week
		FROM opened
		UNION
		SELECT bucket_week
		FROM closed
		UNION
		SELECT bucket_week
		FROM seed_week
	)
SELECT wk.bucket_week,
	COALESCE(o.cases_opened, 0) AS cases_opened,
	COALESCE(o.opened_judgment_amount, 0)::numeric AS opened_judgment_amount,
	COALESCE(c.cases_closed, 0) AS cases_closed,
	COALESCE(c.closed_judgment_amount, 0)::numeric AS closed_judgment_amount,
	active.active_case_count,
	active.active_judgment_amount
FROM week_keys wk
	LEFT JOIN opened o ON o.bucket_week = wk.bucket_week
	LEFT JOIN closed c ON c.bucket_week = wk.bucket_week
	CROSS JOIN active
ORDER BY wk.bucket_week DESC;
COMMENT ON VIEW public.v_metrics_enforcement IS 'Weekly enforcement throughput plus active exposure snapshot for executives.';
GRANT SELECT ON public.v_metrics_enforcement TO anon,
	authenticated,
	service_role;
-- ========================================================================
-- public.v_plaintiffs_overview
-- ========================================================================
CREATE OR REPLACE VIEW public.v_plaintiffs_overview AS
SELECT p.id AS plaintiff_id,
	p.name AS plaintiff_name,
	p.firm_name,
	p.status,
	COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount,
	COUNT(DISTINCT j.id) AS case_count
FROM public.plaintiffs p
	LEFT JOIN public.judgments j ON j.plaintiff_id = p.id
GROUP BY p.id,
	p.name,
	p.firm_name,
	p.status;
GRANT SELECT ON public.v_plaintiffs_overview TO anon,
	authenticated,
	service_role;
-- ========================================================================
-- Enforcement rollups + recents
-- ========================================================================
CREATE OR REPLACE VIEW public.v_enforcement_overview AS
SELECT j.enforcement_stage,
	cs.collectability_tier,
	COUNT(*) AS case_count,
	COALESCE(SUM(j.judgment_amount), 0)::numeric AS total_judgment_amount
FROM public.judgments j
	LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
GROUP BY j.enforcement_stage,
	cs.collectability_tier;
GRANT SELECT ON public.v_enforcement_overview TO anon,
	authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_enforcement_recent AS
SELECT j.id AS judgment_id,
	j.case_number,
	j.plaintiff_id::text AS plaintiff_id,
	COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
	j.judgment_amount,
	j.enforcement_stage,
	j.enforcement_stage_updated_at,
	cs.collectability_tier
FROM public.judgments j
	LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
	LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
ORDER BY j.enforcement_stage_updated_at DESC,
	j.id DESC;
GRANT SELECT ON public.v_enforcement_recent TO anon,
	authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_judgment_pipeline AS
SELECT j.id AS judgment_id,
	j.case_number,
	j.plaintiff_id::text AS plaintiff_id,
	COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
	j.defendant_name,
	j.judgment_amount,
	j.enforcement_stage,
	j.enforcement_stage_updated_at,
	cs.collectability_tier,
	cs.age_days AS collectability_age_days,
	cs.last_enriched_at,
	cs.last_enrichment_status
FROM public.judgments j
	LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
	LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number;
GRANT SELECT ON public.v_judgment_pipeline TO anon,
	authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_priority_pipeline AS WITH normalized AS (
		SELECT j.id AS judgment_id,
			COALESCE(p.name, j.plaintiff_name) AS plaintiff_name,
			j.judgment_amount,
			COALESCE(
				NULLIF(lower(j.enforcement_stage), ''),
				'unknown'
			) AS stage,
			COALESCE(NULLIF(lower(p.status), ''), 'unknown') AS plaintiff_status,
			COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') AS priority_level,
			CASE
				WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 'A'
				WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 'B'
				WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 'C'
				ELSE 'UNSCORED'
			END AS collectability_tier,
			CASE
				WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 1
				WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 2
				WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 3
				ELSE 4
			END AS tier_order,
			CASE
				WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'urgent' THEN 1
				WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'high' THEN 2
				WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'normal' THEN 3
				WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'low' THEN 4
				WHEN COALESCE(NULLIF(lower(j.priority_level), ''), 'normal') = 'on_hold' THEN 5
				ELSE 6
			END AS priority_order
		FROM public.judgments j
			LEFT JOIN public.plaintiffs p ON p.id = j.plaintiff_id
			LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
	)
SELECT n.plaintiff_name,
	n.judgment_id,
	n.collectability_tier,
	n.priority_level,
	n.judgment_amount,
	n.stage,
	n.plaintiff_status,
	ROW_NUMBER() OVER (
		PARTITION BY n.collectability_tier
		ORDER BY n.priority_order,
			COALESCE(n.judgment_amount, 0)::numeric DESC,
			n.judgment_id DESC
	) AS tier_rank
FROM normalized n;
GRANT SELECT ON public.v_priority_pipeline TO service_role;
CREATE OR REPLACE VIEW public.v_plaintiffs_jbi_900 AS
SELECT p.status,
	COUNT(*)::bigint AS plaintiff_count,
	COALESCE(SUM(ov.total_judgment_amount), 0)::numeric AS total_judgment_amount,
	CASE
		WHEN btrim(lower(p.status)) = 'new' THEN 1
		WHEN btrim(lower(p.status)) = 'contacted' THEN 2
		WHEN btrim(lower(p.status)) = 'qualified' THEN 3
		WHEN btrim(lower(p.status)) = 'sent_agreement' THEN 4
		WHEN btrim(lower(p.status)) = 'signed' THEN 5
		WHEN btrim(lower(p.status)) = 'lost' THEN 6
		ELSE 99
	END AS status_priority
FROM public.plaintiffs p
	LEFT JOIN public.v_plaintiffs_overview ov ON ov.plaintiff_id = p.id
WHERE p.source_system = 'jbi_900'
GROUP BY p.status;
GRANT SELECT ON public.v_plaintiffs_jbi_900 TO anon,
	authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_plaintiff_open_tasks AS WITH tier_lookup AS (
		SELECT j.plaintiff_id,
			MIN(
				CASE
					WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 1
					WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 2
					WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 3
					ELSE 99
				END
			) AS best_rank
		FROM public.judgments j
			LEFT JOIN public.v_collectability_snapshot cs ON cs.case_number = j.case_number
		WHERE j.plaintiff_id IS NOT NULL
		GROUP BY j.plaintiff_id
	)
SELECT t.id AS task_id,
	t.plaintiff_id,
	p.name AS plaintiff_name,
	p.firm_name,
	p.email,
	p.phone,
	p.status AS plaintiff_status,
	COALESCE(ov.total_judgment_amount, 0::numeric) AS judgment_total,
	COALESCE(ov.case_count, 0) AS case_count,
	CASE
		WHEN tier_lookup.best_rank = 1 THEN 'A'
		WHEN tier_lookup.best_rank = 2 THEN 'B'
		WHEN tier_lookup.best_rank = 3 THEN 'C'
		ELSE NULL
	END AS top_collectability_tier,
	t.case_id,
	t.kind,
	t.status,
	t.assignee,
	t.due_at,
	t.created_at,
	t.note,
	t.metadata,
	t.severity,
	t.task_code
FROM public.plaintiff_tasks t
	JOIN public.plaintiffs p ON p.id = t.plaintiff_id
	LEFT JOIN public.v_plaintiffs_overview ov ON ov.plaintiff_id = p.id
	LEFT JOIN tier_lookup ON tier_lookup.plaintiff_id = t.plaintiff_id
WHERE t.status IN ('open', 'in_progress');
GRANT SELECT ON public.v_plaintiff_open_tasks TO anon,
	authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_plaintiff_call_queue AS WITH ranked_call_tasks AS (
		SELECT ot.*,
			row_number() OVER (
				PARTITION BY ot.plaintiff_id
				ORDER BY ot.due_at NULLS LAST,
					ot.created_at ASC
			) AS task_rank
		FROM public.v_plaintiff_open_tasks ot
		WHERE ot.kind = 'call'
			AND ot.status IN ('open', 'in_progress')
	)
SELECT r.task_id,
	r.plaintiff_id,
	r.plaintiff_name,
	r.firm_name,
	r.plaintiff_status AS status,
	r.status AS task_status,
	r.top_collectability_tier AS tier,
	r.judgment_total AS total_judgment_amount,
	r.case_count,
	r.phone,
	contact_info.last_contact_at AS last_contact_at,
	contact_info.last_contact_at AS last_contacted_at,
	CASE
		WHEN contact_info.last_contact_at IS NULL THEN NULL
		ELSE GREATEST(
			DATE_PART(
				'day',
				timezone('utc', now()) - contact_info.last_contact_at
			)::int,
			0
		)
	END AS days_since_contact,
	r.due_at,
	r.note AS notes,
	r.created_at
FROM ranked_call_tasks r
	LEFT JOIN LATERAL (
		SELECT CASE
				WHEN status_info.last_contacted_at IS NULL
				AND attempt_info.last_attempt_at IS NULL THEN NULL
				ELSE GREATEST(
					COALESCE(
						status_info.last_contacted_at,
						'-infinity'::timestamptz
					),
					COALESCE(
						attempt_info.last_attempt_at,
						'-infinity'::timestamptz
					)
				)
			END AS last_contact_at
		FROM (
				SELECT MAX(psh.changed_at) AS last_contacted_at
				FROM public.plaintiff_status_history psh
				WHERE psh.plaintiff_id = r.plaintiff_id
					AND psh.status IN (
						'contacted',
						'qualified',
						'sent_agreement',
						'signed'
					)
			) status_info,
			(
				SELECT MAX(pca.attempted_at) AS last_attempt_at
				FROM public.plaintiff_call_attempts pca
				WHERE pca.plaintiff_id = r.plaintiff_id
			) attempt_info
	) contact_info ON TRUE
WHERE r.task_rank = 1
ORDER BY r.due_at NULLS LAST,
	contact_info.last_contact_at NULLS FIRST,
	r.plaintiff_name;
GRANT SELECT ON public.v_plaintiff_call_queue TO anon,
	authenticated,
	service_role;
-- ========================================================================
-- public.generate_enforcement_tasks RPC
-- ========================================================================
CREATE OR REPLACE FUNCTION public.generate_enforcement_tasks(case_id uuid) RETURNS TABLE (
		task_id uuid,
		task_code public.enforcement_task_kind,
		due_at timestamptz,
		severity public.enforcement_task_severity
	) LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public,
	pg_temp AS $$
DECLARE target_case_id uuid := case_id;
v_case RECORD;
v_now timestamptz := timezone('utc', now());
BEGIN IF target_case_id IS NULL THEN RAISE EXCEPTION 'generate_enforcement_tasks: case_id is required';
END IF;
SELECT ec.id,
	ec.judgment_id,
	COALESCE(j.plaintiff_id, NULL) AS plaintiff_id INTO v_case
FROM public.enforcement_cases ec
	LEFT JOIN public.judgments j ON j.id = ec.judgment_id
WHERE ec.id = target_case_id
LIMIT 1;
IF v_case.id IS NULL THEN RAISE EXCEPTION 'generate_enforcement_tasks: enforcement case % not found',
target_case_id USING ERRCODE = 'P0002';
END IF;
IF v_case.plaintiff_id IS NULL THEN RAISE EXCEPTION 'generate_enforcement_tasks: plaintiff missing for case %',
target_case_id USING ERRCODE = '23502';
END IF;
RETURN QUERY WITH defs AS (
	SELECT *
	FROM (
			VALUES (
					'enforcement_phone_attempt',
					'enforcement_phone_attempt',
					'medium',
					0,
					'Place immediate enforcement phone call to confirm borrower contact info.',
					7,
					'phone',
					'follow_up_7_days'
				),
				(
					'enforcement_phone_follow_up',
					'enforcement_phone_follow_up',
					'medium',
					7,
					'Follow up on phone outreach (7-day rule).',
					7,
					'phone',
					'follow_up_7_days'
				),
				(
					'enforcement_mailer',
					'enforcement_mailer',
					'low',
					7,
					'Send enforcement mailer packet to borrower and employer.',
					NULL,
					'mail',
					'follow_up_7_days'
				),
				(
					'enforcement_demand_letter',
					'enforcement_demand_letter',
					'high',
					14,
					'Prepare and send demand letter (14-day escalation).',
					NULL,
					'legal',
					'escalation_14_days'
				),
				(
					'enforcement_wage_garnishment_prep',
					'enforcement_wage_garnishment_prep',
					'high',
					14,
					'Gather payroll intel for wage garnishment filing.',
					NULL,
					'legal',
					'escalation_14_days'
				),
				(
					'enforcement_bank_levy_prep',
					'enforcement_bank_levy_prep',
					'high',
					14,
					'Review assets and prepare bank levy paperwork.',
					NULL,
					'legal',
					'escalation_14_days'
				),
				(
					'enforcement_skiptrace_refresh',
					'enforcement_skiptrace_refresh',
					'medium',
					30,
					'Refresh skiptrace data (30-day cycle).',
					30,
					'research',
					'refresh_30_days'
				)
		) AS d(
			task_code_text,
			kind_text,
			severity_text,
			offset_days,
			note,
			frequency_days,
			category,
			rule_code
		)
),
inserted AS (
	INSERT INTO public.plaintiff_tasks (
			plaintiff_id,
			case_id,
			kind,
			status,
			severity,
			due_at,
			note,
			assignee,
			metadata,
			created_by,
			task_code
		)
	SELECT v_case.plaintiff_id,
		v_case.id,
		d.kind_text,
		'open',
		d.severity_text::public.enforcement_task_severity,
		v_now + (d.offset_days || ' days')::interval,
		d.note,
		NULL,
		jsonb_strip_nulls(
			jsonb_build_object(
				'task_code',
				d.task_code_text,
				'category',
				d.category,
				'frequency_days',
				d.frequency_days,
				'rule',
				d.rule_code,
				'planned_at',
				v_now
			)
		),
		'enforcement_planner_v2',
		d.task_code_text::public.enforcement_task_kind
	FROM defs d
	WHERE NOT EXISTS (
			SELECT 1
			FROM public.plaintiff_tasks existing
			WHERE existing.case_id = v_case.id
				AND existing.task_code = d.task_code_text::public.enforcement_task_kind
				AND existing.status IN ('open', 'in_progress')
		)
	RETURNING id,
		task_code,
		due_at,
		severity
)
SELECT id,
	task_code,
	due_at,
	severity
FROM inserted;
END;
$$;
REVOKE ALL ON FUNCTION public.generate_enforcement_tasks(uuid)
FROM public;
GRANT EXECUTE ON FUNCTION public.generate_enforcement_tasks(uuid) TO authenticated,
	service_role;
CREATE OR REPLACE VIEW public.v_pipeline_snapshot AS WITH simplicity AS (
		SELECT COUNT(*)::bigint AS total
		FROM public.plaintiffs
		WHERE COALESCE(lower(source_system), 'unknown') = 'simplicity'
	),
	normalized_status AS (
		SELECT CASE
				WHEN btrim(COALESCE(status, '')) = '' THEN 'unknown'
				ELSE lower(status)
			END AS status_bucket
		FROM public.plaintiffs
	),
	lifecycle AS (
		SELECT COALESCE(
				jsonb_object_agg(status_bucket, bucket_count),
				'{}'::jsonb
			) AS counts
		FROM (
				SELECT status_bucket,
					COUNT(*)::bigint AS bucket_count
				FROM normalized_status
				GROUP BY status_bucket
			) buckets
	),
	collectability AS (
		SELECT jsonb_build_object(
				'A',
				COALESCE(
					SUM(
						CASE
							WHEN normalized_tier = 'A' THEN judgment_amount
							ELSE 0
						END
					),
					0
				)::numeric,
				'B',
				COALESCE(
					SUM(
						CASE
							WHEN normalized_tier = 'B' THEN judgment_amount
							ELSE 0
						END
					),
					0
				)::numeric,
				'C',
				COALESCE(
					SUM(
						CASE
							WHEN normalized_tier = 'C' THEN judgment_amount
							ELSE 0
						END
					),
					0
				)::numeric
			) AS totals
		FROM (
				SELECT CASE
						WHEN upper(COALESCE(cs.collectability_tier, '')) = 'A' THEN 'A'
						WHEN upper(COALESCE(cs.collectability_tier, '')) = 'B' THEN 'B'
						WHEN upper(COALESCE(cs.collectability_tier, '')) = 'C' THEN 'C'
						ELSE NULL
					END AS normalized_tier,
					COALESCE(cs.judgment_amount, 0::numeric) AS judgment_amount
				FROM public.v_collectability_snapshot cs
			) scored
	),
	jbi AS (
		SELECT COALESCE(
				jsonb_agg(
					jsonb_build_object(
						'status',
						status,
						'plaintiff_count',
						plaintiff_count,
						'total_judgment_amount',
						total_judgment_amount,
						'status_priority',
						status_priority
					)
					ORDER BY status_priority,
						status
				),
				'[]'::jsonb
			) AS summary
		FROM public.v_plaintiffs_jbi_900
	)
SELECT timezone('utc', now()) AS snapshot_at,
	simplicity.total AS simplicity_plaintiff_count,
	lifecycle.counts AS lifecycle_counts,
	collectability.totals AS tier_totals,
	jbi.summary AS jbi_summary
FROM simplicity,
	lifecycle,
	collectability,
	jbi;
GRANT SELECT ON public.v_pipeline_snapshot TO service_role;