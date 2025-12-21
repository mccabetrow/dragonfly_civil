# Release Runbook — Dragonfly Civil

> **Fail-closed principle**: If any gate fails, halt and fix before proceeding.

---

## Pre-Release Checklist

Run these locally **before** pushing to `main`:

```powershell
# 1. Run full test suite (includes RPC contract tests)
.\.venv\Scripts\python.exe -m pytest -q

# 2. Run tools.doctor health check
.\.venv\Scripts\python.exe -m tools.doctor --env dev

# 3. Run schema consistency check
.\.venv\Scripts\python.exe -m tools.check_schema_consistency --env dev

# 4. Run prod gate against dev (validates DB, RPC, migrations)
$env:SUPABASE_MODE = "dev"
.\.venv\Scripts\python.exe -m tools.prod_gate --env dev

# 5. Build dashboard to catch TypeScript/bundle errors
Set-Location dragonfly-dashboard
npm run build
Set-Location ..
```

All five must pass. Any failure = stop and fix.

---

## Automated CI Gates (GitHub Actions)

When you push to `main`, these workflows enforce fail-closed:

| Workflow                | File                                                                                                              | Gates |
| ----------------------- | ----------------------------------------------------------------------------------------------------------------- | ----- |
| `ci.yml`                | Unit tests, lint (ruff, black, isort)                                                                             |
| `dragonfly-ci.yml`      | Unit tests, `tools.doctor`, RPC contract tests, config check, schema consistency, n8n validation, dashboard build |
| `production_deploy.yml` | RPC contract tests, `tools.doctor`, prod secrets, migrations, prod_gate, prod_smoke                               |

### Contract Gate (in production_deploy.yml)

Before migrations are applied:

1. **RPC contract compliance** — `pytest tests/test_worker_rpc_contract.py`
2. **tools.doctor health** — validates the tool is importable

If either fails, deploy halts immediately.

---

## Migrations

Migrations live in `supabase/migrations/`. To apply:

```powershell
# Dev
./scripts/db_push.ps1 -SupabaseEnv dev

# Prod (CI handles this via production_deploy.yml)
./scripts/db_push.ps1 -SupabaseEnv prod
```

Post-migration validation:

```powershell
# Verify canonical RPC signatures exist
.\.venv\Scripts\python.exe -m tools.doctor --env prod

# Full prod gate
$env:SUPABASE_MODE = "prod"
.\.venv\Scripts\python.exe -m tools.prod_gate --env prod --strict
```

---

## Rollback Procedure

If production deploy fails post-migration:

### 1. Stop bleeding

```powershell
# Disable workers (Railway)
railway environment production
railway down --service dragonfly-worker
```

### 2. Assess migration state

```sql
-- Check last applied migration
SELECT * FROM supabase_migrations.schema_migrations
ORDER BY version DESC LIMIT 5;
```

### 3. Rollback (if safe)

Create a **new** migration that reverts the breaking change. Do **not** edit existing migration files.

```powershell
# Generate new migration file
$ts = Get-Date -Format 'yyyyMMddHHmmss'
New-Item -Path "supabase/migrations/${ts}_rollback_<issue>.sql" -ItemType File
```

### 4. Apply rollback

```powershell
./scripts/db_push.ps1 -SupabaseEnv prod
```

### 5. Restore workers

```powershell
railway up --service dragonfly-worker --environment production
```

---

## Canonical RPC Signatures

These are the current canonical function signatures. Verify with `tools.doctor`:

| Function                 | Signature                             |
| ------------------------ | ------------------------------------- |
| `ops.claim_pending_job`  | `(TEXT[], INTEGER, TEXT)`             |
| `ops.update_job_status`  | `(UUID, TEXT, TEXT, INTEGER)`         |
| `ops.queue_job`          | `(TEXT, JSONB, INTEGER, TIMESTAMPTZ)` |
| `ops.register_heartbeat` | `(TEXT, TEXT, TEXT, TEXT)`            |

The `verify_db_state.sql` script validates these during deployment.

---

## Quick Reference

| Action                   | Command                                              |
| ------------------------ | ---------------------------------------------------- |
| Full test suite          | `pytest -q`                                          |
| Doctor check             | `python -m tools.doctor --env dev`                   |
| Schema consistency       | `python -m tools.check_schema_consistency --env dev` |
| Prod gate (dev)          | `python -m tools.prod_gate --env dev`                |
| Prod gate (prod, strict) | `python -m tools.prod_gate --env prod --strict`      |
| Push migrations (dev)    | `./scripts/db_push.ps1 -SupabaseEnv dev`             |
| Push migrations (prod)   | `./scripts/db_push.ps1 -SupabaseEnv prod`            |
| Dashboard build          | `cd dragonfly-dashboard && npm run build`            |

---

## Version

Last updated: 2025-01-13
