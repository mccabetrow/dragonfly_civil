# Incident Response: server_login_retry Lockout

> **Severity**: P1 - Critical | **MTTR Target**: < 15 minutes | **Owner**: On-Call Platform Engineer

## Overview

A `server_login_retry` incident occurs when Supabase/PostgreSQL locks out the database user after repeated authentication failures. This is typically caused by:

1. Misconfigured connection string (wrong password, wrong username format)
2. Password rotation without updating all services
3. Direct connection attempts when pooler is required
4. Retry loops amplifying the failure count

---

## Detection

### Log Signatures

```
FATAL: password authentication failed for user "postgres"
FATAL: password authentication failed for user "postgres.ejiddanxtqcleyswqvkc"
server_login_retry: too many failed login attempts
```

### Symptoms

- All services returning 500 errors
- Health checks failing: `/readyz` returns 503
- Railway logs show repeated auth failures
- Supabase dashboard shows connection spike then drop to zero

---

## Immediate Containment (First 2 Minutes)

### Step 1: Stop the Bleeding

**Scale ALL services to 0 replicas immediately** to prevent further lockout amplification.

```bash
# Railway CLI
railway service update dragonfly-api --replicas 0
railway service update dragonfly-worker-ingest --replicas 0
railway service update dragonfly-worker-enforcement --replicas 0
```

Or via Railway Dashboard:

1. Go to each service → Settings → Scaling
2. Set replicas to 0
3. Confirm scale-down

### Step 2: Confirm Lockout Stopped

Wait 30 seconds, then check Supabase connection logs:

- Supabase Dashboard → Database → Logs
- Verify no new `FATAL: password authentication` entries

---

## Diagnosis (Minutes 2-5)

### Step 3: Identify the Culprit

Check which variable is wrong:

```powershell
# From local machine with Railway CLI
railway variables -s dragonfly-api | Select-String "SUPABASE"
```

**Common Issues:**

| Symptom                           | Likely Cause                    | Fix                       |
| --------------------------------- | ------------------------------- | ------------------------- |
| `user "postgres"` (no suffix)     | Wrong username format           | Add `.project-ref` suffix |
| Port 5432 in URL                  | Using direct connection         | Change to pooler (6543)   |
| Different password                | Password rotated/mismatched     | Reset and sync            |
| `SUPABASE_MIGRATE_DB_URL` present | Migration var leaked to runtime | Delete the variable       |

### Step 4: Validate Current Password

Test the password from Supabase Dashboard:

1. Supabase → Project Settings → Database
2. Copy the connection string
3. Compare password hash with Railway variable

---

## Remediation (Minutes 5-12)

### Step 5: Reset Database Password (If Needed)

If password is compromised or unknown:

1. **Supabase Dashboard** → Project Settings → Database
2. Click **Reset Database Password**
3. Copy the new password immediately
4. ⚠️ This invalidates ALL existing connections

### Step 6: Update Railway Variables

Update the shared variable (affects all services):

```bash
# Set the correct pooler URL
railway variables set SUPABASE_DB_URL="postgresql://postgres.PROJECT_REF:NEW_PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres?sslmode=require"
```

**Verify the format:**

- ✅ Username: `postgres.PROJECT_REF`
- ✅ Host: `*.pooler.supabase.com`
- ✅ Port: `6543`
- ✅ sslmode: `require`

### Step 7: Remove Dangerous Variables

```bash
# CRITICAL: Remove migration URL if present
railway variables unset SUPABASE_MIGRATE_DB_URL -s dragonfly-api
railway variables unset SUPABASE_MIGRATE_DB_URL -s dragonfly-worker-ingest
railway variables unset SUPABASE_MIGRATE_DB_URL -s dragonfly-worker-enforcement
```

---

## Staged Restart (Minutes 12-15)

### Step 8: Restart API First

```bash
railway service update dragonfly-api --replicas 1
```

**Wait for health check:**

```bash
curl https://dragonfly-api-production.up.railway.app/health
# Expected: {"status":"healthy","env":"prod"}
```

### Step 9: Verify Database Connectivity

```bash
curl https://dragonfly-api-production.up.railway.app/readyz
# Expected: {"status":"ready","database":"connected"}
```

### Step 10: Restart Workers (One at a Time)

```bash
# Wait 30 seconds between each
railway service update dragonfly-worker-ingest --replicas 1
# Verify logs show successful connection

railway service update dragonfly-worker-enforcement --replicas 1
# Verify logs show successful connection
```

---

## Verification

### Expected Healthy Logs

```
[BOOT] Mode: PROD | Config Source: SYSTEM_ENV | SHA: abc123
[CONFIG_GUARD] ✅ DB URL validated: pooler=true, port=6543, ssl=require
INFO: Application startup complete.
INFO: Uvicorn running on http://0.0.0.0:8000
```

### Health Check Commands

```bash
# API health
curl -s https://dragonfly-api-production.up.railway.app/health | jq

# Database readiness
curl -s https://dragonfly-api-production.up.railway.app/readyz | jq

# Full certification
python -m tools.certify_deployment --url https://dragonfly-api-production.up.railway.app --env prod
```

---

## Post-Incident

### Step 11: Document the Incident

Create incident report with:

- Timestamp of first failure
- Timestamp of containment (scale to 0)
- Root cause (which variable was wrong)
- Time to recovery
- Logs showing resolution

### Step 12: Prevent Recurrence

- [ ] Verify no per-service overrides of `SUPABASE_DB_URL`
- [ ] Confirm `SUPABASE_MIGRATE_DB_URL` is not in any Railway service
- [ ] Add Railway variable lock if available
- [ ] Review who has access to modify variables

---

## Emergency Contacts

| Role             | Contact             | When to Escalate             |
| ---------------- | ------------------- | ---------------------------- |
| On-Call Platform | PagerDuty           | All P1 incidents             |
| Supabase Support | support@supabase.io | If lockout persists > 30 min |
| Database Admin   | @dbadmin in Slack   | Password reset questions     |

---

## Quick Reference

```
┌─────────────────────────────────────────────────────────────────┐
│  server_login_retry INCIDENT RESPONSE                           │
├─────────────────────────────────────────────────────────────────┤
│  1. CONTAIN: Scale all services to 0 replicas                   │
│  2. DIAGNOSE: Check Railway variables for wrong values          │
│  3. FIX: Reset password in Supabase if needed                   │
│  4. UPDATE: Set correct SUPABASE_DB_URL in Railway              │
│  5. REMOVE: Delete SUPABASE_MIGRATE_DB_URL from all services    │
│  6. RESTART: API first, then workers one-by-one                 │
│  7. VERIFY: /health, /readyz, certify_deployment                │
└─────────────────────────────────────────────────────────────────┘
```
