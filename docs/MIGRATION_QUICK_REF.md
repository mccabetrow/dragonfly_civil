# Migration Operator Quick Reference

## Daily Health Check

```powershell
# Check migration status
.\.venv\Scripts\python.exe -m tools.migration_status --env prod

# Full prod gate (includes migrations)
.\.venv\Scripts\python.exe -m tools.prod_gate --mode prod --env prod
```

## Validation Modes

| Mode                 | Behavior                                | When to Use             |
| -------------------- | --------------------------------------- | ----------------------- |
| `manifest` (default) | Check required migrations + count match | Normal operations       |
| `relaxed`            | Only check required migrations          | After manual repairs    |
| `strict`             | All local = all applied                 | Pre-squash verification |

Set mode: `$env:MIGRATION_VALIDATION_MODE = "manifest"`

## Reconciliation Commands

```powershell
# Dry-run: see what would be inserted
.\.venv\Scripts\python.exe -m tools.baseline_migrations --dry-run

# Commit: mark all local migrations as applied
.\.venv\Scripts\python.exe -m tools.baseline_migrations --commit

# Repair version drift
.\.venv\Scripts\python.exe -m tools.repair_migration_history --env prod --execute
```

## Apply Migrations

```powershell
# Dev environment
./scripts/db_push.ps1 -SupabaseEnv dev

# Production (requires confirmation)
./scripts/db_push.ps1 -SupabaseEnv prod
```

## Emergency: Remove Bad Migration

```powershell
# 1. Run rollback SQL manually
# 2. Remove from history
$version = "20260118"
psql $env:DATABASE_URL -c "DELETE FROM supabase_migrations.schema_migrations WHERE version = '$version'"
# 3. Verify
.\.venv\Scripts\python.exe -m tools.prod_gate --mode prod --env prod
```

## Files

| File                               | Purpose                      |
| ---------------------------------- | ---------------------------- |
| `supabase/migration_manifest.yaml` | Declares required migrations |
| `supabase/migrations/*.sql`        | Migration files              |
| `tools/prod_gate.py`               | Release gate validation      |
| `tools/baseline_migrations.py`     | Mark migrations as applied   |
| `docs/MIGRATION_POLICY.md`         | Full policy document         |
