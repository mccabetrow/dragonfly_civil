# Dragonfly Environment Variables

This document describes the canonical environment variable schema for the Dragonfly platform.

> **Single Source of Truth**: `src/core_config.py`

## Required Variables

These must be set for the application to start:

| Variable                    | Description                   | Example                   |
| --------------------------- | ----------------------------- | ------------------------- |
| `SUPABASE_URL`              | Supabase project REST URL     | `https://xxx.supabase.co` |
| `SUPABASE_SERVICE_ROLE_KEY` | Service role JWT (100+ chars) | `eyJhbGciOiJI...`         |

## Required for Database Operations

| Variable          | Description                  | Example                                                                |
| ----------------- | ---------------------------- | ---------------------------------------------------------------------- |
| `SUPABASE_DB_URL` | PostgreSQL connection string | `postgresql://postgres.project:pass@pooler.supabase.com:5432/postgres` |

## Environment Control

| Variable        | Default | Values                              | Description                              |
| --------------- | ------- | ----------------------------------- | ---------------------------------------- |
| `ENVIRONMENT`   | `dev`   | `dev`, `staging`, `prod`            | Deployment environment                   |
| `SUPABASE_MODE` | `dev`   | `dev`, `prod`                       | Supabase project mode for DSN resolution |
| `LOG_LEVEL`     | `INFO`  | `DEBUG`, `INFO`, `WARNING`, `ERROR` | Logging verbosity                        |

## Recommended for Production

| Variable                 | Description                          | Example                                        |
| ------------------------ | ------------------------------------ | ---------------------------------------------- |
| `DRAGONFLY_API_KEY`      | API key for X-API-Key authentication | `your-secure-key`                              |
| `DRAGONFLY_CORS_ORIGINS` | Comma-separated frontend URLs        | `https://app.vercel.app,http://localhost:3000` |

## Optional Integrations

### Email (SendGrid)

| Variable              | Description          |
| --------------------- | -------------------- |
| `SENDGRID_API_KEY`    | SendGrid API key     |
| `SENDGRID_FROM_EMAIL` | Sender email address |

### SMS (Twilio)

| Variable             | Description                 |
| -------------------- | --------------------------- |
| `TWILIO_ACCOUNT_SID` | Twilio account SID          |
| `TWILIO_AUTH_TOKEN`  | Twilio auth token           |
| `TWILIO_FROM_NUMBER` | Sender phone number (E.164) |

### AI Features (OpenAI)

| Variable         | Description                   |
| ---------------- | ----------------------------- |
| `OPENAI_API_KEY` | OpenAI API key for embeddings |

### Alerts (Discord)

| Variable              | Description                |
| --------------------- | -------------------------- |
| `DISCORD_WEBHOOK_URL` | Discord webhook for alerts |

### Proof.com Integration

| Variable               | Description              |
| ---------------------- | ------------------------ |
| `PROOF_API_KEY`        | Proof.com API key        |
| `PROOF_API_URL`        | Proof.com API URL        |
| `PROOF_WEBHOOK_SECRET` | Webhook signature secret |

### n8n Workflow Integration

| Variable      | Description |
| ------------- | ----------- |
| `N8N_API_KEY` | n8n API key |

### Notification Recipients

| Variable    | Description              |
| ----------- | ------------------------ |
| `CEO_EMAIL` | CEO email for briefings  |
| `OPS_EMAIL` | Operations team email    |
| `OPS_PHONE` | Operations phone (E.164) |

## Server Configuration

| Variable | Default   | Description                        |
| -------- | --------- | ---------------------------------- |
| `HOST`   | `0.0.0.0` | Server bind host                   |
| `PORT`   | `8888`    | Server port (Railway injects this) |

## Deprecated Variables

These are supported for backward compatibility but emit warnings:

### Legacy \_PROD Suffix (use SUPABASE_MODE=prod instead)

| Deprecated                       | Canonical                                             |
| -------------------------------- | ----------------------------------------------------- |
| `SUPABASE_URL_PROD`              | `SUPABASE_URL` with `SUPABASE_MODE=prod`              |
| `SUPABASE_SERVICE_ROLE_KEY_PROD` | `SUPABASE_SERVICE_ROLE_KEY` with `SUPABASE_MODE=prod` |
| `SUPABASE_DB_URL_PROD`           | `SUPABASE_DB_URL` with `SUPABASE_MODE=prod`           |
| `SUPABASE_DB_URL_DIRECT_PROD`    | `SUPABASE_DB_URL` with `SUPABASE_MODE=prod`           |

### Lowercase Aliases (use UPPER_SNAKE_CASE)

| Deprecated                  | Canonical                   |
| --------------------------- | --------------------------- |
| `supabase_url`              | `SUPABASE_URL`              |
| `supabase_service_role_key` | `SUPABASE_SERVICE_ROLE_KEY` |
| `supabase_db_url`           | `SUPABASE_DB_URL`           |

## Startup Validation

On startup, the application validates required environment variables and logs a configuration report:

```
============================================================
DRAGONFLY STARTUP CONFIGURATION REPORT
============================================================
Environment: DEV
Supabase Mode: dev
✓ Present: SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY
⚠ SUPABASE_DB_URL not set - database operations will fail
============================================================
```

If required variables are missing, the application fails fast with an error message.

## Diagnostic Commands

### Print Effective Config

```powershell
# PowerShell
.\scripts\print_effective_config.ps1

# Python
python -c "from src.core_config import print_effective_config; import json; print(json.dumps(print_effective_config(), indent=2))"
```

### Check for Deprecated Keys

```powershell
python -c "from src.core_config import get_settings, get_deprecated_keys_used; get_settings(); print('Deprecated keys:', get_deprecated_keys_used())"
```

### Validate Environment

```powershell
python -c "from src.core_config import validate_required_env; validate_required_env(fail_fast=False)"
```

## CI/CD Integration

The CI workflow includes a check that verifies:

1. All required env vars are documented in `.env.example`
2. The Settings schema matches the documented variables
3. No undocumented required variables exist

See `.github/workflows/env-schema-check.yml`.
