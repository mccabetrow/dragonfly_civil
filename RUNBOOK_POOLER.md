# Dragonfly Supabase Pooler Runbook

**Author**: Principal Database Reliability Engineer  
**Date**: 2026-01-18  
**Status**: Production (Direct Connection Waiver Active)

---

## ⚠️ CURRENT STATUS: DIRECT CONNECTION WAIVER

**Effective**: 2026-01-18  
**Expires**: 2026-02-15  
**Reason**: Supabase Shared Pooler returns `FATAL: Tenant or user not found`

### What This Means

- Production is using **port 5432 (direct)** instead of **port 6543 (pooler)**
- The waiver is enforced in `backend/core/dsn_guard.py`
- `prod_gate.py` tracks waiver expiry with warnings

### Required Environment Variable

```bash
# Railway must have this set:
DB_CONNECTION_MODE=direct_waiver
```

### Before Waiver Expires

1. **Investigate root cause** - See "Pooler Troubleshooting" section below
2. **Fix pooler** OR **extend waiver** in `backend/core/dsn_guard.py`:
   ```python
   DIRECT_WAIVER_EXPIRY = datetime(2026, 3, 15, ...)  # New date
   ```
3. **Document reason** for extension in this file

---

## Overview

This runbook documents Supabase connection pooler strategy for Dragonfly to prevent
`server_login_retry` lockout spirals and ensure production stability.

**Canonical Project References**:

- **Production**: `iaketsyhmqbwaabgykux`
- **Development**: `ejiddanxtqcleyswqvkc`

---

## 🔍 Pooler Troubleshooting: "Tenant or user not found"

This error means the Shared Pooler cannot route your connection.

### Step 1: Verify Correct DSN Format

```
[scheme]://[user].[PROJECT_REF]:[PASSWORD]@aws-0-[REGION].pooler.supabase.com:6543/[database]
```

**Required elements**:

- Username: `postgres.iaketsyhmqbwaabgykux` (NOT just `postgres`)
- Host: `aws-0-REGION.pooler.supabase.com` (NOT `db.xxx.supabase.co`)
- Port: `6543`

### Step 2: Find Your Region

1. Go to Supabase Dashboard → Settings → General
2. Look for "Region" - e.g., `us-east-1`, `us-west-2`, `eu-west-1`
3. Use that region in the pooler hostname

### Step 3: Verify Connection Pooling is Enabled

1. Supabase Dashboard → Settings → Database
2. Scroll to "Connection Pooling"
3. Ensure it's **enabled**

### Step 4: Get Exact Connection String

1. Supabase Dashboard → Settings → Database
2. Find "Connection String" section
3. Select **"Transaction"** mode (dropdown)
4. Copy the exact string provided

### Step 5: Test with verify_pooler

```bash
$env:DATABASE_URL = "YOUR_POOLER_DSN_HERE"
python -m tools.verify_pooler
```

### Step 6: If Pooler Still Fails

If pooler continues to fail after all checks:

1. Contact Supabase Support with project ref and error
2. Extend waiver as needed (see above)
3. Use direct connection (5432) with waiver

---

## 🔥 EMERGENCY: How to Stop a Lockout Spiral

If you see `server_login_retry` errors in logs:

### Step 1: STOP ALL SERVICES IMMEDIATELY

```bash
# Railway
railway service stop <service-name>

# Or via dashboard: Settings → Deployments → Stop
```

**DO NOT RESTART** - every restart attempt amplifies the lockout.

### Step 2: Wait 15-20 Minutes

The Supabase pooler lockout window is **15-20 minutes**. There is no way to shorten this.

### Step 3: Fix Credentials (While Waiting)

```bash
# 1. Verify the password in Supabase Dashboard → Settings → Database
# 2. Ensure password is URL-encoded if it contains special characters
# 3. Update DATABASE_URL in Railway
```

### Step 4: Probe Before Restarting

```bash
python -m tools.probe_db --env prod
```

Only restart services if probe returns `RESULT: PASS`.

### Step 5: Restart Services

```bash
railway up  # or trigger redeploy
```

---

## 🔐 How to Generate a DSN Safely

### Password URL Encoding

If your password contains special characters (`@`, `+`, `/`, `!`, etc.), it **MUST** be URL-encoded:

```python
from urllib.parse import quote

password = "MyP@ss+word!/123"
encoded = quote(password, safe='')
print(f"Encoded: {encoded}")
# Output: MyP%40ss%2Bword%21%2F123
```

### DSN Template Generator

```python
from urllib.parse import quote

# Fill in your values
user = "postgres"
password = "YOUR_PASSWORD_HERE"  # Will be encoded
project_ref = "iaketsyhmqbwaabgykux"
region = "us-east-1"

# Encode password
encoded_password = quote(password, safe='')

# Generate DSN
dsn = f"postgresql://{user}.{project_ref}:{encoded_password}@aws-0-{region}.pooler.supabase.com:6543/postgres?sslmode=require"

print(dsn)
```

### Safe Characters (No Encoding Needed)

RFC 3986 "unreserved" characters don't need encoding:

- `A-Z`, `a-z`, `0-9`
- `-`, `.`, `_`, `~`

If your password uses ONLY these characters, no encoding is needed.

### Common Special Characters

| Character   | URL Encoded |
| ----------- | ----------- |
| `@`         | `%40`       |
| `+`         | `%2B`       |
| `/`         | `%2F`       |
| `!`         | `%21`       |
| `#`         | `%23`       |
| `$`         | `%24`       |
| `%`         | `%25`       |
| `&`         | `%26`       |
| `=`         | `%3D`       |
| `?`         | `%3F`       |
| ` ` (space) | `%20`       |

---

## 1. Pooler Modes

### 1.1 Shared Pooler (RECOMMENDED for Supabase Free/Pro)

| Property     | Value                                |
| ------------ | ------------------------------------ |
| Host pattern | `aws-0-<region>.pooler.supabase.com` |
| Port         | `6543`                               |
| Mode         | Transaction pooling (PgBouncer)      |
| SSL          | Required (`?sslmode=require`)        |

**Username format**: `<db_user>.<project_ref>`

```
postgresql://postgres.iaketsyhmqbwaabgykux:PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
```

**Identity rules**:

- The project reference MUST be appended to the username with a dot separator
- Example: `postgres.iaketsyhmqbwaabgykux` (NOT just `postgres`)
- Custom roles (e.g., `dragonfly_app`) become `dragonfly_app.iaketsyhmqbwaabgykux`

### 1.2 Dedicated Pooler (Supabase Enterprise / BYOP)

| Property     | Value                          |
| ------------ | ------------------------------ |
| Host pattern | `db.<project_ref>.supabase.co` |
| Port         | `6543`                         |
| Mode         | Transaction or session pooling |
| SSL          | Required                       |

**Username format**: `<db_user>` (plain, no suffix)

```
postgresql://postgres:PASSWORD@db.iaketsyhmqbwaabgykux.supabase.co:6543/postgres?sslmode=require
```

### 1.3 Direct Connection (FORBIDDEN in Production)

| Property     | Value                          |
| ------------ | ------------------------------ |
| Host pattern | `db.<project_ref>.supabase.co` |
| Port         | `5432`                         |
| Mode         | Direct PostgreSQL (no pooling) |

**⚠️ NEVER use port 5432 in production** - bypasses the pooler and can exhaust connections.

---

## 2. Username Format Rules

| Pooler Mode | Username Format    | Example                         |
| ----------- | ------------------ | ------------------------------- |
| Shared      | `user.project_ref` | `postgres.iaketsyhmqbwaabgykux` |
| Dedicated   | `user`             | `postgres`                      |
| Direct      | `user`             | `postgres` (FORBIDDEN)          |

### 2.1 Using Custom Roles with Shared Pooler

If you create a custom role like `dragonfly_app`:

```sql
CREATE ROLE dragonfly_app WITH LOGIN NOINHERIT;
ALTER ROLE dragonfly_app WITH PASSWORD 'strong-password';
```

The connection string becomes:

```
postgresql://dragonfly_app.iaketsyhmqbwaabgykux:PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
```

**Important**: The pooler authenticates the `dragonfly_app` role against the project, so:

1. The role MUST exist in the database
2. The password MUST match
3. The project reference MUST be correct

---

## 3. Password Rotation Without Lockouts

### 3.1 Pre-Rotation Checklist

```bash
# Verify current connection works
python -m tools.probe_db --env prod

# Check for active connections (run as superuser)
SELECT usename, application_name, state, query_start
FROM pg_stat_activity
WHERE usename = 'postgres' OR usename = 'dragonfly_app';
```

### 3.2 Rotation Procedure (Zero-Downtime)

**Step 1**: Create temporary second credential (if using custom role)

```sql
-- This only works for custom roles, not the built-in postgres user
ALTER ROLE dragonfly_app WITH PASSWORD 'new-strong-password';
```

**Step 2**: Update Railway environment variable

```bash
# In Railway dashboard or CLI
railway variables set DATABASE_URL="postgresql://postgres.iaketsyhmqbwaabgykux:NEW_PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
```

**Step 3**: Trigger rolling restart

```bash
railway up  # or trigger redeploy
```

**Step 4**: Validate new credential

```bash
python -m tools.probe_db --env prod
```

### 3.3 Emergency: Lockout Recovery

If you triggered a `server_login_retry` lockout:

1. **STOP all retry attempts immediately** - don't restart workers
2. **Wait 15-20 minutes** for the pooler lockout window to clear
3. **Fix the credential** in Railway while waiting
4. **Probe first** before restarting:
   ```bash
   python -m tools.probe_db --env prod
   ```
5. **Then restart** the service

The circuit breaker (exit code 78) prevents workers from amplifying the lockout.

---

## 4. Validation with tools.probe_db

### 4.1 Basic Probe

```bash
# Probe production (uses DATABASE_URL from .env.prod or SUPABASE_MODE=prod)
python -m tools.probe_db --env prod

# Probe development
python -m tools.probe_db --env dev
```

### 4.2 Explicit DSN Probe

```bash
# Direct DSN (will prompt for password if not in string)
python -m tools.probe_db "postgresql://postgres.iaketsyhmqbwaabgykux@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require"
```

### 4.3 Expected Output (PASS)

```
╔══════════════════════════════════════════════════════════════════════════════╗
║  PROBE DATABASE                                                               ║
╚══════════════════════════════════════════════════════════════════════════════╝

DSN: postgresql://postgres.iaketsyh****@aws-0-us-east-1.pooler.supabase.com:6543/postgres

┌─────────────────────────────────────────────────────────────────────────────┐
│  POOLER IDENTITY                                                             │
├─────────────────────────────────────────────────────────────────────────────┤
│  Mode:        shared                                                         │
│  Host:        aws-0-us-east-1.pooler.supabase.com                           │
│  Port:        6543                                                           │
│  User:        postgres.iaketsyhmqbwaabgykux                                  │
│  Project Ref: iaketsyhmqbwaabgykux                                          │
│  Region:      aws-0-us-east-1                                               │
└─────────────────────────────────────────────────────────────────────────────┘

✅ IDENTITY: VALID
✅ CONNECTION: SUCCESS (latency: 45ms)
✅ QUERY: SELECT 1 returned 1

══════════════════════════════════════════════════════════════════════════════
  RESULT: PASS
══════════════════════════════════════════════════════════════════════════════
```

### 4.4 Expected Output (FAIL - Lockout)

```
❌ CONNECTION: FAILED
   Error: server_login_retry exceeded

══════════════════════════════════════════════════════════════════════════════
  RESULT: FAIL (LOCKOUT DETECTED)

  ACTION: Wait 15+ minutes before retrying. Do NOT restart services.
══════════════════════════════════════════════════════════════════════════════
```

---

## 5. Operator Log Lines

At startup, the API and workers log a **single structured line** with all pooler metadata:

```
[DB] pooler_mode=shared host=aws-0-us-east-1.pooler.supabase.com port=6543 user=postgres.*** project_ref=iaketsyhmqbwaabgykux sslmode=require password_encoding=safe_plain
```

### Log Field Reference

| Field               | Description                | Example Values                             |
| ------------------- | -------------------------- | ------------------------------------------ |
| `pooler_mode`       | Connection mode            | `shared`, `dedicated`, `direct`, `unknown` |
| `host`              | Database host              | `aws-0-us-east-1.pooler.supabase.com`      |
| `port`              | Database port              | `6543` (pooler), `5432` (FORBIDDEN)        |
| `user`              | Redacted username          | `postgres.***`                             |
| `project_ref`       | Supabase project reference | `iaketsyhmqbwaabgykux`                     |
| `sslmode`           | SSL configuration          | `require` (mandatory)                      |
| `password_encoding` | Password encoding status   | See below                                  |

### Password Encoding Status

| Status           | Meaning                                              | Action Required     |
| ---------------- | ---------------------------------------------------- | ------------------- |
| `safe_plain`     | Password uses only unreserved chars (A-Za-z0-9-.\_~) | None                |
| `encoded`        | Password contains %XX sequences (URL-encoded)        | None                |
| `needs_encoding` | Password has special chars WITHOUT encoding          | **FIX IMMEDIATELY** |
| `missing`        | No password in DSN                                   | Check configuration |

**If you see `password_encoding=needs_encoding`**, the password contains special characters
that are NOT URL-encoded. This can cause silent authentication failures. Fix using:

```python
from urllib.parse import quote
encoded = quote("YOUR_PASSWORD", safe='')
```

### Lockout Log

On lockout detection:

```
[DB] READY=false reason=lockout next_retry_in=900s
[DB Supervisor] Lockout backoff: 900s (15m) remaining. No connection attempts until backoff expires.
```

---

## 6. Circuit Breaker Behavior

| Component | On Lockout Error                                           | Exit Code |
| --------- | ---------------------------------------------------------- | --------- |
| API       | Degraded mode, /health=200, /readyz=503, 15-20 min backoff | N/A       |
| Worker    | Immediate exit                                             | 78        |

### Supervisor Backoff Guarantee

When the API enters degraded mode due to lockout:

1. **DBSupervisor** schedules next retry 15-20 minutes in the future
2. **Zero connection attempts** are made during the backoff window
3. Supervisor logs remaining time every 60 seconds
4. Only after backoff expires does supervisor attempt reconnection

This prevents the API from amplifying lockouts while staying alive to serve /health.

**Lockout triggers**:

- `server_login_retry` - Supabase pooler rejecting due to repeated bad auth
- `query_wait_timeout` - Connection pool exhaustion

---

## 7. Migration: dragonfly_app Role

The migration `20260114120000_create_app_user.sql` creates a `dragonfly_app` role with least-privilege access.

**Compatibility**:

- ✅ Shared pooler: Use `dragonfly_app.iaketsyhmqbwaabgykux` as username
- ✅ Dedicated pooler: Use `dragonfly_app` as username
- ❌ Direct connection: FORBIDDEN in production

**Post-migration**:

1. Set the password (not in git):
   ```sql
   ALTER ROLE dragonfly_app WITH PASSWORD 'your-strong-password';
   ```
2. Update `DATABASE_URL` in Railway:
   ```
   postgresql://dragonfly_app.iaketsyhmqbwaabgykux:PASSWORD@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
   ```
3. Validate:
   ```bash
   python -m tools.probe_db --env prod
   ```

---

## 8. Quick Reference

### DSN Template (Shared Pooler)

```
postgresql://{user}.{project_ref}:{password}@aws-0-{region}.pooler.supabase.com:6543/postgres?sslmode=require
```

### Environment Variables

| Variable        | Required | Description                       |
| --------------- | -------- | --------------------------------- |
| `DATABASE_URL`  | Yes      | Full DSN with pooler endpoint     |
| `SUPABASE_MODE` | No       | `dev` or `prod` for env selection |

### Ports

| Port | Purpose            | Production   |
| ---- | ------------------ | ------------ |
| 6543 | Pooler (PgBouncer) | ✅ Required  |
| 5432 | Direct PostgreSQL  | ❌ Forbidden |

### Exit Codes

| Code | Meaning                  |
| ---- | ------------------------ |
| 0    | Success                  |
| 1    | General failure          |
| 78   | Auth lockout (EX_CONFIG) |

---

## Appendix: Troubleshooting

### "server_login_retry" Error

**Cause**: Repeated failed authentication attempts triggered pooler lockout.

**Fix**:

1. Stop all services immediately
2. Wait 15-20 minutes
3. Fix credentials while waiting
4. Probe before restarting: `python -m tools.probe_db --env prod`

### "password authentication failed"

**Cause**: Wrong password or role doesn't exist.

**Fix**:

1. Verify role exists: `SELECT * FROM pg_roles WHERE rolname = 'your_role';`
2. Reset password: `ALTER ROLE your_role WITH PASSWORD 'new_password';`
3. Update `DATABASE_URL` in Railway
4. Probe before deploying

### Username Missing Project Ref

**Error**: `SHARED_POOLER_USER_MISSING_REF`

**Fix**: Add project ref to username:

- Wrong: `postgres@aws-0-...`
- Correct: `postgres.iaketsyhmqbwaabgykux@aws-0-...`
