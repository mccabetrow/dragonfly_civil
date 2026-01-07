# Dragonfly Civil – Database Security Contract

> **Version:** 1.0.0  
> **Last Updated:** 2025-01-09  
> **Audience:** Engineers, SREs, Security Auditors

---

## 1. Security Model Overview

Dragonfly Civil uses **Supabase + PostgreSQL** with a layered security model:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT LAYER                                    │
│  Dashboard (React) ←→ PostgREST / Railway API ←→ RLS + Views                │
└─────────────────────────────────────────────────────────────────────────────┘
                                      ↓
┌─────────────────────────────────────────────────────────────────────────────┐
│                              DATABASE LAYER                                  │
│                                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐       │
│  │  public  │  │   api    │  │  intake  │  │   ops    │  │enforce-  │       │
│  │  (core)  │  │  (RPCs)  │  │  (ETL)   │  │  (SRE)   │  │  ment    │       │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────────┘       │
│       ↑              ↑              ↑              ↑              ↑          │
│       └──────────────┴──────────────┴──────────────┴──────────────┘          │
│                         Row-Level Security (RLS)                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Roles & Responsibilities

| Role                | Description              | Access Pattern                          |
| ------------------- | ------------------------ | --------------------------------------- |
| **`anon`**          | Unauthenticated requests | Read-only: dashboard views, api.\* RPCs |
| **`authenticated`** | Logged-in users          | Read views + INSERT via RLS/RPCs        |
| **`service_role`**  | Backend workers          | Full CRUD (bypasses RLS)                |
| **`postgres`**      | Superuser                | Everything (migrations only)            |

### Role Matrix by Schema

| Schema        | `anon`                | `authenticated`       | `service_role` |
| ------------- | --------------------- | --------------------- | -------------- |
| `public`      | USAGE, SELECT (views) | USAGE, SELECT (views) | USAGE, ALL     |
| `api`         | USAGE, EXECUTE        | USAGE, EXECUTE        | USAGE, EXECUTE |
| `intake`      | ❌                    | USAGE (limited)       | USAGE, ALL     |
| `ops`         | ❌                    | ❌                    | USAGE, ALL     |
| `enforcement` | ❌                    | ❌                    | USAGE, ALL     |

---

## 3. Schemas

### `public` – Core Domain

**Purpose:** Core business entities (judgments, plaintiffs, contacts)

**Key Tables:**

- `judgments` – Master judgment records
- `plaintiffs` – Plaintiff demographics
- `plaintiff_contacts` – Phone, email, address
- `plaintiff_status_history` – Status audit trail
- `plaintiff_tasks` – Scheduled outreach tasks
- `job_queue` – Async job processing

**Key Views (Dashboard):**

- `v_plaintiffs_overview` – Plaintiff list with status
- `v_judgment_pipeline` – Judgment funnel metrics
- `v_enforcement_overview` – Enforcement summary
- `v_plaintiff_call_queue` – Next-up call list
- `v_collectability_snapshot` – Tier distribution

### `api` – RPC Surface

**Purpose:** Stored procedures exposed via PostgREST

**Key Functions:**

- `api.get_dashboard_stats()` – CEO metrics
- `api.get_enforcement_overview()` – Enforcement summary
- `api.get_call_queue()` – Next-up calls
- `api.get_ceo_metrics()` – 12 metrics for CEO dashboard

**Security:** All functions are `SECURITY DEFINER` with `search_path = public, pg_temp`.

### `intake` – ETL & Import

**Purpose:** Vendor data staging and import processing

**Key Tables:**

- `simplicity_batches` – Import batch metadata
- `simplicity_import_log` – Row-level import results
- `simplicity_raw` – Raw vendor records

**RLS Policies:**

- `authenticated` can INSERT into `simplicity_batches` (file uploads)
- `service_role` has full access for processing

### `ops` – SRE Monitoring

**Purpose:** Operational visibility and alerting

**Key Tables:**

- `event_log` – Application events
- `outbox` – Transactional outbox for webhooks
- `reaper_log` – Background job tracking

**Key Views:**

- `v_batch_performance` – Import batch metrics
- `v_event_log_recent` – Recent events
- `v_reaper_status` – Background job health
- `v_rls_coverage` – RLS policy audit

### `enforcement` – Collection Workflows

**Purpose:** Judgment enforcement state machine

**Access:** `service_role` only (highly sensitive PII).

---

## 4. Read Paths (Views)

All dashboard data flows through **views**, not tables. Views are the authorized read surface.

### Dashboard-Critical Views

| View                        | Schema   | Purpose                                       |
| --------------------------- | -------- | --------------------------------------------- |
| `v_plaintiffs_overview`     | `public` | Plaintiff list with status, tier              |
| `v_judgment_pipeline`       | `public` | Funnel: intake → collectability → enforcement |
| `v_enforcement_overview`    | `public` | Enforcement metrics (calls, payments)         |
| `v_plaintiff_call_queue`    | `public` | Next-up calls, priority ranked                |
| `v_collectability_snapshot` | `public` | Tier A/B/C/D distribution                     |
| `v_batch_performance`       | `ops`    | Import batch success rates                    |
| `v_reaper_status`           | `ops`    | Background job health                         |

### Fallback Read Path

If PostgREST is unhealthy (PGRST002), the dashboard falls back to the Railway API:

```
Dashboard → /api/v1/dashboard/* → backend.services.dashboard_fallback → Direct SQL
```

See [RUNBOOK_POSTGREST_HEALTH.md](./RUNBOOK_POSTGREST_HEALTH.md) for escalation.

---

## 5. Write Paths

### Principle: No Direct Table Writes

All writes go through:

1. **RLS Policies** – Row-level security on tables
2. **RPCs** – `SECURITY DEFINER` functions in `api.*`
3. **Backend Services** – Python workers using `service_role`

### Write Path Examples

| Operation     | Actor  | Path                                            |
| ------------- | ------ | ----------------------------------------------- |
| Upload CSV    | User   | `POST /intake/simplicity_batches` → RLS INSERT  |
| Import Row    | Worker | `service_role` → `intake.simplicity_raw` INSERT |
| Update Status | Worker | `service_role` → `plaintiffs` UPDATE            |
| Log Event     | Worker | `service_role` → `ops.event_log` INSERT         |
| Queue Job     | RPC    | `api.queue_job()` → `SECURITY DEFINER`          |

---

## 6. SECURITY DEFINER Policy

### Rule

**All `SECURITY DEFINER` functions MUST set `search_path = public, pg_temp`.**

This prevents **search path hijacking attacks** where a malicious actor creates a function in a schema that shadows a trusted function.

### Example

```sql
CREATE OR REPLACE FUNCTION api.get_dashboard_stats()
RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp  -- ← REQUIRED
AS $$
BEGIN
    RETURN jsonb_build_object('status', 'ok');
END;
$$;
```

### Validation

Run the permissions audit to check for unset search paths:

```bash
# Check for SECURITY DEFINER functions without search_path
python -m tools.security_audit --env prod
```

---

## 7. RLS Policy Reference

### Core Tables

| Table                | RLS Enabled | `authenticated` Policy | `service_role` Policy |
| -------------------- | ----------- | ---------------------- | --------------------- |
| `judgments`          | ✓           | SELECT only            | ALL                   |
| `plaintiffs`         | ✓           | SELECT only            | ALL                   |
| `plaintiff_contacts` | ✓           | SELECT only            | ALL                   |
| `job_queue`          | ✓           | None                   | ALL                   |

### Intake Tables

| Table                   | RLS Enabled | `authenticated` Policy | `service_role` Policy |
| ----------------------- | ----------- | ---------------------- | --------------------- |
| `simplicity_batches`    | ✓           | INSERT, SELECT         | ALL                   |
| `simplicity_import_log` | ✓           | None                   | ALL                   |
| `simplicity_raw`        | ✓           | None                   | ALL                   |

---

## 8. Golden SQL Statements

Reference SQL for granting permissions (applied via migration):

### Schema Usage

```sql
-- Grant USAGE on schemas
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;
GRANT USAGE ON SCHEMA api TO anon, authenticated, service_role;
GRANT USAGE ON SCHEMA intake TO service_role;
GRANT USAGE ON SCHEMA ops TO service_role;
GRANT USAGE ON SCHEMA enforcement TO service_role;
```

### View Access

```sql
-- Grant SELECT on dashboard views
GRANT SELECT ON public.v_plaintiffs_overview TO anon, authenticated, service_role;
GRANT SELECT ON public.v_judgment_pipeline TO anon, authenticated, service_role;
GRANT SELECT ON public.v_enforcement_overview TO anon, authenticated, service_role;
GRANT SELECT ON ops.v_batch_performance TO anon, authenticated, service_role;
```

### RPC Execute

```sql
-- Grant EXECUTE on api.* RPCs
GRANT EXECUTE ON FUNCTION api.get_dashboard_stats() TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION api.get_enforcement_overview() TO anon, authenticated, service_role;
```

### Function Hardening

```sql
-- Set search_path on SECURITY DEFINER functions
ALTER FUNCTION api.get_dashboard_stats() SET search_path = public, pg_temp;
ALTER FUNCTION ops.complete_outbox_message(UUID) SET search_path = public, pg_temp;
```

---

## 9. Audit & Validation

### Daily Checks

```bash
# Run security audit (checks RLS, grants, search paths)
python -m tools.security_audit --env prod

# Run doctor to verify views and tables exist
python -m tools.doctor --env prod

# Check for permission drift
python -m tools.check_schema_consistency --env prod
```

### Migration Workflow

1. **Author migration** in `supabase/migrations/YYYYMMDDHHMMSS_name.sql`
2. **Apply to dev**: `./scripts/db_push.ps1 -SupabaseEnv dev`
3. **Run doctor**: `python -m tools.doctor_all --env dev`
4. **Run security audit**: `python -m tools.security_audit --env dev`
5. **Apply to prod**: `./scripts/db_push.ps1 -SupabaseEnv prod`

---

## 10. Incident Response

### PGRST002 (Schema Cache Invalid)

1. Run `python -m tools.fix_schema_cache --env prod`
2. If fix fails, escalate via Discord webhook
3. Dashboard auto-fallback to `/api/v1/dashboard/*`

### Permission Denied Errors

1. Check role in JWT: `SELECT current_role;`
2. Check schema USAGE: `SELECT has_schema_privilege('anon', 'public', 'USAGE');`
3. Check table SELECT: `SELECT has_table_privilege('anon', 'public.v_plaintiffs_overview', 'SELECT');`
4. Re-apply migration if needed

### RLS Bypass Needed

Only `service_role` can bypass RLS. If a backend worker hits permission errors:

1. Verify it's using `SUPABASE_SERVICE_ROLE_KEY`
2. Check `get_supabase_env()` is returning correct env
3. Run `python -m tools.smoke_plaintiffs --env prod`

---

## 11. Change Log

| Date       | Version | Author        | Changes                   |
| ---------- | ------- | ------------- | ------------------------- |
| 2025-01-09 | 1.0.0   | Security Team | Initial security contract |

---

## Appendix: Quick Reference

### Check Current Role

```sql
SELECT current_role, current_user, session_user;
```

### Check Schema Privileges

```sql
SELECT nspname, has_schema_privilege('anon', nspname, 'USAGE') AS anon_usage
FROM pg_namespace
WHERE nspname IN ('public', 'api', 'intake', 'ops', 'enforcement');
```

### List SECURITY DEFINER Functions

```sql
SELECT n.nspname, p.proname,
       pg_get_function_identity_arguments(p.oid) AS args,
       array_to_string(p.proconfig, ', ') AS config
FROM pg_proc p
JOIN pg_namespace n ON p.pronamespace = n.oid
WHERE p.prosecdef = true
  AND n.nspname IN ('public', 'api', 'ops', 'intake', 'enforcement')
ORDER BY n.nspname, p.proname;
```

### List RLS Policies

```sql
SELECT schemaname, tablename, policyname, roles, cmd, qual
FROM pg_policies
WHERE schemaname IN ('public', 'intake', 'ops', 'enforcement')
ORDER BY schemaname, tablename, policyname;
```
