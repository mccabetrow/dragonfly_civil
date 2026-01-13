# Dragonfly Go-Live Runbook

> **Target:** Zero crash loops, pooler-only connections, strict secret separation  
> **Time to Complete:** 15 minutes  
> **Last Updated:** 2026-01-12

---

## Pre-Flight Checklist

| Check                 | Command / Action                                               | Expected      |
| --------------------- | -------------------------------------------------------------- | ------------- |
| Local migrations pass | `./scripts/db_push.ps1 -SupabaseEnv dev`                       | Exit 0        |
| Doctor passes         | `./.venv/Scripts/python.exe -m tools.doctor_all --env dev`     | All green     |
| Security audit clean  | `./.venv/Scripts/python.exe -m tools.security_audit --env dev` | No violations |
| Dashboard builds      | `cd dragonfly-dashboard && npm run build`                      | Exit 0        |
| Tests pass            | `./.venv/Scripts/python.exe -m pytest -q`                      | 0 failures    |

---

## 1. Supabase Configuration (5 min)

### 1.1 Get Connection Strings

**Path:** Supabase Dashboard → Project → Settings → Database

| String                              | Use For         | Format                                                                                                     |
| ----------------------------------- | --------------- | ---------------------------------------------------------------------------------------------------------- |
| **Connection Pooler (Transaction)** | API + Workers   | `postgresql://postgres.[ref]:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require` |
| **Direct Connection**               | Migrations ONLY | `postgresql://postgres.[ref]:[password]@db.[ref].supabase.co:5432/postgres`                                |

⚠️ **CRITICAL:** Runtime services MUST use port `6543` (pooler). Never `5432` in Railway.

### 1.2 Generate Service Role Key

**Path:** Supabase Dashboard → Project → Settings → API

Copy:

- `service_role` key (secret, never expose to frontend)
- `anon` key (public, read-only operations)
- Project URL (`https://[ref].supabase.co`)

### 1.3 Apply Production Migrations

```powershell
# From local machine with direct connection
$env:SUPABASE_MODE = "prod"
./scripts/db_push.ps1 -SupabaseEnv prod
```

Verify:

```powershell
./.venv/Scripts/python.exe -m tools.migration_status --env prod
```

---

## 2. Railway Configuration (8 min)

### 2.1 Create Services

**Path:** Railway Dashboard → Project → New Service

Create three services:

1. `dragonfly-api` (from GitHub repo, Dockerfile)
2. `dragonfly-worker-ingest` (from GitHub repo, worker.Dockerfile or Procfile)
3. `dragonfly-worker-enforcement` (from GitHub repo, worker.Dockerfile or Procfile)

### 2.2 Environment Variable Matrix

#### Legend

| Symbol | Meaning                     |
| ------ | --------------------------- |
| ✅     | Required                    |
| ❌     | Forbidden (must not be set) |
| ⚪     | Optional                    |

---

#### `dragonfly-api`

| Variable                    | Required | Value / Source                               |
| --------------------------- | -------- | -------------------------------------------- |
| `SUPABASE_URL`              | ✅       | `https://[ref].supabase.co`                  |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | From Supabase Dashboard                      |
| `SUPABASE_ANON_KEY`         | ✅       | From Supabase Dashboard                      |
| `DATABASE_URL`              | ✅       | Pooler string (port 6543, `sslmode=require`) |
| `SUPABASE_DB_URL`           | ❌       | Use `DATABASE_URL` instead                   |
| `SUPABASE_DIRECT_URL`       | ❌       | Never in runtime services                    |
| `SUPABASE_MODE`             | ✅       | `prod`                                       |
| `ENVIRONMENT`               | ✅       | `production`                                 |
| `LOG_LEVEL`                 | ⚪       | `INFO` (default) or `WARNING`                |
| `PORT`                      | ⚪       | Railway injects automatically                |
| `RAILWAY_ENVIRONMENT`       | ⚪       | Railway injects automatically                |

---

#### `dragonfly-worker-ingest`

| Variable                    | Required | Value / Source                               |
| --------------------------- | -------- | -------------------------------------------- |
| `SUPABASE_URL`              | ✅       | `https://[ref].supabase.co`                  |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | From Supabase Dashboard                      |
| `DATABASE_URL`              | ✅       | Pooler string (port 6543, `sslmode=require`) |
| `SUPABASE_MODE`             | ✅       | `prod`                                       |
| `ENVIRONMENT`               | ✅       | `production`                                 |
| `WORKER_TYPE`               | ✅       | `ingest`                                     |
| `SUPABASE_ANON_KEY`         | ❌       | Workers use service_role only                |
| `SUPABASE_DIRECT_URL`       | ❌       | Never in runtime services                    |
| `PORT`                      | ❌       | Workers don't bind ports                     |

---

#### `dragonfly-worker-enforcement`

| Variable                    | Required | Value / Source                               |
| --------------------------- | -------- | -------------------------------------------- |
| `SUPABASE_URL`              | ✅       | `https://[ref].supabase.co`                  |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | From Supabase Dashboard                      |
| `DATABASE_URL`              | ✅       | Pooler string (port 6543, `sslmode=require`) |
| `SUPABASE_MODE`             | ✅       | `prod`                                       |
| `ENVIRONMENT`               | ✅       | `production`                                 |
| `WORKER_TYPE`               | ✅       | `enforcement`                                |
| `SUPABASE_ANON_KEY`         | ❌       | Workers use service_role only                |
| `SUPABASE_DIRECT_URL`       | ❌       | Never in runtime services                    |
| `PORT`                      | ❌       | Workers don't bind ports                     |

---

### 2.3 Railway Click-Path for Env Vars

1. Click service name (e.g., `dragonfly-api`)
2. Click **Variables** tab
3. Click **RAW Editor** (faster for bulk paste)
4. Paste variables in `KEY=VALUE` format
5. Click **Update Variables**
6. Service auto-redeploys

### 2.4 Verify Deployments

**Path:** Railway Dashboard → Service → Deployments

Check each service:

- Build log: no errors
- Deploy log: `Listening on 0.0.0.0:PORT` (API only)
- Health check: green (if configured)

---

## 3. Validation Gate (2 min)

### 3.1 Run Production Gate

```powershell
$env:SUPABASE_MODE = "prod"
./.venv/Scripts/python.exe -m tools.prod_gate --env prod --strict
```

All 4 checks must pass:

- [ ] `/health` returns 200
- [ ] `/readyz` returns 200
- [ ] `doctor_all` exits 0
- [ ] `verify_env_config` exits 0

### 3.2 Smoke Test Views

```powershell
./.venv/Scripts/python.exe -m tools.smoke_plaintiffs --env prod
```

### 3.3 Verify ops Schema Locked

```sql
-- Should return rows for service_role only
SELECT grantee, privilege_type
FROM information_schema.table_privileges
WHERE table_schema = 'ops';
```

---

## 4. Schema Drift Strategy

### 4.1 Golden Rule

> **Never repair migration history. Only append forward-compatible migrations.**

### 4.2 When Prod ≠ Dev

| Scenario                    | Action                                    |
| --------------------------- | ----------------------------------------- |
| Prod has column dev lacks   | Add column to dev migration, deploy       |
| Dev has column prod lacks   | Normal migration flow                     |
| Prod has orphan table       | Leave it; document in `SCHEMA_DRIFT.md`   |
| Policy name conflict        | Use `DROP POLICY IF EXISTS` before create |
| Function signature mismatch | Use `CREATE OR REPLACE`                   |

### 4.3 Safe Exceptions

These patterns are approved for production drift:

```sql
-- Safe: Additive index
CREATE INDEX IF NOT EXISTS idx_foo ON table(col);

-- Safe: Idempotent policy
DROP POLICY IF EXISTS policy_name ON table;
CREATE POLICY policy_name ON table ...;

-- Safe: Column addition
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema='public' AND table_name='t' AND column_name='c'
  ) THEN
    ALTER TABLE public.t ADD COLUMN c type;
  END IF;
END $$;
```

### 4.4 Forbidden Patterns

```sql
-- ❌ Never: Drop column in prod
ALTER TABLE foo DROP COLUMN bar;

-- ❌ Never: Truncate in migration
TRUNCATE TABLE foo;

-- ❌ Never: Assume column exists
UPDATE foo SET bar = 1; -- might fail if bar doesn't exist
```

---

## 5. Rollback Procedures

### 5.1 Service Rollback (Railway)

1. Railway Dashboard → Service → Deployments
2. Find last known-good deployment
3. Click **⋮** → **Rollback**

### 5.2 Schema Rollback

> ⚠️ **Schema rollbacks are append-only.** Never delete migration files.

Create a new migration that reverses the change:

```sql
-- 20260113_000000_revert_foo.sql
ALTER TABLE foo DROP COLUMN IF EXISTS bad_column;
```

---

## 6. Monitoring

### 6.1 Railway Logs

```bash
railway logs -f --service dragonfly-api
railway logs -f --service dragonfly-worker-ingest
railway logs -f --service dragonfly-worker-enforcement
```

### 6.2 Supabase Logs

**Path:** Supabase Dashboard → Project → Logs → Postgres

Filter by:

- `ERROR` - immediate attention
- `WARNING` - review daily
- `pgrst` - PostgREST issues

### 6.3 Health Endpoints

| Service | Endpoint      | Expected                |
| ------- | ------------- | ----------------------- |
| API     | `GET /health` | `{"status": "healthy"}` |
| API     | `GET /readyz` | `{"ready": true}`       |

---

## 7. Emergency Contacts

| Role             | Action                            |
| ---------------- | --------------------------------- |
| On-call Engineer | Check Railway logs first          |
| Database Issues  | Supabase Dashboard → Support      |
| Secret Rotation  | Update Railway env vars, redeploy |

---

## Appendix A: Connection String Validation

```python
# Quick validation script
import re
def validate_pooler_url(url: str) -> bool:
    """Ensure URL uses pooler (6543) with SSL."""
    if ":5432" in url:
        raise ValueError("Direct connection (5432) forbidden in runtime")
    if ":6543" not in url:
        raise ValueError("Must use pooler port 6543")
    if "sslmode=require" not in url and "sslmode=verify" not in url:
        raise ValueError("Must have sslmode=require")
    return True
```

---

## Appendix B: Quick Reference

```
┌─────────────────────────────────────────────────────────────┐
│                    DRAGONFLY ARCHITECTURE                   │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│   ┌─────────────┐    ┌─────────────┐    ┌─────────────┐   │
│   │   Railway   │    │   Railway   │    │   Railway   │   │
│   │   API       │    │   Ingest    │    │ Enforcement │   │
│   │   :PORT     │    │   Worker    │    │   Worker    │   │
│   └──────┬──────┘    └──────┬──────┘    └──────┬──────┘   │
│          │                  │                  │           │
│          └──────────────────┼──────────────────┘           │
│                             │                              │
│                    ┌────────▼────────┐                     │
│                    │  Supabase       │                     │
│                    │  Pooler :6543   │                     │
│                    │  (Transaction)  │                     │
│                    └────────┬────────┘                     │
│                             │                              │
│                    ┌────────▼────────┐                     │
│                    │  PostgreSQL     │                     │
│                    │  (Supabase)     │                     │
│                    └─────────────────┘                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```
