-- Enable required extensions
create extension if not exists pgcrypto with schema public;
create extension if not exists pg_trgm with schema public;

-- Create schemas
create schema if not exists judgments;
create schema if not exists parties;
create schema if not exists enrichment;
create schema if not exists outreach;
create schema if not exists intake;
create schema if not exists enforcement;
create schema if not exists ops;
create schema if not exists finance;

-- Enumerated types
create type judgments.case_status as enum (
    'new', 'enriched', 'contacting', 'intake', 'enforcing', 'collected', 'dead'
);
create type parties.entity_type as enum ('person', 'company');
create type enrichment.contact_kind as enum ('phone', 'email', 'address');
create type enforcement.action_type as enum (
    'levy', 'income_exec', 'lien', 'turnover'
);

-- Tables
create table judgments.cases (
    case_id uuid primary key default gen_random_uuid(),
    index_no text not null,
    court text not null,
    county text not null,
    filed_at date,
    judgment_at date,
    principal_amt numeric(14, 2) not null default 0,
    interest_rate numeric(6, 4) default 0.0900,
    interest_from date,
    costs numeric(14, 2) default 0,
    status judgments.case_status not null default 'new',
    source text,
    fingerprint_hash text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    constraint uq_case unique (court, county, index_no)
);

create table parties.entities (
    entity_id uuid primary key default gen_random_uuid(),
    name_raw text not null,
    name_norm text generated always as (
        regexp_replace(lower(name_raw), '\s+', ' ', 'g')
    ) stored,
    type parties.entity_type not null,
    ein_ssn_hash text,
    created_at timestamptz default now()
);

create table parties.roles (
    case_id uuid references judgments.cases (case_id) on delete cascade,
    entity_id uuid references parties.entities (entity_id) on delete cascade,
    role text check (role in ('plaintiff', 'defendant', 'attorney')),
    primary key (case_id, entity_id, role)
);

create table enrichment.contacts (
    contact_id uuid primary key default gen_random_uuid(),
    entity_id uuid not null references parties.entities (
        entity_id
    ) on delete cascade,
    kind enrichment.contact_kind not null,
    value text not null,
    source text,
    validated_bool boolean default false,
    score numeric(5, 2) default 0,
    created_at timestamptz default now(),
    unique (entity_id, kind, value)
);

create table enrichment.assets (
    asset_id uuid primary key default gen_random_uuid(),
    entity_id uuid not null references parties.entities (
        entity_id
    ) on delete cascade,
    asset_type text check (
        asset_type in (
            'real_property',
            'bank_hint',
            'employment',
            'vehicle',
            'license',
            'ucc',
            'dba'
        )
    ),
    meta_json jsonb not null default '{}'::jsonb,
    confidence numeric(5, 2) default 0,
    source text,
    created_at timestamptz default now()
);

create table enrichment.collectability (
    case_id uuid primary key references judgments.cases (
        case_id
    ) on delete cascade,
    identity_score numeric(5, 2) default 0,
    contactability_score numeric(5, 2) default 0,
    asset_score numeric(5, 2) default 0,
    recency_amount_score numeric(5, 2) default 0,
    adverse_penalty numeric(5, 2) default 0,
    total_score numeric(5, 2) generated always as (
        greatest(
            0,
            identity_score * 0.30
            + contactability_score * 0.25
            + asset_score * 0.25
            + recency_amount_score * 0.10
            - adverse_penalty
        )
    ) stored,
    tier text generated always as (
        case
            when
                greatest(
                    0,
                    identity_score * 0.30
                    + contactability_score * 0.25
                    + asset_score * 0.25
                    + recency_amount_score * 0.10
                    - adverse_penalty
                )
                >= 80
                then 'A'
            when
                greatest(
                    0,
                    identity_score * 0.30
                    + contactability_score * 0.25
                    + asset_score * 0.25
                    + recency_amount_score * 0.10
                    - adverse_penalty
                )
                >= 60
                then 'B'
            when
                greatest(
                    0,
                    identity_score * 0.30
                    + contactability_score * 0.25
                    + asset_score * 0.25
                    + recency_amount_score * 0.10
                    - adverse_penalty
                )
                >= 40
                then 'C'
            else 'D'
        end
    ) stored,
    updated_at timestamptz default now()
);

create table outreach.cadences (
    cadence_id uuid primary key default gen_random_uuid(),
    case_id uuid not null references judgments.cases (
        case_id
    ) on delete cascade,
    strategy text not null,
    status text not null default 'draft',
    started_at timestamptz default now(),
    completed_at timestamptz,
    created_at timestamptz default now(),
    updated_at timestamptz default now()
);

create table outreach.attempts (
    attempt_id uuid primary key default gen_random_uuid(),
    case_id uuid not null references judgments.cases (
        case_id
    ) on delete cascade,
    cadence_id uuid references outreach.cadences (
        cadence_id
    ) on delete set null,
    channel text not null,
    outcome text,
    notes text,
    attempted_at timestamptz default now(),
    created_at timestamptz default now()
);

create table intake.esign (
    esign_id uuid primary key default gen_random_uuid(),
    case_id uuid not null references judgments.cases (
        case_id
    ) on delete cascade,
    envelope_id text,
    status text not null default 'pending',
    sent_at timestamptz,
    signed_at timestamptz,
    created_at timestamptz default now()
);

create table enforcement.actions (
    action_id uuid primary key default gen_random_uuid(),
    case_id uuid not null references judgments.cases (
        case_id
    ) on delete cascade,
    action_type enforcement.action_type not null,
    filed_at date,
    status text,
    notes text,
    created_at timestamptz default now()
);

create table finance.trust_txns (
    txn_id uuid primary key default gen_random_uuid(),
    case_id uuid references judgments.cases (case_id) on delete cascade,
    amount numeric(14, 2) not null,
    txn_type text check (txn_type in ('credit', 'debit')),
    occurred_at timestamptz not null default now(),
    reference text,
    memo text,
    created_at timestamptz default now()
);

create table ops.runs (
    run_id uuid primary key default gen_random_uuid(),
    job_name text not null,
    status text not null default 'pending',
    started_at timestamptz default now(),
    finished_at timestamptz,
    payload jsonb not null default '{}'::jsonb,
    created_at timestamptz default now()
);

-- Trigger to maintain updated_at on cases
create or replace function judgments._set_updated_at() returns trigger
language plpgsql
as $$
begin
  new.updated_at := now();
  return new;
end;
$$;

create trigger _bu_cases
before update on judgments.cases
for each row
execute function judgments._set_updated_at();

-- Indexes
create index idx_cases_county on judgments.cases (county);
create index idx_cases_status on judgments.cases (status);
create index idx_contacts_entity on enrichment.contacts (entity_id);
create index idx_assets_entity on enrichment.assets (entity_id);
create index idx_attempts_case_time on outreach.attempts (
    case_id, attempted_at
);
create index idx_entities_name_norm_trgm on parties.entities using gin (
    name_norm gin_trgm_ops
);

-- Row level security and policies
alter table judgments.cases enable row level security;
alter table parties.entities enable row level security;
alter table parties.roles enable row level security;
alter table enrichment.contacts enable row level security;
alter table enrichment.assets enable row level security;
alter table enrichment.collectability enable row level security;
alter table outreach.cadences enable row level security;
alter table outreach.attempts enable row level security;
alter table intake.esign enable row level security;
alter table enforcement.actions enable row level security;
alter table finance.trust_txns enable row level security;
alter table ops.runs enable row level security;

-- Select policies (open to all)
create policy select_cases on judgments.cases for select using (true);
create policy select_entities on parties.entities for select using (true);
create policy select_roles on parties.roles for select using (true);
create policy select_contacts on enrichment.contacts for select using (true);
create policy select_assets on enrichment.assets for select using (true);
create policy select_collectability on enrichment.collectability for select using (
    true
);
create policy select_cadences on outreach.cadences for select using (true);
create policy select_attempts on outreach.attempts for select using (true);
create policy select_esign on intake.esign for select using (true);
create policy select_actions on enforcement.actions for select using (true);
create policy select_trust_txns on finance.trust_txns for select using (true);
create policy select_runs on ops.runs for select using (true);

-- Insert policies (service role only)
create policy insert_cases_service on judgments.cases for insert with check (
    auth.role() = 'service_role'
);
create policy insert_entities_service on parties.entities for insert with check (
    auth.role() = 'service_role'
);
create policy insert_roles_service on parties.roles for insert with check (
    auth.role() = 'service_role'
);
create policy insert_contacts_service on enrichment.contacts for insert with check (
    auth.role() = 'service_role'
);
create policy insert_assets_service on enrichment.assets for insert with check (
    auth.role() = 'service_role'
);
create policy insert_collectability_service on enrichment.collectability for insert with check (
    auth.role() = 'service_role'
);
create policy insert_cadences_service on outreach.cadences for insert with check (
    auth.role() = 'service_role'
);
create policy insert_attempts_service on outreach.attempts for insert with check (
    auth.role() = 'service_role'
);
create policy insert_esign_service on intake.esign for insert with check (
    auth.role() = 'service_role'
);
create policy insert_actions_service on enforcement.actions for insert with check (
    auth.role() = 'service_role'
);
create policy insert_trust_txns_service on finance.trust_txns for insert with check (
    auth.role() = 'service_role'
);
create policy insert_runs_service on ops.runs for insert with check (
    auth.role() = 'service_role'
);

-- Update policies (service role only)
create policy update_cases_service on judgments.cases for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_entities_service on parties.entities for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_roles_service on parties.roles for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_contacts_service on enrichment.contacts for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_assets_service on enrichment.assets for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_collectability_service on enrichment.collectability for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_cadences_service on outreach.cadences for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_attempts_service on outreach.attempts for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_esign_service on intake.esign for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_actions_service on enforcement.actions for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_trust_txns_service on finance.trust_txns for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');
create policy update_runs_service on ops.runs for update using (
    auth.role() = 'service_role'
) with check (auth.role() = 'service_role');

-- View for case balance calculations
create or replace view judgments.v_case_balance as
select
    c.case_id,
    c.index_no,
    c.court,
    c.county,
    c.status,
    c.principal_amt,
    c.costs,
    (
        coalesce(c.principal_amt, 0) * coalesce(c.interest_rate, 0)
        * greatest(0, date_part('day', now()::date - coalesce(c.interest_from, c.judgment_at, c.filed_at, c.created_at::date))) / 365.0
    )::numeric(14, 2) as interest_accrued,
    (
        coalesce(c.principal_amt, 0) + coalesce(c.costs, 0)
        + (
            coalesce(c.principal_amt, 0) * coalesce(c.interest_rate, 0)
            * greatest(0, date_part('day', now()::date - coalesce(c.interest_from, c.judgment_at, c.filed_at, c.created_at::date))) / 365.0
        )
    )::numeric(14, 2) as balance_today,
    co.total_score,
    co.tier
from judgments.cases as c
left join enrichment.collectability as co on c.case_id = co.case_id;

