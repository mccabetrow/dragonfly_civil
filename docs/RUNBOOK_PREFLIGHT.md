# Dragonfly Civil – Preflight Configuration

**Environment configuration for worker preflight validation**

_Version 1.0 | January 2026_

---

## Overview

The preflight system validates worker configuration at startup. It implements
the **Strict Preflight Contract**:

- **Errors are FATAL** – Missing required config exits with code 1
- **Warnings are NEVER fatal** – Deprecation notices do not crash workers
- This prevents workers from crash-looping on configuration warnings

---

## Environment Variables

### Required Variables

| Variable                    | Description                         | Example                                     |
| --------------------------- | ----------------------------------- | ------------------------------------------- |
| `DATABASE_URL`              | Canonical PostgreSQL connection URL | `postgresql://user:pass@host:6543/postgres` |
| `SUPABASE_URL`              | Supabase project REST API URL       | `https://project.supabase.co`               |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role JWT token              | `eyJhbGciOiJIUzI1NiIs...`                   |

### Preflight Toggles

| Variable                   | Default                  | Description                              |
| -------------------------- | ------------------------ | ---------------------------------------- |
| `PREFLIGHT_FAIL_FAST`      | `true`                   | Exit immediately on errors               |
| `PREFLIGHT_WARNINGS_FATAL` | `false`                  | Treat warnings as errors (rarely needed) |
| `PREFLIGHT_STRICT_MODE`    | prod=`true`, dev=`false` | Stricter validation in prod              |

### Deprecated Variables

| Variable          | Replacement    | Notes                                  |
| ----------------- | -------------- | -------------------------------------- |
| `SUPABASE_DB_URL` | `DATABASE_URL` | Still works, emits deprecation warning |

---

## Railway Configuration

### Setting Environment Variables in Railway

1. Open your Railway project dashboard
2. Navigate to **Settings → Variables**
3. Add the following variables:

```env
# Required
DATABASE_URL=postgresql://postgres.<ref>:<password>@aws-0-us-east-1.pooler.supabase.com:6543/postgres
SUPABASE_URL=https://<project-ref>.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...

# Environment
ENVIRONMENT=prod
SUPABASE_MODE=prod

# Preflight (defaults are correct for production)
# PREFLIGHT_FAIL_FAST=true       # (default)
# PREFLIGHT_WARNINGS_FATAL=false # (default - CRITICAL for stable deploys)
# PREFLIGHT_STRICT_MODE=true     # (default in prod)
```

### Critical: Do NOT Set PREFLIGHT_WARNINGS_FATAL=true

The default `PREFLIGHT_WARNINGS_FATAL=false` ensures workers do not crash-loop
on configuration warnings (e.g., deprecation notices). Only set this to `true`
in CI/CD pipelines where you want strict validation.

---

## Migrating from SUPABASE_DB_URL to DATABASE_URL

If you're currently using `SUPABASE_DB_URL`, migrate as follows:

1. **Add DATABASE_URL** with the same connection string
2. **Deploy** – workers will use `DATABASE_URL` and suppress the deprecation warning
3. **Remove SUPABASE_DB_URL** after confirming all workers are healthy

When both are set, `DATABASE_URL` takes precedence and no deprecation warning is emitted.

---

## Troubleshooting

### Worker Crash-Loop on Startup

**Symptom:** Worker repeatedly exits with code 1 in production.

**Check:**

```powershell
# View preflight output
railway logs --service <worker-name> | Select-String "preflight|CRITICAL|ERROR"
```

**Common Causes:**

1. Missing `DATABASE_URL` – Add the connection string
2. Invalid `SUPABASE_SERVICE_ROLE_KEY` – Verify it starts with `ey` and is >100 chars
3. `PREFLIGHT_WARNINGS_FATAL=true` – Remove this variable or set to `false`

### Deprecation Warning in Logs

**Symptom:** Logs show "SUPABASE_DB_URL is deprecated"

**Fix:** Add `DATABASE_URL` with the same value. The warning will be suppressed.

### Preflight Validation in CI/CD

For strict validation in CI pipelines, use:

```powershell
$env:PREFLIGHT_WARNINGS_FATAL = "true"
python -m backend.preflight --service api
```

This exits non-zero on any warning, useful for catching config issues before deploy.

---

## CLI Usage

```powershell
# Validate configuration
python -m backend.preflight --service enforcement_engine

# Print effective config (shows which env vars are set)
python -m backend.preflight --service api --print-effective-config

# Single-line output for log aggregators
python -m backend.preflight --service ingest_processor --single-line
```

---

## Acceptance Criteria

After configuration, verify:

```powershell
# 1. Preflight passes without errors
python -m backend.preflight --service test_worker

# 2. Worker starts successfully
python -m backend.workers.enforcement_engine

# 3. Exit code is 0 (warnings do not cause exit)
echo $LASTEXITCODE  # Should be 0
```
