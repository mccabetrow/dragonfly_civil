# Railway Production Environment Audit Checklist

> **Scope:** dragonfly-api, dragonfly-worker-ingest, dragonfly-worker-enforce  
> **Last Updated:** 2026-01-10  
> **Environment:** Production

---

## Quick Navigation (Railway UI Click Path)

```
Railway Dashboard → Project: dragonfly-civil → Environment: production
```

For each service:

1. Click service name in left sidebar
2. **Settings** tab → Start Command
3. **Variables** tab → View/Edit environment variables
4. **Metrics** tab → Resource usage
5. **Settings** tab → Scaling section

---

## 1. API Start Command Verification

### Click Path

```
dragonfly-api → Settings → Deploy → Start Command
```

### ✅ Expected Perfect State

| Field         | Expected Value                |
| ------------- | ----------------------------- |
| Start Command | `python -m tools.run_uvicorn` |

### ❌ Red Flags

- `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` (legacy, bypasses our hardened launcher)
- Any command containing hardcoded port numbers
- Missing or empty start command (falls back to Procfile which should also be correct)

---

## 2. Forbidden Variables Check

### Click Path (for each service)

```
[service] → Variables → Search for "MIGRATE"
```

### ✅ Expected Perfect State

| Variable                  | Expected           |
| ------------------------- | ------------------ |
| `SUPABASE_MIGRATE_DB_URL` | **MUST NOT EXIST** |

### ❌ Red Flags

- `SUPABASE_MIGRATE_DB_URL` present in ANY runtime service
- Any variable containing `5432` (direct DB port) in the value

### Why This Matters

The migrate URL uses port 5432 (direct connection) which:

- Bypasses the transaction pooler
- Can exhaust Supabase connection limits
- Triggers `config_guard.py` to abort startup in production

---

## 3. Database URL Validation

### Click Path

```
[service] → Variables → SUPABASE_DB_URL
```

### ✅ Expected Perfect State

| Component    | Expected Value                                         |
| ------------ | ------------------------------------------------------ |
| Host         | `aws-0-us-east-1.pooler.supabase.com` (or your region) |
| Port         | `6543` (transaction pooler)                            |
| Database     | `postgres`                                             |
| User         | `postgres.{project-ref}`                               |
| Query params | `?sslmode=require`                                     |

### URL Format Validation

```
postgresql://postgres.{project-ref}:{password}@{pooler-host}:6543/postgres?sslmode=require
```

### Verification Script (run locally)

```powershell
# Extract port from your URL (should output 6543)
$url = $env:SUPABASE_DB_URL
[regex]::Match($url, ':(\d+)/').Groups[1].Value
```

### ❌ Red Flags

| Issue           | Example                | Risk                            |
| --------------- | ---------------------- | ------------------------------- |
| Direct DB port  | `:5432/`               | Connection exhaustion, lockouts |
| Missing sslmode | No `?sslmode=`         | Data in transit unencrypted     |
| Weak sslmode    | `sslmode=prefer`       | Downgrade attacks possible      |
| Wrong pooler    | `db.{ref}.supabase.co` | Direct connection, not pooled   |

---

## 4. Variable Consistency Matrix

### Click Path

Open each service's Variables tab side-by-side (use multiple browser tabs).

### ✅ Expected Perfect State

All three services MUST have **identical values** for shared variables:

| Variable                    | dragonfly-api | worker-ingest | worker-enforce | Notes                |
| --------------------------- | ------------- | ------------- | -------------- | -------------------- |
| `ENVIRONMENT`               | `prod`        | `prod`        | `prod`         | Exact match required |
| `SUPABASE_URL`              | ✓ same        | ✓ same        | ✓ same         | REST API endpoint    |
| `SUPABASE_DB_URL`           | ✓ same        | ✓ same        | ✓ same         | Pooler connection    |
| `SUPABASE_SERVICE_ROLE_KEY` | ✓ same        | ✓ same        | ✓ same         | Service role JWT     |
| `DRAGONFLY_API_KEY`         | ✓ same        | ✓ same        | ✓ same         | Internal auth        |
| `DISCORD_WEBHOOK_URL`       | ✓ same        | ✓ same        | ✓ same         | Alerting             |

### Service-Specific Variables (OK to differ)

| Variable          | dragonfly-api  | worker-ingest  | worker-enforce |
| ----------------- | -------------- | -------------- | -------------- |
| `PORT`            | (Railway auto) | (Railway auto) | (Railway auto) |
| `WORKER_MODE`     | —              | `true`         | `true`         |
| `WEB_CONCURRENCY` | `2`            | —              | —              |

### ❌ Red Flags

- Different `SUPABASE_DB_URL` across services (split-brain risk)
- Missing `ENVIRONMENT=prod` on any service
- Typos in variable names (e.g., `SUPABASE_DB_URLL`)

---

## 5. Required Variables Checklist

### Click Path

```
[service] → Variables
```

### ✅ Minimum Required Variables

| Variable                    | Purpose         | Example Value                                         |
| --------------------------- | --------------- | ----------------------------------------------------- |
| `ENVIRONMENT`               | Env detection   | `prod`                                                |
| `SUPABASE_URL`              | REST API base   | `https://xxx.supabase.co`                             |
| `SUPABASE_DB_URL`           | Postgres pooler | `postgresql://...@...:6543/postgres?sslmode=require`  |
| `SUPABASE_SERVICE_ROLE_KEY` | Service auth    | `eyJhbG...` (JWT)                                     |
| `DRAGONFLY_API_KEY`         | Internal auth   | Random 32+ char string                                |
| `DRAGONFLY_CORS_ORIGINS`    | CORS whitelist  | `https://dragonfly.vercel.app,https://yourdomain.com` |
| `DISCORD_WEBHOOK_URL`       | Alerting        | `https://discord.com/api/webhooks/...`                |

### Optional but Recommended

| Variable               | Purpose                    | Default               |
| ---------------------- | -------------------------- | --------------------- |
| `LOG_LEVEL`            | Logging verbosity          | `INFO`                |
| `WEB_CONCURRENCY`      | Uvicorn workers (API only) | `1`                   |
| `DRAGONFLY_ACTIVE_ENV` | Legacy compat              | Same as `ENVIRONMENT` |

### ❌ Red Flags

- Missing `SUPABASE_SERVICE_ROLE_KEY` → API will fail on DB operations
- Missing `DRAGONFLY_API_KEY` → Internal endpoints unprotected
- Empty `DRAGONFLY_CORS_ORIGINS` → Dashboard cannot connect
- `DISCORD_WEBHOOK_URL` missing → No alerting on failures

---

## 6. Resource Sizing & Scaling

### Click Path

```
[service] → Settings → Scaling
```

### ✅ Recommended Configuration

#### dragonfly-api (Web Service)

| Setting             | Recommended        | Notes                             |
| ------------------- | ------------------ | --------------------------------- |
| **CPU**             | 0.5 vCPU           | Scales with traffic               |
| **Memory**          | 512 MB             | Increase if OOM errors            |
| **Instances**       | 1 (can scale to 2) | Horizontal scaling OK             |
| **Health Check**    | `/health`          | Liveness probe                    |
| **Readiness Check** | `/readyz`          | Only routes traffic when DB ready |

#### dragonfly-worker-ingest

| Setting            | Recommended | Notes                                   |
| ------------------ | ----------- | --------------------------------------- |
| **CPU**            | 0.25 vCPU   | Batch processing, not latency-sensitive |
| **Memory**         | 256 MB      | Increase for large CSV batches          |
| **Instances**      | 1           | Single consumer prevents duplicates     |
| **Restart Policy** | Always      | Auto-recover from crashes               |

#### dragonfly-worker-enforce

| Setting            | Recommended | Notes                                 |
| ------------------ | ----------- | ------------------------------------- |
| **CPU**            | 0.25 vCPU   | AI calls are I/O bound                |
| **Memory**         | 256 MB      | Increase if processing large payloads |
| **Instances**      | 1           | Single consumer for ordering          |
| **Restart Policy** | Always      | Auto-recover from crashes             |

### Scaling Rules (if using Railway Pro)

```yaml
# Example scaling configuration
api:
  min_instances: 1
  max_instances: 3
  scale_up_threshold: 80% CPU for 60s
  scale_down_threshold: 20% CPU for 300s

workers:
  min_instances: 1
  max_instances: 1 # Keep at 1 for queue ordering
```

### ❌ Red Flags

- Workers scaled beyond 1 instance (causes duplicate processing)
- API with no health check configured
- Memory < 256 MB (Python baseline)
- No restart policy on workers

---

## 7. Complete Audit Procedure

### Pre-Flight

```powershell
# 1. Ensure you have Railway CLI installed
railway --version

# 2. Link to your project
railway link

# 3. Switch to production environment
railway environment production
```

### Step-by-Step Audit

#### Step 1: API Service

```
□ Open: dragonfly-api → Settings → Start Command
□ Verify: python -m tools.run_uvicorn
□ Open: dragonfly-api → Variables
□ Verify: NO SUPABASE_MIGRATE_DB_URL
□ Verify: SUPABASE_DB_URL contains :6543/ and sslmode=require
□ Verify: All required variables present (Section 5)
□ Open: dragonfly-api → Settings → Scaling
□ Verify: Health check = /health, Readiness = /readyz
```

#### Step 2: Ingest Worker

```
□ Open: dragonfly-worker-ingest → Settings → Start Command
□ Verify: python -m backend.workers.ingest_processor
□ Open: dragonfly-worker-ingest → Variables
□ Verify: NO SUPABASE_MIGRATE_DB_URL
□ Verify: SUPABASE_DB_URL identical to API service
□ Verify: WORKER_MODE=true (optional but recommended)
□ Verify: Instances = 1 (no horizontal scaling)
```

#### Step 3: Enforcement Worker

```
□ Open: dragonfly-worker-enforce → Settings → Start Command
□ Verify: python -m backend.workers.enforcement_engine
□ Open: dragonfly-worker-enforce → Variables
□ Verify: NO SUPABASE_MIGRATE_DB_URL
□ Verify: SUPABASE_DB_URL identical to API service
□ Verify: WORKER_MODE=true (optional but recommended)
□ Verify: Instances = 1 (no horizontal scaling)
```

#### Step 4: Cross-Service Consistency

```
□ Compare SUPABASE_URL across all 3 services
□ Compare SUPABASE_DB_URL across all 3 services
□ Compare SUPABASE_SERVICE_ROLE_KEY across all 3 services
□ Compare DRAGONFLY_API_KEY across all 3 services
□ Compare ENVIRONMENT across all 3 services
```

#### Step 5: Final Validation

```
□ Deploy latest commit to production
□ Check API health: curl https://your-api.railway.app/health
□ Check API readiness: curl https://your-api.railway.app/readyz
□ Verify logs show no auth_failure classification
□ Verify logs show pool_mode=api for API, pool_mode=worker for workers
```

---

## 8. Perfect State Variable Table

Copy-paste reference for all three services:

### Shared Variables (identical across all services)

| Variable                    | Value                                                                                                             |
| --------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| `ENVIRONMENT`               | `prod`                                                                                                            |
| `SUPABASE_URL`              | `https://{project-ref}.supabase.co`                                                                               |
| `SUPABASE_DB_URL`           | `postgresql://postgres.{project-ref}:{password}@aws-0-{region}.pooler.supabase.com:6543/postgres?sslmode=require` |
| `SUPABASE_SERVICE_ROLE_KEY` | `eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...`                                                                         |
| `DRAGONFLY_API_KEY`         | `{your-32-char-random-key}`                                                                                       |
| `DRAGONFLY_CORS_ORIGINS`    | `https://dragonfly-dashboard.vercel.app`                                                                          |
| `DISCORD_WEBHOOK_URL`       | `https://discord.com/api/webhooks/{id}/{token}`                                                                   |

### API-Only Variables

| Variable          | Value  |
| ----------------- | ------ |
| `WEB_CONCURRENCY` | `2`    |
| `LOG_LEVEL`       | `INFO` |

### Worker-Only Variables

| Variable      | Value  |
| ------------- | ------ |
| `WORKER_MODE` | `true` |

### Railway-Injected (do not set manually)

| Variable                 | Notes                    |
| ------------------------ | ------------------------ |
| `PORT`                   | Auto-assigned by Railway |
| `RAILWAY_ENVIRONMENT`    | Set by Railway           |
| `RAILWAY_GIT_COMMIT_SHA` | Set by Railway           |

---

## 9. Troubleshooting Common Issues

### Issue: API returns 503 on /readyz

**Check:**

1. `SUPABASE_DB_URL` is set and uses port 6543
2. Password in URL is correct (no URL-encoding issues)
3. Supabase project is not paused
4. Check logs for `classification: auth_failure`

### Issue: Workers not processing jobs

**Check:**

1. Worker is running (not crashed)
2. `SUPABASE_DB_URL` matches API service
3. Queue tables exist and have pending jobs
4. Logs show `pool_mode=worker`

### Issue: Logs show "auth_failure"

**Check:**

1. `SUPABASE_DB_URL` password is correct
2. User in URL matches Supabase project
3. No copy-paste issues (trailing spaces, wrong quotes)

### Issue: CORS errors in dashboard

**Check:**

1. `DRAGONFLY_CORS_ORIGINS` includes your dashboard domain
2. Domain uses HTTPS (not HTTP)
3. No trailing slash in origin URL

---

## 10. Audit Sign-Off

| Check                      | Status | Auditor | Date |
| -------------------------- | ------ | ------- | ---- |
| API start command          | □      |         |      |
| No migrate URL in runtime  | □      |         |      |
| DB URL uses pooler (6543)  | □      |         |      |
| DB URL has sslmode=require | □      |         |      |
| Variables consistent       | □      |         |      |
| Required vars present      | □      |         |      |
| Resource sizing OK         | □      |         |      |
| Health checks configured   | □      |         |      |

**Auditor:** ******\_\_\_******  
**Date:** ******\_\_\_******  
**Next Audit Due:** ******\_\_\_******

---

_Generated by Dragonfly Civil Ops Team_
