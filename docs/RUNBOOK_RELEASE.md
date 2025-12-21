# Release Runbook — Dragonfly Civil

> **The Constitution for Production Deployments**
>
> **Fail-closed principle**: If any gate fails, halt and fix before proceeding.

---

## Section 1: Contract Truth Sources

### The Only Sources of Truth

| Truth Domain           | Authoritative Source                     | Verification                               |
| ---------------------- | ---------------------------------------- | ------------------------------------------ |
| **Database Schema**    | `supabase/migrations/*.sql`              | `supabase db diff`                         |
| **RPC Signatures**     | `tests/test_rpc_contract.py`             | `pytest tests/test_rpc_contract.py`        |
| **Worker Contract**    | `tests/test_worker_rpc_contract.py`      | `pytest tests/test_worker_rpc_contract.py` |
| **Environment Config** | `src/core_config.py` + `.env.{dev,prod}` | `python -m tools.env_doctor`               |
| **View Definitions**   | `dashboards/sql/*.sql` + migrations      | `python -m tools.doctor --env prod`        |

### What This Means

1. **Database Migrations** (`supabase/migrations/`) define the schema. If a table, column, or RPC is not in a migration, it does not exist.

2. **Contract Tests** (`tests/test_rpc_contract.py`) define what the application expects. If the DB signature drifts from the contract test, the deployment gate fails.

3. **No Other Sources**: Production console output, Supabase Studio, or ad-hoc queries are **NOT** sources of truth. They are diagnostic tools only.

---

## Section 2: The Prime Directive

> **No manual SQL is ever run in Production without a corresponding migration file and contract test update.**

### Violations and Consequences

| Violation                             | Risk                             | Consequence                 |
| ------------------------------------- | -------------------------------- | --------------------------- |
| Manual `ALTER TABLE` in prod          | Schema drift → Worker crashes    | Immediate rollback required |
| RPC created without migration         | Next deploy overwrites it        | Feature silently breaks     |
| Column added without contract test    | Workers may not use it correctly | Data corruption risk        |
| `INSERT`/`UPDATE` without audit trail | Untraceable state changes        | Compliance failure          |

### Approved SQL Execution Paths

```
✅ APPROVED:
   1. supabase/migrations/{timestamp}_{description}.sql
   2. scripts/db_push.ps1 -SupabaseEnv {dev|prod}
   3. Verified by: python -m tools.doctor --env {env}

❌ FORBIDDEN:
   1. Direct SQL in Supabase Studio (production)
   2. psql one-liners against production
   3. Any change not captured in version control
```

---

## Section 3: B3 Deployment Protocol

### Overview

The **B3 (Build-Before-Break) Protocol** ensures code correctness is verified before any production change.

```
┌─────────────────────────────────────────────────────────────────┐
│                    B3 DEPLOYMENT SEQUENCE                       │
├─────────────────────────────────────────────────────────────────┤
│  PHASE 0: FREEZE                                                │
│    └─ Scale Railway workers to 0                                │
│    └─ Reason: Prevent in-flight jobs during migration           │
│                                                                 │
│  PHASE 1: GATE (Hard Fail)                                      │
│    └─ pytest -m "not integration"                               │
│    └─ Tests: RPC-CONTRACT, WORKER-CONTRACT, UNIT-TESTS          │
│    └─ If ANY fail → ABORT immediately                           │
│                                                                 │
│  PHASE 2: GATE (Soft Fail)                                      │
│    └─ pytest -m "integration"                                   │
│    └─ Tests: PostgREST, Pooler, Realtime connectivity           │
│    └─ If fail → WARN but continue (external infra may be flaky) │
│                                                                 │
│  PHASE 3: MIGRATE                                               │
│    └─ ./scripts/db_push.ps1 -SupabaseEnv prod                   │
│    └─ Applies all pending migrations atomically                 │
│                                                                 │
│  PHASE 4: VERIFY                                                │
│    └─ python -m tools.doctor --env prod                         │
│    └─ python -m tools.prod_gate --env prod --strict             │
│    └─ All checks must pass                                      │
│                                                                 │
│  PHASE 5: DEPLOY                                                │
│    └─ Railway: redeploy with new code                           │
│    └─ Scale workers back up                                     │
│    └─ Monitor logs for 15 minutes                               │
│                                                                 │
│  PHASE 6: SMOKE                                                 │
│    └─ python -m tools.prod_smoke                                │
│    └─ Verify critical paths work end-to-end                     │
└─────────────────────────────────────────────────────────────────┘
```

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
