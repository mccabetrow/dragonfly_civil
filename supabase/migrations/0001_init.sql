-- 0001_init.sql
-- Initial database objects for Dragonfly (idempotent where possible)

-- Extensions
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "btree_gin";

-- Schemas
CREATE SCHEMA IF NOT EXISTS judgments;
CREATE SCHEMA IF NOT EXISTS ingestion;

-- ingestion.runs
CREATE TABLE IF NOT EXISTS ingestion.runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source text,
  started_at timestamptz DEFAULT now(),
  finished_at timestamptz,
  rows_ok int DEFAULT 0,
  rows_err int DEFAULT 0,
  notes jsonb,
  metadata jsonb,
  created_at timestamptz DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started ON ingestion.runs(started_at DESC);

-- judgments.cases
CREATE TABLE IF NOT EXISTS judgments.cases (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source text,
  external_id text,
  state text NOT NULL,
  county text NOT NULL,
  court_name text,
  docket_number text,
  case_number text,
  case_type text,
  case_status text,
  case_url text,
  filing_date date,
  owner text,
  metadata jsonb,
  ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE SET NULL,
  created_at timestamptz DEFAULT now()
);
-- Unique indexes to support different upsert keys used by loaders
DO $$ BEGIN
  CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_state_county_docket ON judgments.cases(state, county, docket_number);
EXCEPTION WHEN duplicate_table THEN NULL; END $$;
DO $$ BEGIN
  CREATE UNIQUE INDEX IF NOT EXISTS ux_cases_state_county_case ON judgments.cases(state, county, case_number);
EXCEPTION WHEN duplicate_table THEN NULL; END $$;

-- judgments.judgments
CREATE TABLE IF NOT EXISTS judgments.judgments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL REFERENCES judgments.cases(id) ON DELETE CASCADE,
  judgment_number text,
  judgment_date date NOT NULL,
  amount_awarded numeric(12,2) NOT NULL,
  amount_remaining numeric(12,2),
  interest_rate numeric(5,2),
  judgment_type text,
  judgment_status text DEFAULT 'unsatisfied',
  renewal_date date,
  expiration_date date,
  notes text,
  metadata jsonb,
  ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE SET NULL,
  created_at timestamptz DEFAULT now()
);
DO $$ BEGIN
  CREATE UNIQUE INDEX IF NOT EXISTS ux_judgments_case_date_amount ON judgments.judgments(case_id, judgment_date, amount_awarded);
EXCEPTION WHEN duplicate_table THEN NULL; END $$;

-- judgments.parties
CREATE TABLE IF NOT EXISTS judgments.parties (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  case_id uuid NOT NULL REFERENCES judgments.cases(id) ON DELETE CASCADE,
  role text NOT NULL CHECK (role IN ('plaintiff', 'defendant')),
  party_role text,
  party_type text,
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
  is_business boolean DEFAULT false,
  phone text,
  email text,
  metadata jsonb,
  created_at timestamptz DEFAULT now()
);
DO $$ BEGIN
  CREATE UNIQUE INDEX IF NOT EXISTS ux_parties_case_role_name ON judgments.parties(case_id, role, name_normalized);
EXCEPTION WHEN duplicate_table THEN NULL; END $$;

-- judgments.contacts
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
  is_verified boolean DEFAULT false,
  is_primary boolean DEFAULT false,
  source text,
  last_verified_at timestamptz,
  notes text,
  metadata jsonb,
  ingestion_run_id uuid REFERENCES ingestion.runs(id) ON DELETE SET NULL,
  created_at timestamptz DEFAULT now()
);
DO $$ BEGIN
  CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_party_phone ON judgments.contacts(party_id, phone_e164) WHERE phone_e164 IS NOT NULL;
EXCEPTION WHEN duplicate_table THEN NULL; END $$;
DO $$ BEGIN
  CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_party_email ON judgments.contacts(party_id, email) WHERE email IS NOT NULL;
EXCEPTION WHEN duplicate_table THEN NULL; END $$;
DO $$ BEGIN
  CREATE UNIQUE INDEX IF NOT EXISTS ux_contacts_type_value ON judgments.contacts(party_id, contact_type, contact_value) WHERE contact_type IS NOT NULL AND contact_value IS NOT NULL;
EXCEPTION WHEN duplicate_table THEN NULL; END $$;

-- Helpful indexes
CREATE INDEX IF NOT EXISTS ix_cases_state_county ON judgments.cases(state, county);
CREATE INDEX IF NOT EXISTS ix_judgments_case ON judgments.judgments(case_id);
CREATE INDEX IF NOT EXISTS ix_parties_case ON judgments.parties(case_id);
CREATE INDEX IF NOT EXISTS ix_contacts_party ON judgments.contacts(party_id);

-- End of migration 0001
