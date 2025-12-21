# Dragonfly Least Privilege Security Model

## Overview

This document describes the least-privilege security model for Dragonfly Civil with three custom roles:

| Role                 | Purpose               | Access Level                  |
| -------------------- | --------------------- | ----------------------------- |
| `dragonfly_app`      | API runtime (FastAPI) | SELECT + EXECUTE on read RPCs |
| `dragonfly_worker`   | Background workers    | Full ops access + write RPCs  |
| `dragonfly_readonly` | Dashboard analytics   | SELECT only on views          |

## Role Hierarchy

```
┌─────────────────────────────────────────────────────────────────────────┐
│  postgres / supabase_admin (reserved - full access, migration owner)   │
├─────────────────────────────────────────────────────────────────────────┤
│  service_role (Supabase built-in - bypasses RLS, used for admin ops)   │
├─────────────────────────────────────────────────────────────────────────┤
│  dragonfly_app    - API runtime (FastAPI backend)                      │
│                     SELECT on most tables, EXECUTE on RPCs             │
│                     NO raw INSERT/UPDATE on protected tables           │
├─────────────────────────────────────────────────────────────────────────┤
│  dragonfly_worker - Background workers (ingest, enforcement, etc.)     │
│                     SELECT + limited INSERT/UPDATE on ops tables       │
│                     EXECUTE on job-related RPCs                        │
├─────────────────────────────────────────────────────────────────────────┤
│  dragonfly_readonly - Dashboard/analytics (read-only access)           │
│                       SELECT only on views and materialized views      │
└─────────────────────────────────────────────────────────────────────────┘
```

## Design Decisions

### 1. RLS on Internal Tables

**Decision: DISABLE RLS on `ops.job_queue` and `ops.worker_heartbeats`**

**Justification:**

- These are purely internal tables, never exposed to end users via PostgREST
- Only accessed by backend services running as `dragonfly_worker`
- Access control is at the role level, not row level
- RLS would add query overhead with zero security benefit
- Simpler debugging and maintenance

**Alternative considered:** Enable RLS with `USING (true)` policies. Rejected because it adds complexity and overhead for no benefit on internal tables.

### 2. SECURITY DEFINER RPCs

All write operations go through SECURITY DEFINER functions with `SET search_path`:

| Function                 | Purpose                  | Accessible By |
| ------------------------ | ------------------------ | ------------- |
| `ops.claim_pending_job`  | Atomic job claiming      | worker only   |
| `ops.update_job_status`  | Job status transitions   | worker only   |
| `ops.register_heartbeat` | Worker heartbeat         | worker only   |
| `ops.queue_job`          | Enqueue new jobs         | worker, app   |
| `ops.log_intake_event`   | Operational logging      | worker, app   |
| `ops.upsert_judgment`    | Judgment creation/update | worker only   |

**Why SECURITY DEFINER?**

- Functions run with owner privileges (postgres)
- Controlled inputs prevent SQL injection
- Role can EXECUTE without raw table access
- Audit trail via function calls

**Why SET search_path?**

- Prevents search_path injection attacks
- Each function specifies exactly which schema it operates in

### 3. Separation of App vs Worker

| Operation                | dragonfly_app | dragonfly_worker |
| ------------------------ | ------------- | ---------------- |
| SELECT tables            | ✓             | ✓                |
| INSERT/UPDATE ops tables | ✗             | ✓                |
| Claim jobs               | ✗             | ✓                |
| Queue jobs               | ✓ (via RPC)   | ✓ (via RPC)      |
| Read analytics           | ✓             | ✓                |

**Why separate roles?**

- Prevents API from directly manipulating job queue
- Limits blast radius of API compromise
- Clearer audit trail
- Supports principle of least privilege

## Migration Files

### Primary Migration

```
supabase/migrations/20251219180000_least_privilege_security_model.sql
```

### Verification Script

```
scripts/sql/verify_role_grants.sql
```

## How to Apply

### 1. Apply the Migration

```bash
# Via Supabase CLI (dev)
npx supabase db push --include-all

# Or via direct SQL in Supabase SQL Editor
# Copy contents of 20251219180000_least_privilege_security_model.sql
```

### 2. Set Role Passwords

**In Supabase SQL Editor (do NOT put in migration files):**

```sql
ALTER ROLE dragonfly_app WITH PASSWORD 'your-secure-app-password';
ALTER ROLE dragonfly_worker WITH PASSWORD 'your-secure-worker-password';
ALTER ROLE dragonfly_readonly WITH PASSWORD 'your-secure-readonly-password';
```

### 3. Update Environment Variables

**Railway API Service:**

```
SUPABASE_DB_URL=postgresql://dragonfly_app:<password>@db.<project>.supabase.co:5432/postgres?sslmode=require
```

**Railway Worker Service:**

```
SUPABASE_DB_URL=postgresql://dragonfly_worker:<password>@db.<project>.supabase.co:5432/postgres?sslmode=require
```

**Dashboard (if using direct DB access):**

```
SUPABASE_DB_URL=postgresql://dragonfly_readonly:<password>@db.<project>.supabase.co:5432/postgres?sslmode=require
```

## How to Verify

### Option 1: SQL Verification Script

```sql
-- In Supabase SQL Editor
\i scripts/sql/verify_role_grants.sql
```

### Option 2: Python Security Audit

```bash
# Against dev
python -m tools.security_audit --env dev --verbose

# Against prod
python -m tools.security_audit --env prod --verbose
```

### Expected Output

```
=== ROLE EXISTENCE CHECK ===
dragonfly_app     | YES | NO  | NO  | NO  | NO
dragonfly_worker  | YES | NO  | NO  | NO  | NO
dragonfly_readonly| YES | NO  | NO  | NO  | NO

=== INTERNAL OPS TABLES - RLS DETAIL ===
job_queue         | DISABLED | OK - RLS disabled for internal table
worker_heartbeats | DISABLED | OK - RLS disabled for internal table

=== PRIVILEGE SUMMARY MATRIX ===
dragonfly_app     | SELECT on public/ops tables | Cannot claim jobs
dragonfly_worker  | Full ops access             | Can claim and process jobs
dragonfly_readonly| SELECT only on views        | No table writes
```

## Rollback Procedure

If you need to revert to service_role-only access:

```sql
-- Revert to service_role access (emergency rollback)
BEGIN;

-- Drop custom roles (this revokes all their grants)
DROP ROLE IF EXISTS dragonfly_readonly;
DROP ROLE IF EXISTS dragonfly_worker;
DROP ROLE IF EXISTS dragonfly_app;

-- Update Railway env vars to use service_role connection string

COMMIT;
```

## Security Checklist

- [ ] Roles created with NOINHERIT, NOCREATEDB, NOCREATEROLE
- [ ] RLS disabled on internal ops tables
- [ ] SECURITY DEFINER functions have SET search_path
- [ ] No CREATE grants on public schema
- [ ] No authenticated/anon access to ops schema
- [ ] Passwords set separately (not in migration files)
- [ ] Connection strings use sslmode=require
- [ ] Verification script passes all checks
