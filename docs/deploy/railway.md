# Railway Deployment Guide

This document describes deterministic Railway deployments for Dragonfly Civil services.

## Services Overview

| Service            | Railway Name                   | Start Command                                          | Purpose                   |
| ------------------ | ------------------------------ | ------------------------------------------------------ | ------------------------- |
| API                | `dragonfly-api`                | `uvicorn backend.main:app --host 0.0.0.0 --port $PORT` | Main FastAPI backend      |
| Ingest Worker      | `dragonfly-worker-ingest`      | `python -m backend.workers.ingest_processor`           | CSV/data ingestion        |
| Enforcement Worker | `dragonfly-worker-enforcement` | `python -m backend.workers.enforcement_engine`         | Enforcement pipeline      |
| Simplicity Worker  | `dragonfly-worker-simplicity`  | `python -m backend.workers.simplicity_ingest_worker`   | Simplicity vendor imports |

## Build Configuration

**No build command is required.** Railway uses Nixpacks with the following auto-detected configuration:

- **Python version**: 3.12 (from `runtime.txt`)
- **Dependencies**: `pip install -r requirements.txt`
- **System packages**: PostgreSQL client libraries (auto-detected from `psycopg`)

The `nixpacks.toml` file ensures consistent builds:

```toml
[phases.setup]
nixPkgs = ["python312", "postgresql"]

[phases.install]
cmds = ["pip install --upgrade pip", "pip install -r requirements.txt"]

[start]
cmd = "uvicorn backend.main:app --host 0.0.0.0 --port $PORT"
```

**Each service overrides the start command** in Railway dashboard settings.

## Environment Variables

### Canonical Contract (UPPERCASE only)

All services share these **required** variables:

| Variable                    | Description                                           |
| --------------------------- | ----------------------------------------------------- |
| `SUPABASE_URL`              | Supabase project REST URL (`https://xxx.supabase.co`) |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role JWT (100+ chars, starts with `ey`)       |
| `SUPABASE_DB_URL`           | PostgreSQL connection string (use pooler URL)         |
| `ENVIRONMENT`               | `dev`, `staging`, or `prod`                           |
| `SUPABASE_MODE`             | `dev` or `prod` (credential selection)                |

### Service-Specific Variables

**API only:**
| Variable | Required | Description |
|----------|----------|-------------|
| `PORT` | Yes (injected) | Railway injects this automatically |
| `DRAGONFLY_API_KEY` | Recommended | API key for protected endpoints |
| `DRAGONFLY_CORS_ORIGINS` | Recommended | Comma-separated frontend URLs |

**Enforcement Worker only:**
| Variable | Required | Description |
|----------|----------|-------------|
| `OPENAI_API_KEY` | Recommended | For AI-powered enforcement strategies |

### Deprecated Variables (DELETE these)

The following are **deprecated** and must be removed from Railway:

- Lowercase variants: `supabase_url`, `supabase_service_role_key`, etc.
- `_PROD` suffix: `SUPABASE_URL_PROD`, `SUPABASE_DB_URL_PROD`, etc.
- `_DEV` suffix: `SUPABASE_URL_DEV`, `SUPABASE_DB_URL_DEV`, etc.

**Why:** On Linux (Railway runtime), `LOG_LEVEL` and `log_level` are different variables. If both exist with different values, behavior is undefined.

## Pre-Deploy Audit

Run the environment audit before deploying:

```bash
# Check all services (CI mode)
python scripts/railway_env_audit.py --check

# Check specific service
python scripts/railway_env_audit.py --service api
python scripts/railway_env_audit.py --service enforcement

# Print canonical contract
python scripts/railway_env_audit.py --print-contract
```

### Exit Codes

| Code | Meaning                                                   |
| ---- | --------------------------------------------------------- |
| 0    | All checks passed                                         |
| 1    | Warnings only (deprecated keys, missing recommended vars) |
| 2    | Errors (deprecated key collisions)                        |
| 3    | Critical (case-sensitive conflicts)                       |

## Railway Dashboard Settings

For each service, configure in Railway Dashboard:

1. **Settings > Deploy > Start Command**: Use the command from the table above
2. **Variables**: Set only UPPERCASE canonical variables
3. **Delete**: Any lowercase or `_PROD`/`_DEV` suffixed variables

### Copy-Paste Commands

**API Service:**

```
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

**Ingest Worker:**

```
python -m backend.workers.ingest_processor
```

**Enforcement Worker:**

```
python -m backend.workers.enforcement_engine
```

**Simplicity Worker:**

```
python -m backend.workers.simplicity_ingest_worker
```

## Troubleshooting

### Worker crashes on "SUPABASE_SERVICE_ROLE_KEY too short"

**Symptom:** Worker exits with preflight error:

```
[CRITICAL] PREFLIGHT CHECK FAILED
ERROR 1: SUPABASE_SERVICE_ROLE_KEY is TOO SHORT (50 chars)
```

**Root Cause:** The service role key was truncated when copying to Railway.

**Fix:**

1. Go to Supabase Dashboard → Project Settings → API
2. Copy the **full** `service_role` key (should be 200+ characters)
3. In Railway, delete the existing `SUPABASE_SERVICE_ROLE_KEY` variable
4. Create new variable, paste the full key
5. Redeploy the service

**Validation:**

```bash
# The key should:
# - Start with "ey"
# - Be at least 100 characters
# - Be a valid JWT token

python -c "
import os
key = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')
print(f'Length: {len(key)}')
print(f'Starts with ey: {key.startswith(\"ey\")}')
print(f'Valid: {len(key) >= 100 and key.startswith(\"ey\")}')
"
```

### Build fails for one worker but not another

**Root Cause:** Different start commands or missing environment variables.

**Fix:**

1. Ensure all workers share the same base environment variables
2. Verify the start command matches exactly (case-sensitive)
3. Check for typos in variable names (Railway is case-sensitive on Linux)

### "Module not found" on Railway but works locally

**Root Cause:** Missing dependency or wrong Python path.

**Fix:**

1. Ensure the module is in `requirements.txt`
2. Verify the start command uses `-m` flag: `python -m backend.workers.xxx`
3. Check that `PYTHONPATH` is not set to a conflicting value

## CI Integration

The GitHub Actions workflow `.github/workflows/env-schema-check.yml` includes an `env-contract-check` job that runs on every push affecting environment configuration.

This job:

1. Runs `python scripts/railway_env_audit.py --check`
2. Fails on errors or collisions (exit code >= 2)
3. Passes with warnings on deprecated keys (exit code 1)
4. Prints clear output showing which variables need attention

## Local Testing

Before deploying, simulate Railway environment locally:

```powershell
# PowerShell
$env:ENVIRONMENT = "prod"
$env:SUPABASE_MODE = "prod"
python scripts/railway_env_audit.py --check
```

```bash
# Bash
ENVIRONMENT=prod SUPABASE_MODE=prod python scripts/railway_env_audit.py --check
```
