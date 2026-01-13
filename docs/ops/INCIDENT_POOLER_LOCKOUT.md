# Incident Runbook: Supabase Pooler Lockout / server_login_retry

**Severity:** P1 (Production Down)  
**Last Updated:** 2026-01-10  
**Owner:** Platform Engineering

---

## Symptoms

| Indicator                                  | Where to See It                                |
| ------------------------------------------ | ---------------------------------------------- |
| Logs show `server_login_retry`             | Railway logs for any service                   |
| Logs show `password authentication failed` | Railway logs                                   |
| Logs show `too many connection attempts`   | Railway logs                                   |
| `/readyz` returns 503                      | API health endpoint                            |
| DB pool never initializes                  | Startup logs show repeated retry attempts      |
| Services crash-loop                        | Railway dashboard shows restart count climbing |

**Key log pattern to grep:**

```
server_login_retry
password authentication failed
no pg_hba.conf entry
FATAL.*authentication
```

---

## Likely Causes

| Cause                                      | Probability | How to Confirm                                       |
| ------------------------------------------ | ----------- | ---------------------------------------------------- |
| Wrong password in `SUPABASE_DB_URL`        | HIGH        | Compare Railway var to Supabase dashboard            |
| Wrong username (not pooler format)         | HIGH        | Username should be `postgres.PROJECT_REF` for pooler |
| Wrong host (direct vs pooler)              | MEDIUM      | Host should be `aws-0-us-east-1.pooler.supabase.com` |
| Wrong port (5432 vs 6543)                  | MEDIUM      | Port must be **6543** for transaction pooler         |
| Supabase rotated credentials               | LOW         | Check Supabase dashboard for recent password changes |
| Too many failed attempts triggered lockout | MEDIUM      | Supabase temporarily blocks after ~10 rapid failures |

---

## Immediate Containment (< 5 minutes)

### Step 1: Stop the Bleeding

**Scale all services to 0 replicas immediately.**

In Railway:

1. Go to each service (API, worker-ingest, worker-enforcement)
2. Click **Settings** → **Scaling** → set replicas to **0**
3. Or: Click **Pause Service** if available

**Why:** Every failed connection attempt extends the lockout timer. Stop all connection attempts NOW.

### Step 2: Wait 60 Seconds

Supabase `server_login_retry` has a backoff window. Give it time to clear.

### Step 3: Verify Credentials (Do NOT restart yet)

Open Supabase Dashboard:

1. Project → **Settings** → **Database**
2. Click **Connection Pooling** section
3. Copy the **Transaction** connection string
4. Compare EVERY field to your Railway `SUPABASE_DB_URL`:

| Field    | Expected Format                                        |
| -------- | ------------------------------------------------------ |
| Host     | `aws-0-us-east-1.pooler.supabase.com` (or your region) |
| Port     | `6543`                                                 |
| User     | `postgres.YOUR_PROJECT_REF`                            |
| Password | The database password (not API key)                    |
| Database | `postgres`                                             |
| SSL      | `?sslmode=require`                                     |

---

## Verification Queries

Run these from a **local machine** (not Railway) to test credentials before restarting:

```powershell
# Test connection with psql (if installed)
$env:PGPASSWORD = "your-password"
psql -h aws-0-us-east-1.pooler.supabase.com -p 6543 -U postgres.YOUR_PROJECT_REF -d postgres -c "SELECT 1;"
```

Or with Python:

```python
import psycopg
conn = psycopg.connect("postgresql://postgres.PROJECT_REF:PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require")
print(conn.execute("SELECT 1").fetchone())
conn.close()
```

**Expected:** Returns `(1,)` with no errors.

**If this fails locally:** The credentials are wrong. Do NOT restart Railway services.

---

## Root Cause Matrix

| Symptom                                  | Root Cause                                     | Fix                                               |
| ---------------------------------------- | ---------------------------------------------- | ------------------------------------------------- |
| `password authentication failed`         | Wrong password                                 | Copy fresh password from Supabase dashboard       |
| `role "postgres" does not exist`         | Using direct username instead of pooler format | Change to `postgres.PROJECT_REF`                  |
| `could not translate host name`          | Wrong host                                     | Use pooler host, not `db.PROJECT_REF.supabase.co` |
| `connection refused` on 5432             | Using direct port                              | Change to port `6543`                             |
| `server_login_retry` after correct creds | Lockout still active                           | Wait 2-5 minutes, then retry once                 |
| `too many connections`                   | Pool exhaustion (not auth)                     | Different issue—see connection pool runbook       |

---

## Recovery Procedure

### Phase 1: Fix Credentials

1. In Railway → Service → **Variables**
2. Update `SUPABASE_DB_URL` with verified connection string
3. **Do NOT redeploy yet**

### Phase 2: Test with Single Instance

1. Scale **dragonfly-api** to 1 replica only
2. Watch logs for 30 seconds
3. Check `/readyz` endpoint

| Result            | Next Step                                           |
| ----------------- | --------------------------------------------------- |
| `{"status":"ok"}` | Proceed to Phase 3                                  |
| Still failing     | Return to Verification Queries, recheck credentials |

### Phase 3: Staged Rollout

1. If API is healthy, scale **worker-ingest** to 1
2. Wait 30 seconds, check logs
3. Scale **worker-enforcement** to 1
4. Wait 30 seconds, verify all healthy

### Phase 4: Return to Normal

1. Scale API to normal replica count (if using scaling)
2. Confirm `/readyz` returns OK
3. Run `.\scripts\dad_go.ps1` locally to verify full system health

---

## Prevention Measures

### 1. Auth-Failure Fast Exit (Already Implemented)

Our `backend/db.py` now limits auth-related retries to **3 attempts max** with 15-30s backoff.

This prevents:

- Rapid-fire failed connections
- Triggering Supabase lockout
- Wasting the entire 60s retry budget on bad creds

### 2. Config Guard (Already Implemented)

`validate_db_config()` runs before any DB connection:

- FATAL if port is 5432 in production (must be 6543)
- FATAL if `SUPABASE_MIGRATE_DB_URL` is present in runtime
- WARN if sslmode is missing

### 3. Credential Rotation SOP

When rotating Supabase password:

1. Update Railway variables for ALL services FIRST (don't redeploy)
2. Redeploy services one at a time with 30s gaps
3. Never rotate password during business hours

### 4. Local Verification Before Deploy

Always run before any credential change:

```powershell
.\scripts\dad_go.ps1
```

### 5. Monitoring Alert

Set up Railway notification for log pattern:

```
server_login_retry OR "password authentication failed"
```

Alert destination: Slack #dragonfly-alerts

---

## Post-Incident Checklist

- [ ] All services running and healthy
- [ ] `/readyz` returns OK
- [ ] `dad_go.ps1` passes all checks
- [ ] No `server_login_retry` in last 5 minutes of logs
- [ ] Incident logged in #incidents channel
- [ ] Root cause documented
- [ ] Prevention measure identified (if new failure mode)

---

## Escalation Path

| Time Since Detection | Action                                                     |
| -------------------- | ---------------------------------------------------------- |
| 0-5 min              | Follow this runbook                                        |
| 5-15 min             | If still failing, check Supabase status page               |
| 15+ min              | Contact Supabase support if their infrastructure suspected |
| Any time             | If unsure, call Ryan                                       |

---

## Quick Commands Reference

```powershell
# Test credentials locally
.\scripts\dad_go.ps1

# Check API health
curl https://YOUR-APP.up.railway.app/readyz

# View recent logs (Railway CLI)
railway logs --service dragonfly-api | Select-String "server_login_retry"
```

---

_This incident will resolve faster if you STOP all services first. Every failed attempt makes it worse._
