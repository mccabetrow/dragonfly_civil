# Environment Variable Contract

> **Single Source of Truth** — All environment configuration is defined here and validated by
> `scripts/railway_env_audit.py`. Keep docs and code in sync: the audit script imports this contract.

---

## Quick Reference: Required Variables by Service

| Variable                    | API | Ingest | Enforcement |     Shared     | Default  |
| --------------------------- | :-: | :----: | :---------: | :------------: | -------- |
| `SUPABASE_URL`              | ✅  |   ✅   |     ✅      | Railway Shared | —        |
| `SUPABASE_SERVICE_ROLE_KEY` | ✅  |   ✅   |     ✅      | Railway Shared | —        |
| `SUPABASE_DB_URL`           | ✅  |   ✅   |     ✅      | Railway Shared | —        |
| `ENVIRONMENT`               | ✅  |   ✅   |     ✅      | Railway Shared | `dev`    |
| `SUPABASE_MODE`             | ✅  |   ✅   |     ✅      | Railway Shared | `dev`    |
| `PORT`                      | ✅  |   —    |      —      | Service-Level  | Injected |
| `DRAGONFLY_API_KEY`         | ⚠️  |   —    |      —      | Service-Level  | —        |
| `DRAGONFLY_CORS_ORIGINS`    | ⚠️  |   —    |      —      | Service-Level  | `*`      |
| `OPENAI_API_KEY`            |  —  |   —    |     ⚠️      | Service-Level  | —        |
| `LOG_LEVEL`                 | ⚪  |   ⚪   |     ⚪      | Railway Shared | `INFO`   |

**Legend:** ✅ = Required | ⚠️ = Conditionally Required | ⚪ = Optional | — = Not Used

---

## 1. Canonical Environment Variables

All variables use **UPPERCASE** names. Lowercase and `_PROD/_DEV` suffixes are **deprecated**.

### 1.1 Core (Required for All Services)

| Variable                    | Type   | Description                           | Example                                                            |
| --------------------------- | ------ | ------------------------------------- | ------------------------------------------------------------------ |
| `SUPABASE_URL`              | string | Supabase project REST URL             | `https://xxx.supabase.co`                                          |
| `SUPABASE_SERVICE_ROLE_KEY` | string | Service role JWT (100+ chars)         | `eyJhbG...`                                                        |
| `SUPABASE_DB_URL`           | string | PostgreSQL connection string (pooler) | `postgresql://postgres.xxx:pass@pooler.supabase.com:5432/postgres` |

### 1.2 Environment Control

| Variable        | Type | Values                              | Default | Description               |
| --------------- | ---- | ----------------------------------- | ------- | ------------------------- |
| `ENVIRONMENT`   | enum | `dev`, `staging`, `prod`            | `dev`   | Deployment environment    |
| `SUPABASE_MODE` | enum | `dev`, `prod`                       | `dev`   | Credential selection mode |
| `LOG_LEVEL`     | enum | `DEBUG`, `INFO`, `WARNING`, `ERROR` | `INFO`  | Logging verbosity         |

### 1.3 API-Only Variables

| Variable                 | Required             | Description                         |
| ------------------------ | -------------------- | ----------------------------------- |
| `PORT`                   | ✅ (Railway injects) | HTTP port for uvicorn               |
| `DRAGONFLY_API_KEY`      | ⚠️                   | API key for `X-API-Key` header auth |
| `DRAGONFLY_CORS_ORIGINS` | ⚠️                   | Comma-separated CORS origins        |

### 1.4 Worker-Specific Variables

| Variable         | Service     | Required | Description                        |
| ---------------- | ----------- | -------- | ---------------------------------- |
| `OPENAI_API_KEY` | Enforcement | ⚠️       | For AI-powered strategy generation |

### 1.5 Optional Integrations

| Variable              | Description                  |
| --------------------- | ---------------------------- |
| `DISCORD_WEBHOOK_URL` | Discord alerts               |
| `SENDGRID_API_KEY`    | Email notifications          |
| `SENDGRID_FROM_EMAIL` | Default sender email         |
| `TWILIO_ACCOUNT_SID`  | SMS notifications            |
| `TWILIO_AUTH_TOKEN`   | Twilio auth                  |
| `TWILIO_FROM_NUMBER`  | E.164 sender number          |
| `CEO_EMAIL`           | Executive briefing recipient |
| `OPS_EMAIL`           | Ops team email               |
| `OPS_PHONE`           | Ops team phone (E.164)       |
| `PROOF_API_KEY`       | Proof.com API key            |
| `PROOF_API_URL`       | Proof.com API URL            |

---

## 2. Railway Variable Strategy

### 2.1 Shared Variables (Project-Level)

Set these **once** in Railway's shared variables. All services inherit them:

```bash
# Core Supabase (NEVER service-level — prevents drift)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_SERVICE_ROLE_KEY=eyJhbG...your-prod-key
SUPABASE_DB_URL=postgresql://postgres.xxx:password@pooler.supabase.com:5432/postgres

# Environment flags
ENVIRONMENT=prod
SUPABASE_MODE=prod
LOG_LEVEL=INFO
```

**Why shared?**

- Prevents credential drift between services
- Single update point when rotating keys
- All services must use the same Supabase project

### 2.2 Service-Level Variables

Set these **per-service** in Railway:

| Service                        | Variable                 | Reason                   |
| ------------------------------ | ------------------------ | ------------------------ |
| `dragonfly-api`                | `DRAGONFLY_API_KEY`      | Only API needs auth key  |
| `dragonfly-api`                | `DRAGONFLY_CORS_ORIGINS` | Only API serves HTTP     |
| `dragonfly-worker-enforcement` | `OPENAI_API_KEY`         | Only enforcement uses AI |

### 2.3 Railway-Injected Variables

Railway automatically injects these — **do not set manually**:

| Variable               | Auto-Set By                |
| ---------------------- | -------------------------- |
| `PORT`                 | Railway (API service only) |
| `RAILWAY_ENVIRONMENT`  | Railway (all services)     |
| `RAILWAY_SERVICE_NAME` | Railway (all services)     |

---

## 3. Service Configurations

### 3.1 API Service (`dragonfly-api`)

**Start command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`

| Variable                    | Source  | Required  |
| --------------------------- | ------- | --------- |
| `SUPABASE_URL`              | Shared  | ✅        |
| `SUPABASE_SERVICE_ROLE_KEY` | Shared  | ✅        |
| `SUPABASE_DB_URL`           | Shared  | ✅        |
| `ENVIRONMENT`               | Shared  | ✅        |
| `SUPABASE_MODE`             | Shared  | ✅        |
| `PORT`                      | Railway | ✅ (auto) |
| `DRAGONFLY_API_KEY`         | Service | ⚠️        |
| `DRAGONFLY_CORS_ORIGINS`    | Service | ⚠️        |
| `LOG_LEVEL`                 | Shared  | ⚪        |

### 3.2 Ingest Worker (`dragonfly-worker-ingest`)

**Start command:** `python -m backend.workers.ingest_processor`

| Variable                    | Source | Required |
| --------------------------- | ------ | -------- |
| `SUPABASE_URL`              | Shared | ✅       |
| `SUPABASE_SERVICE_ROLE_KEY` | Shared | ✅       |
| `SUPABASE_DB_URL`           | Shared | ✅       |
| `ENVIRONMENT`               | Shared | ✅       |
| `SUPABASE_MODE`             | Shared | ✅       |
| `LOG_LEVEL`                 | Shared | ⚪       |

### 3.3 Enforcement Worker (`dragonfly-worker-enforcement`)

**Start command:** `python -m backend.workers.enforcement_engine`

| Variable                    | Source  | Required |
| --------------------------- | ------- | -------- |
| `SUPABASE_URL`              | Shared  | ✅       |
| `SUPABASE_SERVICE_ROLE_KEY` | Shared  | ✅       |
| `SUPABASE_DB_URL`           | Shared  | ✅       |
| `ENVIRONMENT`               | Shared  | ✅       |
| `SUPABASE_MODE`             | Shared  | ✅       |
| `OPENAI_API_KEY`            | Service | ⚠️       |
| `LOG_LEVEL`                 | Shared  | ⚪       |

---

## 4. Validation & Audit

### 4.1 Local Environment Audit

```powershell
# Print canonical contract
python scripts/railway_env_audit.py --print-contract

# Audit local env (warns on deprecated keys)
python scripts/railway_env_audit.py --service api

# CI mode (fails on missing required or collisions)
python scripts/railway_env_audit.py --check
```

**Exit Codes:**

| Code | Meaning                                     |
| ---- | ------------------------------------------- |
| 0    | All checks passed                           |
| 1    | Missing required variables                  |
| 2    | Deprecated key collision detected           |
| 3    | Case-sensitive conflict (critical on Linux) |

### 4.2 Railway Environment Audit

The audit script can validate Railway service variables directly:

```powershell
# Audit Railway prod (requires RAILWAY_TOKEN)
python scripts/railway_env_audit.py --railway --project dragonfly-civil

# Dry run: show what would be checked
python scripts/railway_env_audit.py --railway --dry-run
```

### 4.3 Pre-Deploy Check

Before any production deployment:

```powershell
# Full pre-deploy gate (includes Railway env validation)
.\scripts\pre_deploy_check.ps1

# This will FAIL if:
# - Any Railway service is missing SUPABASE_DB_URL
# - Deprecated _PROD/_DEV suffix keys exist
# - Case-sensitive collisions detected
```

---

## 5. Deprecated Variables

### 5.1 Lowercase Variants (Use UPPERCASE)

| Deprecated                  | Use Instead                 |
| --------------------------- | --------------------------- |
| `supabase_url`              | `SUPABASE_URL`              |
| `supabase_service_role_key` | `SUPABASE_SERVICE_ROLE_KEY` |
| `supabase_db_url`           | `SUPABASE_DB_URL`           |
| `environment`               | `ENVIRONMENT`               |
| `supabase_mode`             | `SUPABASE_MODE`             |
| `log_level`                 | `LOG_LEVEL`                 |

### 5.2 `_PROD` Suffix Variants (Use `SUPABASE_MODE=prod`)

| Deprecated                       | Use Instead                                        |
| -------------------------------- | -------------------------------------------------- |
| `SUPABASE_URL_PROD`              | `SUPABASE_URL` + `SUPABASE_MODE=prod`              |
| `SUPABASE_SERVICE_ROLE_KEY_PROD` | `SUPABASE_SERVICE_ROLE_KEY` + `SUPABASE_MODE=prod` |
| `SUPABASE_DB_URL_PROD`           | `SUPABASE_DB_URL` + `SUPABASE_MODE=prod`           |
| `SUPABASE_DB_URL_DIRECT_PROD`    | `SUPABASE_DB_URL` + `SUPABASE_MODE=prod`           |

---

## 6. Code Behavior Reference

### 6.1 DB URL Resolution (`src/supabase_client.py`)

The `get_supabase_db_url()` function uses this priority:

```python
# Priority order:
1. SUPABASE_DB_URL          # Canonical - if present, use regardless of mode
2. SUPABASE_DB_URL_DIRECT_PROD  # Legacy: prod direct connection
3. SUPABASE_DB_URL_PROD / SUPABASE_DB_URL_DEV  # Legacy: by mode
4. Construct from SUPABASE_DB_PASSWORD + SUPABASE_PROJECT_REF  # Fallback
```

**Critical:** In production Railway, `SUPABASE_DB_URL` must be set as a shared variable.
The code uses it directly without checking `SUPABASE_MODE`.

### 6.2 Credentials Resolution (`src/core_config.py`)

```python
# Settings loader accepts both uppercase and lowercase (case_sensitive=False)
# But canonical uppercase takes precedence
SUPABASE_URL > supabase_url
```

### 6.3 Startup Validation

On startup, each service validates required env vars:

```python
# From src/core_config.py - validate_required_env()
missing = []
for var in REQUIRED_VARS:
    if not os.getenv(var):
        missing.append(var)
if missing:
    raise RuntimeError(f"Missing required env vars: {missing}")
```

---

## 7. Migration Guide

### 7.1 From Lowercase to UPPERCASE

```bash
# Before (deprecated)
supabase_url=https://xxx.supabase.co

# After (canonical)
SUPABASE_URL=https://xxx.supabase.co
```

### 7.2 From `_PROD` Suffix to `SUPABASE_MODE`

```bash
# Before (deprecated)
SUPABASE_URL_PROD=https://prod.supabase.co
SUPABASE_DB_URL_PROD=postgresql://...

# After (canonical)
SUPABASE_MODE=prod
SUPABASE_URL=https://prod.supabase.co
SUPABASE_DB_URL=postgresql://...
```

### 7.3 Railway Migration Steps

1. **Add shared variables** with canonical names
2. **Verify services inherit** shared variables
3. **Delete deprecated `_PROD` keys** from all services
4. **Run audit:** `python scripts/railway_env_audit.py --railway`
5. **Deploy and verify** via `scripts/pre_deploy_check.ps1`

---

## 8. Linux/Railway Collision Warning

⚠️ On Linux (Railway's runtime), environment variables are **case-sensitive**:

```bash
LOG_LEVEL=INFO     # uppercase
log_level=DEBUG    # separate variable!
```

If both exist with different values, startup fails with a collision error.

**Action:** Delete all lowercase duplicates from Railway before deploying.

---

## 9. Railway Deployment Checklist

### Before Every Deploy

- [ ] Run `python scripts/railway_env_audit.py --check` locally
- [ ] Verify all services have `SUPABASE_DB_URL` (not just shared)
- [ ] Confirm `SUPABASE_MODE=prod` in shared variables
- [ ] Delete any deprecated `_PROD` suffix variables
- [ ] Run `.\scripts\pre_deploy_check.ps1` — must exit 0

### After Deploy

- [ ] Check `/api/ready` returns 200
- [ ] Verify worker heartbeats in `ops.worker_heartbeats`
- [ ] Run `tools/prod_gate.py --env prod` — all 5 checks pass
