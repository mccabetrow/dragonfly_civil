# Plaintiff Onboarding Operator Checklist — January 10, 2026

> **Date:** 2026-01-10  
> **Operator:** ******\_\_\_******  
> **Shift Start:** ******\_\_\_******  
> **Status:** ☐ GO / ☐ NO-GO

---

## 🚦 Pre-Flight: Pass/Fail Gates

| #   | Check                  | Command / URL                                 | PASS | FAIL |
| --- | ---------------------- | --------------------------------------------- | :--: | :--: |
| 1   | CI Green               | `gh run list --limit 1` shows ✓               |  ☐   |  ☐   |
| 2   | Doctor Clean           | `python -m tools.doctor --env prod` exits 0   |  ☐   |  ☐   |
| 3   | No Uncommitted Changes | `git status -sb` shows nothing                |  ☐   |  ☐   |
| 4   | Migrations Applied     | `python -m tools.migration_status --env prod` |  ☐   |  ☐   |

**If ANY check FAILS → STOP. Fix before proceeding.**

---

## 🔧 Exact Railway Start Commands

| Service                                | Railway Service Name           | Start Command                                  |
| -------------------------------------- | ------------------------------ | ---------------------------------------------- |
| **1. API** (start first)               | `dragonfly-api`                | `python -m tools.run_uvicorn`                  |
| **2. Ingest Worker** (start second)    | `dragonfly-worker-ingest`      | `python -m backend.workers.ingest_processor`   |
| **3. Enforcement Worker** (start last) | `dragonfly-worker-enforcement` | `python -m backend.workers.enforcement_engine` |

### Bring-Up Order (CRITICAL)

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: dragonfly-api         (must be healthy before step 2) │
│  STEP 2: dragonfly-worker-ingest                                │
│  STEP 3: dragonfly-worker-enforcement                           │
└─────────────────────────────────────────────────────────────────┘
```

**Rationale:** API must be ready for healthz probes and scheduler jobs before workers start consuming queues.

---

## ✅ Required Environment Variables

All services **MUST** have these set (Railway Shared Variables):

| Variable                    | Required | Example                                                    | Set? |
| --------------------------- | :------: | ---------------------------------------------------------- | :--: |
| `SUPABASE_URL`              |    ✅    | `https://xxx.supabase.co`                                  |  ☐   |
| `SUPABASE_SERVICE_ROLE_KEY` |    ✅    | `eyJhbG...` (100+ chars, starts with `ey`)                 |  ☐   |
| `SUPABASE_DB_URL`           |    ✅    | `postgresql://...@pooler...:6543/postgres?sslmode=require` |  ☐   |
| `ENVIRONMENT`               |    ✅    | `prod`                                                     |  ☐   |
| `SUPABASE_MODE`             |    ✅    | `prod`                                                     |  ☐   |
| `DRAGONFLY_API_KEY`         |    ✅    | `df_prod_xxxx...` (32+ chars)                              |  ☐   |

### Service-Specific Variables

| Variable                 | Service          |         Required         | Set? |
| ------------------------ | ---------------- | :----------------------: | :--: |
| `PORT`                   | API only         | Auto-injected by Railway |  ☐   |
| `DRAGONFLY_CORS_ORIGINS` | API only         |            ⚠️            |  ☐   |
| `OPENAI_API_KEY`         | Enforcement only |            ⚠️            |  ☐   |
| `DISCORD_WEBHOOK_URL`    | All (optional)   |            ⚪            |  ☐   |
| `LOG_LEVEL`              | All (optional)   |    ⚪ Default: `INFO`    |  ☐   |

---

## 🚫 Forbidden Variables (DELETE if present)

| Variable Pattern               | Risk                    | Action     |
| ------------------------------ | ----------------------- | ---------- |
| `supabase_url` (lowercase)     | Case collision on Linux | **DELETE** |
| `supabase_db_url` (lowercase)  | Case collision on Linux | **DELETE** |
| `SUPABASE_URL_PROD`            | Deprecated suffix       | **DELETE** |
| `SUPABASE_DB_URL_DEV`          | Deprecated suffix       | **DELETE** |
| `SUPABASE_URL_DEV`             | Deprecated suffix       | **DELETE** |
| Any `*_PROD` or `*_DEV` suffix | Split-brain risk        | **DELETE** |
| `PORT` (manually set)          | Railway auto-injects    | **DELETE** |

### Verification Command

```powershell
python scripts/railway_env_audit.py --check
```

Exit code 0 = clean. Exit code 2 or 3 = **STOP and fix**.

---

## 🔐 Pooler DSN Validation

### Expected Format

```
postgresql://postgres.{project-ref}:{password}@aws-0-{region}.pooler.supabase.com:6543/postgres?sslmode=require
```

### Validation Checklist

| Component | Expected                    | Actual           |  ✓  |
| --------- | --------------------------- | ---------------- | :-: |
| Host      | `*.pooler.supabase.com`     | ****\_\_\_\_**** |  ☐  |
| Port      | `6543` (transaction pooler) | ****\_\_\_\_**** |  ☐  |
| SSL       | `?sslmode=require`          | ****\_\_\_\_**** |  ☐  |
| User      | `postgres.{project-ref}`    | ****\_\_\_\_**** |  ☐  |
| Database  | `postgres`                  | ****\_\_\_\_**** |  ☐  |

### ❌ Red Flags (FAIL immediately)

| Issue           | Example              | Risk                                 |
| --------------- | -------------------- | ------------------------------------ |
| Direct DB port  | `:5432/`             | Connection exhaustion                |
| Missing sslmode | No `?sslmode=`       | Data unencrypted in transit          |
| Wrong host      | `db.xxx.supabase.co` | Not pooled, will exhaust connections |
| Weak sslmode    | `sslmode=prefer`     | Downgrade attacks                    |

### Extraction Command (local)

```powershell
$url = $env:SUPABASE_DB_URL
[regex]::Match($url, ':(\d+)/').Groups[1].Value  # Should output: 6543
```

---

## 📍 URLs to Check

### Production API Base

```
https://dragonflycivil-production-d57a.up.railway.app
```

### Health Endpoints

| Endpoint                    | Auth        | Expected Response                                 | cURL                                                                                                                        |
| --------------------------- | ----------- | ------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `GET /health`               | None        | `{"service": "Dragonfly Engine", "status": "ok"}` | `curl -s https://dragonflycivil-production-d57a.up.railway.app/health`                                                      |
| `GET /api/health`           | None        | `{"status": "ok", "version": "..."}`              | `curl -s https://dragonflycivil-production-d57a.up.railway.app/api/health`                                                  |
| `GET /api/v1/intake/health` | `X-API-Key` | `{"status": "ok", "service": "intake-gateway"}`   | `curl -s -H "X-API-Key: $env:DRAGONFLY_API_KEY" https://dragonflycivil-production-d57a.up.railway.app/api/v1/intake/health` |

### Smoke Test Script

```powershell
$env:API_BASE_URL = "https://dragonflycivil-production-d57a.up.railway.app"
python -m tools.prod_smoke_railway
```

---

## 🎯 Pass/Fail Conditions

### ✅ GO Conditions (ALL must be true)

| #   | Condition                                             | Verified |
| --- | ----------------------------------------------------- | :------: |
| 1   | `GET /health` returns 200 with `"status": "ok"`       |    ☐     |
| 2   | `GET /api/health` returns 200 with `"status": "ok"`   |    ☐     |
| 3   | `GET /api/v1/intake/health` returns 200 with API key  |    ☐     |
| 4   | Railway logs show no startup errors                   |    ☐     |
| 5   | Railway logs show "Scheduler started"                 |    ☐     |
| 6   | Railway logs show "polling for jobs" on workers       |    ☐     |
| 7   | All 3 services show "Active" in Railway dashboard     |    ☐     |
| 8   | `SUPABASE_DB_URL` uses port 6543 with sslmode=require |    ☐     |

### 🚫 NO-GO Conditions (ANY triggers rollback)

| Condition                           | Immediate Action                          |
| ----------------------------------- | ----------------------------------------- |
| Any health endpoint returns non-200 | Rollback via Railway dashboard            |
| Logs show "connection refused"      | Verify SUPABASE_DB_URL pooler host        |
| Logs show "401 Unauthorized"        | Verify SUPABASE_SERVICE_ROLE_KEY          |
| Logs show "ModuleNotFoundError"     | Check start command uses `-m` flag        |
| Worker restarts in a loop           | Disable Railway health checks for workers |
| Database connection timeout         | Check pooler (port 6543) vs direct (5432) |

---

## 🔄 Rollback Procedure

### Railway Dashboard (Fastest)

1. Open https://railway.app/dashboard
2. Click failing service → **Deployments** tab
3. Find last working deployment (green ✓)
4. Click **⋮** → **Rollback**
5. Repeat for each affected service

### Railway CLI

```bash
railway rollback
```

---

## 📝 Sign-Off

| Gate                   |     Status      | Operator Initials |  Time  |
| ---------------------- | :-------------: | :---------------: | :----: |
| Pre-Flight Checks      | ☐ PASS / ☐ FAIL |      **\_**       | **\_** |
| Variables Verified     | ☐ PASS / ☐ FAIL |      **\_**       | **\_** |
| Forbidden Vars Removed | ☐ PASS / ☐ FAIL |      **\_**       | **\_** |
| Pooler DSN Validated   | ☐ PASS / ☐ FAIL |      **\_**       | **\_** |
| API Health Check       | ☐ PASS / ☐ FAIL |      **\_**       | **\_** |
| Ingest Worker Up       | ☐ PASS / ☐ FAIL |      **\_**       | **\_** |
| Enforcement Worker Up  | ☐ PASS / ☐ FAIL |      **\_**       | **\_** |

**Final Status:** ☐ **GO** — Ready for plaintiff onboarding  
 ☐ **NO-GO** — Issues documented below

**Notes:**

```
_______________________________________________________________
_______________________________________________________________
_______________________________________________________________
```

---

_Generated from Dragonfly runbooks: [railway.md](../deploy/railway.md), [env_contract.md](../env_contract.md), [RAILWAY_DEPLOY_CHECKLIST.md](./RAILWAY_DEPLOY_CHECKLIST.md), [Ops_Runbook.md](../Ops_Runbook.md)_
