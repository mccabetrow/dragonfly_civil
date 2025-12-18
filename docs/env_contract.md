# Environment Variable Contract

This document defines the canonical environment variables used by Dragonfly Civil services.

## Single Source of Truth

All configuration is loaded through `src/config.py`. Both `backend/config.py` and `src/settings.py` re-export from this canonical module.

## Canonical Environment Variables

All variables should use UPPERCASE names. Lowercase and `_PROD/_DEV` suffixed variants are deprecated but still accepted for backward compatibility.

### Required (Core)

| Variable                    | Description                   | Example                                                      |
| --------------------------- | ----------------------------- | ------------------------------------------------------------ |
| `SUPABASE_URL`              | Supabase project REST URL     | `https://xxx.supabase.co`                                    |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role JWT (100+ chars) | `eyJhbG...`                                                  |
| `SUPABASE_DB_URL`           | PostgreSQL connection string  | `postgresql://postgres:xxx@db.xxx.supabase.co:5432/postgres` |

### Environment Control

| Variable        | Description               | Values                              | Default |
| --------------- | ------------------------- | ----------------------------------- | ------- |
| `ENVIRONMENT`   | Deployment environment    | `dev`, `staging`, `prod`            | `dev`   |
| `SUPABASE_MODE` | Credential selection mode | `dev`, `prod`                       | `dev`   |
| `LOG_LEVEL`     | Logging verbosity         | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO`  |

### API Authentication

| Variable            | Description                       | Required For                 |
| ------------------- | --------------------------------- | ---------------------------- |
| `DRAGONFLY_API_KEY` | API key for X-API-Key header auth | API endpoints requiring auth |

### Optional Integrations

| Variable                 | Description                   |
| ------------------------ | ----------------------------- |
| `OPENAI_API_KEY`         | OpenAI API key for embeddings |
| `DISCORD_WEBHOOK_URL`    | Discord alerts                |
| `SENDGRID_API_KEY`       | Email notifications           |
| `SENDGRID_FROM_EMAIL`    | Default sender email          |
| `TWILIO_ACCOUNT_SID`     | SMS notifications             |
| `TWILIO_AUTH_TOKEN`      | Twilio auth                   |
| `TWILIO_FROM_NUMBER`     | E.164 sender number           |
| `CEO_EMAIL`              | Executive briefing recipient  |
| `OPS_EMAIL`              | Ops team email                |
| `OPS_PHONE`              | Ops team phone (E.164)        |
| `PROOF_API_KEY`          | Proof.com API key             |
| `PROOF_API_URL`          | Proof.com API URL             |
| `DRAGONFLY_CORS_ORIGINS` | Comma-separated CORS origins  |

---

## Service-Specific Requirements

### API Service (backend/main.py)

**Start command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

| Variable                    | Required | Notes                            |
| --------------------------- | -------- | -------------------------------- |
| `SUPABASE_URL`              | ✅       |                                  |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       |                                  |
| `SUPABASE_DB_URL`           | ✅       |                                  |
| `ENVIRONMENT`               | ✅       | Set to `prod` for production     |
| `PORT`                      | ✅       | Injected by Railway              |
| `DRAGONFLY_API_KEY`         | ⚠️       | Required for protected endpoints |
| `DRAGONFLY_CORS_ORIGINS`    | ⚠️       | Required for frontend access     |

### Ingest Worker (backend/workers/ingest_processor.py)

**Start command:** `python -m backend.workers.ingest_processor`

| Variable                    | Required | Notes          |
| --------------------------- | -------- | -------------- |
| `SUPABASE_URL`              | ✅       |                |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       |                |
| `SUPABASE_DB_URL`           | ✅       |                |
| `SUPABASE_MODE`             | ✅       | Must match API |
| `LOG_LEVEL`                 | ⚪       | Optional       |

### Enforcement Worker (backend/workers/enforcement_engine.py)

**Start command:** `python -m backend.workers.enforcement_engine`

| Variable                    | Required | Notes                     |
| --------------------------- | -------- | ------------------------- |
| `SUPABASE_URL`              | ✅       |                           |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       |                           |
| `SUPABASE_DB_URL`           | ✅       |                           |
| `SUPABASE_MODE`             | ✅       | Must match API            |
| `OPENAI_API_KEY`            | ⚠️       | For AI-powered strategies |
| `LOG_LEVEL`                 | ⚪       | Optional                  |

---

## Environment Examples

### Development (.env)

```bash
# Core
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...your-dev-key
SUPABASE_DB_URL=postgresql://postgres:password@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# Environment
ENVIRONMENT=dev
SUPABASE_MODE=dev
LOG_LEVEL=DEBUG

# API Auth (optional for local dev)
DRAGONFLY_API_KEY=dev-test-key-123

# CORS (optional - defaults to localhost)
DRAGONFLY_CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Production (Railway)

```bash
# Core
SUPABASE_URL=https://production-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...your-prod-key
SUPABASE_DB_URL=postgresql://postgres:password@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# Environment
ENVIRONMENT=prod
SUPABASE_MODE=prod
LOG_LEVEL=INFO

# API Auth
DRAGONFLY_API_KEY=secure-random-key-minimum-32-chars

# CORS
DRAGONFLY_CORS_ORIGINS=https://dragonfly-console1.vercel.app,https://dragonfly-console1-git-main-user.vercel.app

# PORT injected by Railway automatically
```

---

## Deprecated Variables

The following variables are deprecated but still accepted for backward compatibility. A startup warning is emitted when they are used.

### Lowercase Variants (use UPPERCASE instead)

| Deprecated                  | Use Instead                 |
| --------------------------- | --------------------------- |
| `supabase_url`              | `SUPABASE_URL`              |
| `supabase_service_role_key` | `SUPABASE_SERVICE_ROLE_KEY` |
| `supabase_db_url`           | `SUPABASE_DB_URL`           |
| `environment`               | `ENVIRONMENT`               |
| `supabase_mode`             | `SUPABASE_MODE`             |
| `log_level`                 | `LOG_LEVEL`                 |

### `_PROD` Suffix Variants (use `SUPABASE_MODE=prod` instead)

| Deprecated                       | Use Instead                                           |
| -------------------------------- | ----------------------------------------------------- |
| `SUPABASE_URL_PROD`              | `SUPABASE_URL` with `SUPABASE_MODE=prod`              |
| `SUPABASE_SERVICE_ROLE_KEY_PROD` | `SUPABASE_SERVICE_ROLE_KEY` with `SUPABASE_MODE=prod` |
| `SUPABASE_DB_URL_PROD`           | `SUPABASE_DB_URL` with `SUPABASE_MODE=prod`           |
| `SUPABASE_DB_URL_DIRECT_PROD`    | `SUPABASE_DB_URL` with `SUPABASE_MODE=prod`           |

---

## Diagnostic Commands

Check which environment variables are in use:

```powershell
# PowerShell - Print effective config (redacts secrets)
.\scripts\print_effective_config.ps1

# Python - Detailed config output
python -c "from src.core_config import print_effective_config; import json; print(json.dumps(print_effective_config(), indent=2))"
```

Check for deprecated keys:

```powershell
python -c "from src.core_config import get_settings, get_deprecated_keys_used; get_settings(); print('Deprecated keys:', get_deprecated_keys_used())"
```

---

## Migration Guide

If you're using deprecated environment variables, update your configuration:

1. **Replace lowercase with UPPERCASE:**

   ```bash
   # Before
   supabase_url=https://xxx.supabase.co

   # After
   SUPABASE_URL=https://xxx.supabase.co
   ```

2. **Replace `_PROD` suffix with `SUPABASE_MODE`:**

   ```bash
   # Before
   SUPABASE_URL_PROD=https://prod.supabase.co
   SUPABASE_DB_URL_PROD=postgresql://...

   # After
   SUPABASE_MODE=prod
   SUPABASE_URL=https://prod.supabase.co
   SUPABASE_DB_URL=postgresql://...
   ```

3. **Use the same variables for all services:**
   - API and workers should all use the same canonical variable names
   - Set `SUPABASE_MODE=prod` in production Railway services

---

## Railway Deployment Checklist

### ⚠️ Mandatory Rules

1. **UPPERCASE keys only** – Delete any lowercase duplicates. On Linux (Railway), `LOG_LEVEL` and `log_level` are separate variables. If both exist with different values, startup will fail with a collision error.

2. **ENVIRONMENT must be `dev`, `staging`, or `prod`** – Values like `production` or `development` are normalized automatically but emit a deprecation warning.

3. **Never expose `SUPABASE_SERVICE_ROLE_KEY` to frontend apps** – This key grants admin access. Only backend services should have it.

4. **Delete deprecated `_PROD` suffix variables** – After migrating to `SUPABASE_MODE=prod`, remove `SUPABASE_URL_PROD`, `SUPABASE_DB_URL_PROD`, etc.

### Pre-Deploy Audit

Before deploying to Railway:

```powershell
# 1. Check for deprecated keys in local env
python -c "from src.core_config import get_settings, get_deprecated_keys_used; get_settings(); used = get_deprecated_keys_used(); print('OK' if not used else f'DEPRECATED: {used}')"

# 2. Validate required env vars
python -c "from src.core_config import validate_required_env; validate_required_env(fail_fast=True)"

# 3. Print effective config (redacts secrets)
python -c "from src.core_config import print_effective_config; import json; print(json.dumps(print_effective_config(), indent=2))"
```

---

## Required Variables by Service (Copy/Paste Reference)

### API Service

| Variable                    | Required | Notes                               |
| --------------------------- | -------- | ----------------------------------- |
| `SUPABASE_URL`              | ✅       | Supabase project URL                |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | Server-side only, never in frontend |
| `SUPABASE_DB_URL`           | ✅       | Use pooler URL in prod              |
| `ENVIRONMENT`               | ✅       | `prod` for production               |
| `SUPABASE_MODE`             | ✅       | `prod` for production               |
| `PORT`                      | ✅       | Injected by Railway                 |
| `DRAGONFLY_API_KEY`         | ⚠️       | Required for protected endpoints    |
| `DRAGONFLY_CORS_ORIGINS`    | ⚠️       | Comma-separated frontend URLs       |
| `LOG_LEVEL`                 | ⚪       | Default: `INFO`                     |

**Start command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

### Ingest Worker

| Variable                    | Required | Notes                  |
| --------------------------- | -------- | ---------------------- |
| `SUPABASE_URL`              | ✅       | Supabase project URL   |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | Server-side only       |
| `SUPABASE_DB_URL`           | ✅       | Use pooler URL in prod |
| `ENVIRONMENT`               | ✅       | Must match API         |
| `SUPABASE_MODE`             | ✅       | Must match API         |
| `LOG_LEVEL`                 | ⚪       | Default: `INFO`        |

**Start command:** `python -m backend.workers.ingest_processor`

### Enforcement Worker

| Variable                    | Required | Notes                               |
| --------------------------- | -------- | ----------------------------------- |
| `SUPABASE_URL`              | ✅       | Supabase project URL                |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅       | Server-side only                    |
| `SUPABASE_DB_URL`           | ✅       | Use pooler URL in prod              |
| `ENVIRONMENT`               | ✅       | Must match API                      |
| `SUPABASE_MODE`             | ✅       | Must match API                      |
| `OPENAI_API_KEY`            | ⚠️       | Required for AI strategy generation |
| `LOG_LEVEL`                 | ⚪       | Default: `INFO`                     |

**Start command:** `python -m backend.workers.enforcement_engine`

### Quick Copy Reference (Production)

```bash
# === REQUIRED FOR ALL SERVICES ===
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
SUPABASE_DB_URL=postgresql://postgres.xxxxx:password@aws-0-us-east-1.pooler.supabase.com:5432/postgres
ENVIRONMENT=prod
SUPABASE_MODE=prod
LOG_LEVEL=INFO

# === API ONLY ===
DRAGONFLY_API_KEY=your-secure-api-key-32-chars-min
DRAGONFLY_CORS_ORIGINS=https://your-app.vercel.app

# === ENFORCEMENT WORKER ONLY ===
OPENAI_API_KEY=sk-...
```

### Legend

| Symbol | Meaning                                     |
| ------ | ------------------------------------------- |
| ✅     | Required - service will fail without it     |
| ⚠️     | Conditionally required - some features need |
| ⚪     | Optional - has sensible default             |

---

## CI Environment Contract Check

The repository includes automated CI checks that run on every push affecting environment configuration:

### Workflow: `.github/workflows/env-schema-check.yml`

Two jobs run automatically:

1. **check-env-schema** – Validates that `core_config.py`, `.env.example`, and `docs/env.md` stay synchronized.
2. **env-contract-check** – Runs `scripts/railway_env_audit.py --check` to detect deprecated keys and collision risks.

### Local Audit Command

Before deploying to Railway, run the audit locally:

```powershell
# Print canonical env contract
python scripts/railway_env_audit.py

# CI mode (fails on deprecated keys or collisions)
python scripts/railway_env_audit.py --check
```

### Exit Codes

| Code | Meaning                                                            |
| ---- | ------------------------------------------------------------------ |
| 0    | OK – all clear                                                     |
| 1    | Warnings only – deprecated keys detected but no collisions         |
| 2    | Errors – deprecated keys found (CI should fail)                    |
| 3    | Critical – potential collisions (lowercase + uppercase duplicates) |

---

## ⚠️ Linux/Railway Collision Warning

On Linux (Railway's runtime), environment variables are **case-sensitive**:

```
LOG_LEVEL=INFO     # uppercase – correct
log_level=DEBUG    # lowercase – separate variable!
```

If both exist with different values, `railway_env_audit.py` will detect a collision and fail with exit code 3.

**Action required:** Delete all lowercase duplicates from your Railway service variables before deploying.

To check for collisions locally:

```powershell
python scripts/railway_env_audit.py --check
```
