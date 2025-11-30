# Dragonfly Civil – Security & Compliance Audit

> **Generated**: November 30, 2025  
> **Scope**: Supabase schema, RLS policies, RPCs, API endpoints, FCRA/FDCPA compliance gaps  
> **Repository**: `dragonfly_civil` (branch: `release/golden-prod`)

---

## Executive Summary

This audit identifies the current state of row-level security (RLS), access control, and regulatory compliance for judgment/consumer data in the Dragonfly Civil codebase. We provide actionable recommendations for:

1. Enforcing least-privilege access on all judgment-related tables
2. Logging external data API calls with `judgment_id` for FCRA audit trails
3. Enforcing FDCPA contact-time and venue constraints in automation

---

## 1. Tables Containing Judgment/Consumer Data

### 1.1 Core Judgment Tables

| Schema   | Table                      | Purpose                                                       | Contains Consumer PII                           |
| -------- | -------------------------- | ------------------------------------------------------------- | ----------------------------------------------- |
| `public` | `judgments`                | Primary judgment records (case_number, debtor names, amounts) | **Yes** – defendant_name, plaintiff_name        |
| `public` | `core_judgments`           | New canonical judgment schema (0200 migration)                | **Yes** – debtor_name, original_creditor        |
| `public` | `debtor_intelligence`      | Enriched debtor data (employer, bank, income)                 | **Yes** – employer_name, bank_name, income_band |
| `public` | `plaintiffs`               | Plaintiff entities and contacts                               | **Yes** – name, contact info                    |
| `public` | `plaintiff_contacts`       | Phone, email, address for plaintiffs                          | **Yes** – PII contact data                      |
| `public` | `plaintiff_status_history` | Status audit trail for plaintiffs                             | No                                              |

### 1.2 Enforcement Tables

| Schema   | Table                     | Purpose                                     | Contains Consumer PII            |
| -------- | ------------------------- | ------------------------------------------- | -------------------------------- |
| `public` | `enforcement_cases`       | Tracks enforcement proceedings per judgment | **Yes** – linked to judgment_id  |
| `public` | `enforcement_actions`     | Actions taken (levy, garnishment, etc.)     | **Yes** – linked to judgment_id  |
| `public` | `enforcement_timeline`    | Event log for enforcement lifecycle         | **Yes** – linked to judgment_id  |
| `public` | `enforcement_evidence`    | Evidence files for enforcement cases        | **Yes** – linked to case_id      |
| `public` | `plaintiff_tasks`         | Task queue for plaintiff outreach           | **Yes** – linked to plaintiff_id |
| `public` | `plaintiff_call_attempts` | Call log with outcomes                      | **Yes** – phone interactions     |

### 1.3 Enrichment & Audit Tables

| Schema       | Table             | Purpose                                | Contains Consumer PII                   |
| ------------ | ----------------- | -------------------------------------- | --------------------------------------- |
| `judgments`  | `cases`           | Legacy case records                    | **Yes** – case_number, judgment amounts |
| `judgments`  | `enrichment_runs` | Enrichment job audit trail             | No – but references case_id             |
| `judgments`  | `foil_responses`  | FOIL agency response payloads          | **Yes** – agency data about debtors     |
| `parties`    | `entities`        | Party records (plaintiffs, defendants) | **Yes** – name_full, emails, phones     |
| `enrichment` | `contacts`        | Contact discovery data                 | **Yes** – phone, email                  |
| `enrichment` | `assets`          | Asset discovery data                   | **Yes** – asset types, values           |
| `enrichment` | `collectability`  | Collectability scores                  | No – but linked to entity_id            |

---

## 2. Current RLS & Access Control State

### 2.1 RLS Enabled Tables (Verified)

The following tables have `ROW LEVEL SECURITY` enabled via migrations:

| Table                            | RLS Enabled | RLS Forced | Migration                                                      |
| -------------------------------- | ----------- | ---------- | -------------------------------------------------------------- |
| `public.judgments`               | ✅          | ✅         | `0066_rls_hardening.sql`, `0149_core_rls_hardening.sql`        |
| `public.plaintiffs`              | ✅          | ✅         | `0071_plaintiff_model.sql`, `0149_core_rls_hardening.sql`      |
| `public.enforcement_cases`       | ✅          | ✅         | `0091_enforcement_cases.sql`, `0149_core_rls_hardening.sql`    |
| `public.enforcement_timeline`    | ✅          | ✅         | `0127_enforcement_timeline.sql`, `0149_core_rls_hardening.sql` |
| `public.enforcement_evidence`    | ✅          | ✅         | `0149_core_rls_hardening.sql`                                  |
| `public.plaintiff_tasks`         | ✅          | ✅         | `0149_core_rls_hardening.sql`                                  |
| `public.plaintiff_call_attempts` | ✅          | ✅         | `0149_core_rls_hardening.sql`                                  |
| `public.core_judgments`          | ✅          | ❌         | `0200_core_judgment_schema.sql`                                |
| `public.debtor_intelligence`     | ✅          | ❌         | `0200_core_judgment_schema.sql`                                |
| `public.enforcement_actions`     | ✅          | ❌         | `0200_core_judgment_schema.sql`                                |
| `judgments.enrichment_runs`      | ✅          | ❌         | `0066_rls_hardening.sql`                                       |
| `judgments.foil_responses`       | ✅          | ❌         | `0066_rls_hardening.sql`                                       |
| `judgments.cases`                | ✅          | ❌         | `0007_rls_policies.sql`, `0022_rls_policies.sql`               |
| `parties.entities`               | ✅          | ❌         | `0007_rls_policies.sql`, `0022_rls_policies.sql`               |

### 2.2 RLS Policy Patterns

Most tables follow this pattern:

```sql
-- Read: anon, authenticated, service_role
CREATE POLICY table_select_public ON public.table FOR SELECT
  USING (auth.role() IN ('anon', 'authenticated', 'service_role'));

-- Write: service_role only
CREATE POLICY table_insert_service ON public.table FOR INSERT
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY table_update_service ON public.table FOR UPDATE
  USING (auth.role() = 'service_role')
  WITH CHECK (auth.role() = 'service_role');

CREATE POLICY table_delete_service ON public.table FOR DELETE
  USING (auth.role() = 'service_role');
```

### 2.3 SECURITY DEFINER Functions (Elevated Privilege RPCs)

The following public RPCs run with `SECURITY DEFINER` (owner privileges):

| Function                                         | Purpose                      | Restricted to service_role |
| ------------------------------------------------ | ---------------------------- | -------------------------- |
| `public.insert_case()`                           | Upsert case records          | ✅ Yes                     |
| `public.insert_case_with_entities()`             | Upsert case + party entities | ✅ Yes                     |
| `public.upsert_enrichment_bundle()`              | Batch enrichment updates     | ✅ Yes                     |
| `public.set_case_enrichment()`                   | Update case enrichment       | ✅ Yes                     |
| `public.set_case_scores()`                       | Update case scores           | ✅ Yes                     |
| `public.add_enforcement_event()`                 | Log enforcement events       | ✅ Yes                     |
| `public.log_call_outcome()`                      | Record call attempts         | ✅ Yes                     |
| `public.generate_enforcement_tasks()`            | Generate tasks for a case    | ✅ Yes                     |
| `public.copilot_case_context()`                  | AI context for case          | ✅ Yes                     |
| `public.spawn_enforcement_flow()`                | Trigger enforcement workflow | ✅ Yes                     |
| `public.log_event()` / `log_enforcement_event()` | Ops event logging            | ✅ Yes                     |
| `public.ops_triage_alerts_fetch()` / `_ack()`    | Alert management             | ✅ Yes                     |
| `public.pgmq_metrics()`                          | Queue metrics                | ✅ Yes                     |
| `public.dequeue_job()`                           | Job queue operations         | ✅ Yes                     |
| `public.pgrst_reload()`                          | PostgREST cache refresh      | ✅ Yes                     |

**⚠️ Gap Identified**: All `SECURITY DEFINER` functions are properly restricted to `service_role`, but there is **no audit logging** within these functions for FCRA compliance.

### 2.4 Grant Analysis Summary

From `tools/security_audit.py` and migrations:

- **Restricted Tables** (no anon/authenticated access): `import_runs`, `enforcement_cases`, `enforcement_events`, `enforcement_evidence`
- **Pipeline Views** (SELECT for anon/authenticated): `v_plaintiffs_overview`, `v_judgment_pipeline`, `v_enforcement_overview`, `v_enforcement_recent`, `v_plaintiff_call_queue`
- **Metrics Views** (service_role only): `v_metrics_intake_daily`, `v_metrics_pipeline`, `v_metrics_enforcement`

---

## 3. API Endpoints That May Expose Sensitive Data

### 3.1 FastAPI Endpoints (`src/api/app.py`)

| Endpoint                | Method | Auth Required | Data Exposed                                  |
| ----------------------- | ------ | ------------- | --------------------------------------------- |
| `/api/cases`            | POST   | ✅ X-API-Key  | Creates/updates judgment cases                |
| `/api/outreach-events`  | POST   | ✅ X-API-Key  | Logs outreach to `outreach_log`               |
| `/api/webhooks/inbound` | POST   | ✅ X-API-Key  | Records inbound messages, updates case status |
| `/api/tasks/complete`   | POST   | ✅ X-API-Key  | Marks enforcement tasks complete              |
| `/healthz`              | GET    | ❌            | None (health check)                           |

**Current Protection**:

- All mutation endpoints require `X-API-Key` header validated against `N8N_API_KEY`
- Environment override via `X-Dragonfly-Env` header (dev/prod)

**⚠️ Gaps Identified**:

1. No rate limiting on API endpoints
2. No request-level audit logging (who called, when, with what judgment_id)
3. API key is single shared secret (no per-client keys)

### 3.2 Streamlit Dashboard (`apps/dragonfly_dashboard.py`)

- Uses `service_role` key to query Supabase
- Queries `core_judgments` joined to `debtor_intelligence`
- Triggers n8n webhook with `judgment_id`

**⚠️ Gaps**:

1. No authentication on the Streamlit app (anyone with URL can access)
2. Uses service_role which bypasses RLS (intentional for dashboard, but risky)

---

## 4. Compliance Gap Analysis

### 4.1 FCRA Audit Trail Requirements

The Fair Credit Reporting Act (FCRA) requires a permissible purpose audit trail for any consumer data access from credit bureaus or skip-trace vendors.

**Current State**: ❌ Not implemented

**Required**:

- Log every external API call (skip-trace, LexisNexis, FOIL requests) with:
  - `judgment_id` or `entity_id` being queried
  - Timestamp
  - API endpoint called
  - User/service that initiated the request
  - Permissible purpose code
  - Response summary (hit/no-hit, confidence)

**Affected Code Paths**:

- `etl/src/worker_enrich.py` - enrichment workers
- `src/workers/enrich_bundle.py` - enrichment bundle updates
- Any future LexisNexis/TLO/Experian integrations

### 4.2 FDCPA Contact-Time Restrictions

The Fair Debt Collection Practices Act (FDCPA) prohibits contacting consumers:

- Before 8:00 AM local time
- After 9:00 PM local time
- At inconvenient times/places if known

**Current State**: ❌ Not enforced in automation

**Affected Code Paths**:

- `tools/task_planner.py` - schedules plaintiff tasks
- `brain/escalation_engine.py` - determines enforcement actions
- n8n workflows that trigger outreach

**Required**:

- Add `debtor_timezone` column to debtor records (default `America/New_York`)
- Pre-execution check in any outreach automation: `8 <= local_hour <= 21`
- Log contact attempts with local time for audit

### 4.3 FDCPA Venue Requirements

Debt collection actions must be filed in:

- The judicial district where the consumer signed the contract, OR
- The judicial district where the consumer resides at commencement

**Current State**: ⚠️ Partially tracked

- `public.judgments` has `county` column
- `public.core_judgments` has `county` column
- No explicit validation that enforcement venue matches debtor residence

---

## 5. Recommended Migrations/Policy Changes

### 5.1 PRIORITY 1: FCRA Audit Log Table

**Purpose**: Create an audit trail for all external data API calls.

```sql
-- File: supabase/migrations/0201_fcra_audit_log.sql

CREATE TABLE IF NOT EXISTS public.data_access_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- What was accessed
    judgment_id uuid REFERENCES public.core_judgments(id),
    entity_id uuid,  -- if querying parties.entities
    case_id uuid,    -- legacy judgments.cases reference

    -- Access details
    api_endpoint text NOT NULL,          -- 'lexisnexis/person_search', 'foil/nyc_finance'
    api_provider text NOT NULL,          -- 'lexisnexis', 'tlo', 'foil', 'internal'
    permissible_purpose text NOT NULL,   -- 'debt_collection', 'litigation', 'skip_trace'

    -- Request context
    requested_by text NOT NULL,          -- service account, user email, or workflow name
    request_metadata jsonb DEFAULT '{}', -- query parameters, filters used

    -- Response summary
    response_status text,                -- 'hit', 'no_hit', 'error', 'partial'
    confidence_score numeric(5,2),       -- if applicable
    response_metadata jsonb DEFAULT '{}',

    -- Timestamps
    requested_at timestamptz NOT NULL DEFAULT timezone('utc', now()),
    responded_at timestamptz,

    created_at timestamptz NOT NULL DEFAULT timezone('utc', now())
);

-- Index for audit queries
CREATE INDEX idx_data_access_audit_judgment ON public.data_access_audit(judgment_id);
CREATE INDEX idx_data_access_audit_requested_at ON public.data_access_audit(requested_at DESC);
CREATE INDEX idx_data_access_audit_provider ON public.data_access_audit(api_provider);

-- RLS: service_role only (this is sensitive audit data)
ALTER TABLE public.data_access_audit ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.data_access_audit FORCE ROW LEVEL SECURITY;

CREATE POLICY data_access_audit_service_only ON public.data_access_audit
FOR ALL USING (auth.role() = 'service_role')
WITH CHECK (auth.role() = 'service_role');

REVOKE ALL ON public.data_access_audit FROM PUBLIC, anon, authenticated;
GRANT ALL ON public.data_access_audit TO service_role;

-- Helper RPC for logging
CREATE OR REPLACE FUNCTION public.log_data_access(
    p_judgment_id uuid,
    p_api_endpoint text,
    p_api_provider text,
    p_permissible_purpose text,
    p_requested_by text,
    p_response_status text DEFAULT NULL,
    p_confidence_score numeric DEFAULT NULL,
    p_request_metadata jsonb DEFAULT '{}',
    p_response_metadata jsonb DEFAULT '{}'
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE v_id uuid;
BEGIN
    INSERT INTO public.data_access_audit (
        judgment_id, api_endpoint, api_provider, permissible_purpose,
        requested_by, response_status, confidence_score,
        request_metadata, response_metadata, responded_at
    ) VALUES (
        p_judgment_id, p_api_endpoint, p_api_provider, p_permissible_purpose,
        p_requested_by, p_response_status, p_confidence_score,
        p_request_metadata, p_response_metadata,
        CASE WHEN p_response_status IS NOT NULL THEN timezone('utc', now()) ELSE NULL END
    )
    RETURNING id INTO v_id;

    RETURN v_id;
END;
$$;

REVOKE ALL ON FUNCTION public.log_data_access FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.log_data_access TO service_role;
```

### 5.2 PRIORITY 2: FDCPA Contact-Time Guard

**Purpose**: Add debtor timezone tracking and contact-time validation.

```sql
-- File: supabase/migrations/0202_fdcpa_contact_guard.sql

-- Add timezone to debtor intelligence
ALTER TABLE public.debtor_intelligence
ADD COLUMN IF NOT EXISTS debtor_timezone text DEFAULT 'America/New_York';

-- Add timezone to core_judgments for simpler access
ALTER TABLE public.core_judgments
ADD COLUMN IF NOT EXISTS debtor_timezone text DEFAULT 'America/New_York';

-- Contact guard function
CREATE OR REPLACE FUNCTION public.is_fdcpa_contact_allowed(
    p_debtor_timezone text DEFAULT 'America/New_York'
) RETURNS boolean
LANGUAGE plpgsql IMMUTABLE
AS $$
DECLARE
    local_hour integer;
BEGIN
    -- Get current hour in debtor's timezone
    local_hour := EXTRACT(HOUR FROM (timezone('utc', now()) AT TIME ZONE COALESCE(p_debtor_timezone, 'America/New_York')));

    -- FDCPA: No contact before 8 AM or after 9 PM local time
    RETURN local_hour >= 8 AND local_hour < 21;
END;
$$;

-- Convenience function for checking a specific judgment
CREATE OR REPLACE FUNCTION public.can_contact_debtor(p_judgment_id uuid)
RETURNS TABLE (
    allowed boolean,
    local_hour integer,
    debtor_timezone text,
    reason text
)
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_timezone text;
    v_hour integer;
    v_allowed boolean;
BEGIN
    -- Get timezone from core_judgments or fall back to America/New_York
    SELECT COALESCE(cj.debtor_timezone, 'America/New_York')
    INTO v_timezone
    FROM public.core_judgments cj
    WHERE cj.id = p_judgment_id;

    IF v_timezone IS NULL THEN
        v_timezone := 'America/New_York';
    END IF;

    v_hour := EXTRACT(HOUR FROM (timezone('utc', now()) AT TIME ZONE v_timezone));
    v_allowed := v_hour >= 8 AND v_hour < 21;

    RETURN QUERY SELECT
        v_allowed,
        v_hour,
        v_timezone,
        CASE
            WHEN v_allowed THEN 'Contact allowed'
            WHEN v_hour < 8 THEN 'Too early (before 8 AM local)'
            ELSE 'Too late (after 9 PM local)'
        END;
END;
$$;

GRANT EXECUTE ON FUNCTION public.is_fdcpa_contact_allowed TO service_role;
GRANT EXECUTE ON FUNCTION public.can_contact_debtor TO service_role;
```

### 5.3 PRIORITY 3: Force RLS on New Tables + Dashboard Auth

**Purpose**: Complete RLS hardening for 0200 schema tables.

```sql
-- File: supabase/migrations/0203_rls_force_core_judgment_tables.sql

-- Force RLS on new core judgment tables (currently only enabled, not forced)
ALTER TABLE public.core_judgments FORCE ROW LEVEL SECURITY;
ALTER TABLE public.debtor_intelligence FORCE ROW LEVEL SECURITY;
ALTER TABLE public.enforcement_actions FORCE ROW LEVEL SECURITY;

-- Revoke unnecessary grants (defense in depth)
REVOKE INSERT, UPDATE, DELETE ON public.core_judgments FROM anon, authenticated, PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON public.debtor_intelligence FROM anon, authenticated, PUBLIC;
REVOKE INSERT, UPDATE, DELETE ON public.enforcement_actions FROM anon, authenticated, PUBLIC;

-- Ensure only service_role can write
GRANT INSERT, UPDATE, DELETE ON public.core_judgments TO service_role;
GRANT INSERT, UPDATE, DELETE ON public.debtor_intelligence TO service_role;
GRANT INSERT, UPDATE, DELETE ON public.enforcement_actions TO service_role;

SELECT public.pgrst_reload();
```

---

## 6. Implementation Checklist

### Immediate Actions (This Sprint)

- [ ] Apply migration `0201_fcra_audit_log.sql` to dev
- [ ] Update `etl/src/worker_enrich.py` to call `log_data_access()` before/after enrichment API calls
- [ ] Apply migration `0202_fdcpa_contact_guard.sql` to dev
- [ ] Update `tools/task_planner.py` to call `can_contact_debtor()` before scheduling outreach tasks
- [ ] Apply migration `0203_rls_force_core_judgment_tables.sql` to dev

### Near-Term (Next 2 Sprints)

- [ ] Add Streamlit authentication (e.g., Supabase Auth, SSO, or basic auth)
- [ ] Implement per-client API keys with rotation policy
- [ ] Add rate limiting to FastAPI endpoints
- [ ] Add `debtor_timezone` population from skip-trace/FOIL data
- [ ] Create n8n node to check `can_contact_debtor()` before outreach

### Validation

- [ ] Run `python -m tools.security_audit --env dev` after each migration
- [ ] Run `python -m tools.doctor --env dev` to verify health
- [ ] Verify no new violations in security audit output

---

## 7. Risk Summary

| Risk                         | Severity   | Current Status         | Mitigation             |
| ---------------------------- | ---------- | ---------------------- | ---------------------- |
| FCRA audit trail missing     | **High**   | ❌ Not implemented     | Migration 0201         |
| FDCPA contact-time violation | **High**   | ❌ Not enforced        | Migration 0202         |
| RLS not forced on new tables | **Medium** | ⚠️ Enabled only        | Migration 0203         |
| Dashboard unauthenticated    | **Medium** | ⚠️ Open access         | Add auth layer         |
| Single shared API key        | **Low**    | ⚠️ Working but fragile | Implement key rotation |

---

## Appendix A: Full Table Inventory

<details>
<summary>Click to expand full table list with RLS status</summary>

### `public` schema

| Table                      | RLS Enabled | RLS Forced | Notes                     |
| -------------------------- | ----------- | ---------- | ------------------------- |
| `judgments`                | ✅          | ✅         | Primary judgment table    |
| `core_judgments`           | ✅          | ❌ → ✅    | **Action: Force RLS**     |
| `debtor_intelligence`      | ✅          | ❌ → ✅    | **Action: Force RLS**     |
| `enforcement_actions`      | ✅          | ❌ → ✅    | **Action: Force RLS**     |
| `plaintiffs`               | ✅          | ✅         |                           |
| `plaintiff_contacts`       | ✅          | ❌         |                           |
| `plaintiff_status_history` | ✅          | ❌         |                           |
| `enforcement_cases`        | ✅          | ✅         |                           |
| `enforcement_timeline`     | ✅          | ✅         |                           |
| `enforcement_evidence`     | ✅          | ✅         |                           |
| `enforcement_events`       | ✅          | ❌         |                           |
| `plaintiff_tasks`          | ✅          | ✅         |                           |
| `plaintiff_call_attempts`  | ✅          | ✅         |                           |
| `outreach_log`             | ❓          | ❓         | Review needed             |
| `import_runs`              | ❓          | ❓         | Review needed             |
| `ops_metadata`             | ❓          | ❓         | Ops table, less sensitive |
| `ops_triage_alerts`        | ❓          | ❓         | Ops table                 |

### `judgments` schema

| Table             | RLS Enabled | RLS Forced |
| ----------------- | ----------- | ---------- |
| `cases`           | ✅          | ❌         |
| `enrichment_runs` | ✅          | ❌         |
| `foil_responses`  | ✅          | ❌         |

### `parties` schema

| Table      | RLS Enabled | RLS Forced |
| ---------- | ----------- | ---------- |
| `entities` | ✅          | ❌         |
| `roles`    | ✅          | ❌         |

### `enrichment` schema

| Table            | RLS Enabled | RLS Forced |
| ---------------- | ----------- | ---------- |
| `contacts`       | ✅          | ❌         |
| `assets`         | ✅          | ❌         |
| `collectability` | ✅          | ❌         |

</details>

---

## Appendix B: Security Audit Tool Reference

Run the built-in security audit:

```bash
# Dev environment
python -m tools.security_audit --env dev

# Prod environment (use with caution)
python -m tools.security_audit --env prod
```

The tool checks:

- RLS enabled/forced on key tables
- Write grants restricted to `service_role`
- Pipeline views read-only for `anon`/`authenticated`
- No unexpected grants on restricted tables

---

_Document maintained by Dragonfly Civil engineering. Last updated: November 30, 2025._
