# Runbook: Supabase Pooler Lockout Recovery

**Severity:** P1 – Platform-wide database access failure  
**Trigger:** `server_login_retry` errors in logs, `/readyz` returning 503

---

## 1. Symptoms

| Signal                                           | Where to Look                                    |
| ------------------------------------------------ | ------------------------------------------------ |
| `FATAL: server_login_retry` in logs              | Railway logs, `docker logs`                      |
| `password authentication failed for user`        | Supabase Pooler logs (Dashboard → Logs → Pooler) |
| `/readyz` returns `503` with `"db": "unhealthy"` | `curl https://<api>/readyz`                      |
| Connection count spike then plateau at 0         | Supabase Dashboard → Database → Connections      |
| All workers stuck in retry loops                 | Railway service metrics (CPU high, no DB ops)    |

**Log pattern to grep:**

```
FATAL.*server_login_retry|password authentication failed|too many connections
```

---

## 2. Immediate Containment (< 2 min)

```powershell
# 1. Stop the bleeding - scale ALL services to 0
railway service update dragonfly-api --replicas 0
railway service update dragonfly-worker-ingest --replicas 0
railway service update dragonfly-worker-enforcement --replicas 0

# 2. Verify services stopped
railway status
```

**Checklist:**

- [ ] All replicas at 0
- [ ] No new `server_login_retry` logs appearing
- [ ] Supabase connection count dropping to baseline

---

## 3. Root Cause Matrix

| Cause                           | Evidence                              | Fix                                                                 |
| ------------------------------- | ------------------------------------- | ------------------------------------------------------------------- |
| **Wrong pooler username**       | `user "postgres.xxxx" does not exist` | Use `postgres.{project-ref}` format, NOT `postgres`                 |
| **Wrong password**              | `password authentication failed`      | Regenerate in Dashboard → Settings → Database → Database password   |
| **Wrong host/port**             | `connection refused` or timeout       | Use `aws-0-us-west-1.pooler.supabase.com:6543` (pooler), not direct |
| **Transaction vs Session mode** | Works locally, fails in prod          | Ensure DSN uses port `6543` (transaction mode)                      |
| **Connection storm**            | `too many connections` before lockout | Check replica count, pool size settings                             |
| **IP restrictions**             | `no pg_hba.conf entry`                | Verify Railway IPs allowed in Supabase Network settings             |

---

## 4. Verification Steps

### 4.1 Test DSN Safely (from local machine)

```powershell
# Load credentials
. ./scripts/load_env.ps1

# Test with psql (single connection, immediate exit)
$env:PGPASSWORD = $env:SUPABASE_DB_PASSWORD
psql -h $env:SUPABASE_DB_HOST -p 6543 -U "postgres.$env:SUPABASE_PROJECT_REF" -d postgres -c "SELECT 1"
```

**Expected:** `1` returned, no errors.

### 4.2 Supabase Dashboard Checks

- [ ] **Database → Connections:** Shows available slots (not maxed)
- [ ] **Logs → Pooler:** No ongoing auth failures
- [ ] **Settings → Database:** Password matches `SUPABASE_DB_PASSWORD`
- [ ] **Settings → API:** Project ref matches DSN username suffix

### 4.3 Validate DSN Format

```
postgresql://postgres.{PROJECT_REF}:{PASSWORD}@aws-0-{REGION}.pooler.supabase.com:6543/postgres?sslmode=require
```

**Common mistakes:**

- Using `postgres` instead of `postgres.{ref}`
- Using port `5432` (direct) instead of `6543` (pooler)
- Missing `sslmode=require`

---

## 5. Staged Recovery Plan

### Stage 1: API (validates auth works)

```powershell
# Scale API to 1 replica only
railway service update dragonfly-api --replicas 1

# Watch logs for 60 seconds
railway logs -f --service dragonfly-api
```

**Gate criteria:**

- [ ] `🔌 Database Pool Opened` in logs
- [ ] `/readyz` returns `200` with `"db": "healthy"`
- [ ] No `server_login_retry` errors

### Stage 2: Ingest Worker

```powershell
railway service update dragonfly-worker-ingest --replicas 1
# Monitor 2 minutes
```

**Gate criteria:**

- [ ] Worker connects without auth errors
- [ ] At least one job processed successfully

### Stage 3: Enforcement Worker

```powershell
railway service update dragonfly-worker-enforcement --replicas 1
# Monitor 2 minutes, then scale API to normal
railway service update dragonfly-api --replicas 2
```

**Gate criteria:**

- [ ] All services stable for 5 minutes
- [ ] Supabase connection count stable (not climbing)

---

## 6. Prevention Checklist

### Code-Level Guards

- [ ] **Auth-failure fast exit:** First `password authentication failed` → log + exit (no retry)
- [ ] **Exponential backoff:** Base 2s, max 60s, with ±25% jitter
- [ ] **Max retry cap:** 6 attempts total, then graceful degradation
- [ ] **Pool size limits:** API: `min=2, max=10` / Workers: `min=1, max=2`

### Operational Guards

- [ ] **Single replica rule:** Workers run 1 replica max (no connection storms)
- [ ] **Credential rotation SOP:** Update Railway secrets → rolling restart
- [ ] **Monitoring alert:** PagerDuty on `server_login_retry` pattern
- [ ] **Preflight gate:** `python -m tools.doctor --env prod` before deploy

### Railway Configuration

```yaml
# Recommended service settings
dragonfly-worker-ingest:
  replicas: 1
  healthcheck:
    path: /readyz
    interval: 30s
    timeout: 10s
```

---

## 7. Post-Incident

- [ ] Document root cause in `#incidents` Slack channel
- [ ] Update `SUPABASE_DB_PASSWORD` rotation date in secrets inventory
- [ ] Review connection pool metrics for sizing adjustments
- [ ] Run `python -m tools.doctor_all --env prod` to verify full health

---

**Last updated:** 2026-01-10  
**Owner:** Platform Team
