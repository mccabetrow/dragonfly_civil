# Dragonfly Civil — Migration Management Policy

> **Status**: Active  
> **Effective Date**: 2026-01-18  
> **Owner**: Platform Engineering

---

## Executive Summary

This document establishes the migration management policy for Dragonfly Civil, addressing:

1. **Reconciliation** — How to align local migrations with `supabase_migrations.schema_migrations`
2. **Squash/Archive** — How to reduce migration count safely
3. **Gate Validation** — How `prod_gate` validates migrations intelligently
4. **CI Enforcement** — How GitHub Actions applies migrations and prevents drift
5. **Operator Checklist** — Step-by-step operational procedures
6. **Policy Going Forward** — Rules for all future migrations

---

## Part 1: Current State Analysis

### Schema Migration Table Structure

```sql
-- supabase_migrations.schema_migrations
CREATE TABLE schema_migrations (
    version TEXT PRIMARY KEY,  -- e.g., "0001", "0002", "20261102"
    statements TEXT[],         -- SQL statements applied
    name TEXT                  -- Human-readable name (e.g., "core_schema")
);
```

### Naming Convention

| Local File                          | DB `version` | DB `name`              |
| ----------------------------------- | ------------ | ---------------------- |
| `0001_core_schema.sql`              | `0001`       | `core_schema`          |
| `20261102_verify_view_security.sql` | `20261102`   | `verify_view_security` |

**Key insight**: The `version` column stores only the numeric prefix before the first underscore.

### Current Inventory

| Metric                | Value                                         |
| --------------------- | --------------------------------------------- |
| Local migrations      | 319                                           |
| DB applied migrations | 319                                           |
| Version format        | Mixed (4-digit `0001` + 8-digit `20261102`)   |
| Oldest migration      | `0001_core_schema.sql`                        |
| Newest migration      | `20261105_enforce_security_invoker_views.sql` |

---

## Part 2: Reconciliation Strategy

### 2.1 Detecting Drift

Use the existing tooling:

```powershell
# Full status report
.\.venv\Scripts\python.exe -m tools.migration_status --env prod

# Repair analysis (dry-run)
.\.venv\Scripts\python.exe -m tools.repair_migration_history --env prod

# prod_gate migration check
.\.venv\Scripts\python.exe -m tools.prod_gate --mode prod --env prod
```

### 2.2 Types of Drift

| Type                 | Description                       | Resolution                                     |
| -------------------- | --------------------------------- | ---------------------------------------------- |
| **Missing in DB**    | Local file exists, no DB record   | Run `supabase migration up` or insert baseline |
| **Missing locally**  | DB record exists, no local file   | Either restore file or remove orphan DB record |
| **Version mismatch** | Different version formats         | Run `repair_migration_history --execute`       |
| **Content drift**    | Schema changed outside migrations | Manual investigation required                  |

### 2.3 Reconciliation Tool: `tools/baseline_migrations.py`

For environments where migrations were applied manually, use the baseline tool:

```powershell
# Dry-run: See what would be inserted
.\.venv\Scripts\python.exe -m tools.baseline_migrations --dry-run

# Commit: Mark all local migrations as applied
.\.venv\Scripts\python.exe -m tools.baseline_migrations --commit
```

This inserts records with `ON CONFLICT DO NOTHING`, making it idempotent.

---

## Part 3: Squash/Archive Strategy

### 3.1 When to Squash

Squash migrations when:

- ✅ Migration count exceeds 500
- ✅ Performance impact on deployment
- ✅ Major version release (e.g., v2.0)
- ✅ Team agrees to reset baseline

**Never squash** if:

- ❌ Active production traffic depends on incremental rollback
- ❌ Audit trail requirements mandate full history
- ❌ Team lacks consensus

### 3.2 Squash Procedure

#### Step 1: Create Baseline Snapshot

```powershell
# Dump current schema (no data)
$env:DATABASE_URL = "postgresql://postgres:xxx@db.xxx.supabase.co:5432/postgres?sslmode=require"
pg_dump --schema-only --no-owner --no-acl $env:DATABASE_URL > schema_baseline_$(Get-Date -Format "yyyyMMdd").sql
```

#### Step 2: Archive Old Migrations

```powershell
# Move old migrations to archive
New-Item -ItemType Directory -Path "archive/migrations_$(Get-Date -Format 'yyyyMMdd')" -Force
Move-Item "supabase/migrations/0*.sql" "archive/migrations_$(Get-Date -Format 'yyyyMMdd')/"
```

#### Step 3: Create Consolidated Migration

```sql
-- supabase/migrations/0001_baseline_v1.sql
-- Consolidated schema as of 2026-01-18
-- Squashes migrations 0001-0319

-- [Include full schema here from pg_dump output]

-- Marker comment for tooling
-- SQUASH_BASELINE: 2026-01-18
-- SQUASH_COUNT: 319
-- SQUASH_HASH: sha256:<hash of original migration contents>
```

#### Step 4: Update Migration History

```sql
-- Reset schema_migrations to single baseline entry
BEGIN;

-- Archive old records (optional: move to audit table)
CREATE TABLE IF NOT EXISTS supabase_migrations.schema_migrations_archive AS
SELECT * FROM supabase_migrations.schema_migrations;

-- Clear and insert baseline
TRUNCATE supabase_migrations.schema_migrations;
INSERT INTO supabase_migrations.schema_migrations (version, statements, name)
VALUES ('0001', ARRAY['-- Baseline squash 2026-01-18'], 'baseline_v1');

COMMIT;
```

#### Step 5: Validate

```powershell
.\.venv\Scripts\python.exe -m tools.prod_gate --mode prod --env prod
```

### 3.3 Archive Retention Policy

| Location                                        | Retention | Purpose                         |
| ----------------------------------------------- | --------- | ------------------------------- |
| `archive/migrations_YYYYMMDD/`                  | 1 year    | Audit trail, rollback reference |
| `supabase_migrations.schema_migrations_archive` | 6 months  | Database-side audit             |
| Git history                                     | Permanent | Full source control history     |

---

## Part 4: Intelligent Gate Validation

### 4.1 Current prod_gate Behavior

The `check_migrations()` function in [tools/prod_gate.py](../tools/prod_gate.py) compares:

- Local migration file versions (extracted from filenames)
- Applied migrations in `supabase_migrations.schema_migrations`

### 4.2 Enhanced Validation: Version-Aware Gates

#### Option A: Manifest-Based Validation (Recommended)

Create a manifest file that declares which migrations are required for each release:

```yaml
# supabase/migration_manifest.yaml
version: "1.0"
baseline: "0001"
required_migrations:
  - "0001" # core_schema
  - "0002" # enrichment_rpc
  # ... etc

# Optional: declare squash points
squash_points:
  - version: "0001_baseline_v1"
    replaces: ["0001", "0002", "...", "0319"]
```

#### Option B: Branch-Based Validation

Check only migrations introduced since a baseline commit:

```python
def check_migrations_since_baseline(env: str, baseline_version: str = "0001") -> CheckResult:
    """Only validate migrations newer than baseline."""
    local_versions = get_local_versions()
    applied = get_applied_versions(env)

    # Filter to migrations after baseline
    relevant = [v for v in local_versions if v >= baseline_version]
    pending = [v for v in relevant if v not in applied]

    # ... rest of validation
```

#### Option C: Hash-Based Validation

Compute hash of applied schema and compare to expected:

```python
def check_schema_hash(env: str) -> CheckResult:
    """Validate schema state regardless of migration path."""
    expected_hash = load_expected_schema_hash()  # From committed file
    actual_hash = compute_current_schema_hash(env)

    if expected_hash == actual_hash:
        return CheckResult(passed=True, message="Schema matches expected state")
    else:
        return CheckResult(passed=False, message="Schema drift detected")
```

### 4.3 Recommended Implementation

Add to `tools/prod_gate.py`:

```python
# Migration validation modes
MIGRATION_MODE = os.environ.get("MIGRATION_VALIDATION_MODE", "strict")
# strict: All local migrations must be applied (current behavior)
# manifest: Only migrations in manifest must be applied
# relaxed: Only check for schema drift, ignore migration count
```

---

## Part 5: CI/CD Enforcement

### 5.1 Current CI Behavior

The `.github/workflows/supabase-migrate.yml` workflow:

1. Triggers on push to `main` when `supabase/migrations/**` changes
2. Runs `supabase migration up --db-url --include-all`
3. Verifies critical views exist
4. Notifies Discord on failure

### 5.2 Enhanced CI Pipeline

#### Add Migration Drift Check to PR Validation

```yaml
# .github/workflows/ci_gate.yml - Add migration validation step
- name: Check Migration Consistency
  run: |
    # Ensure all local migrations have corresponding test coverage
    python -m tools.migration_status --env test --format json > migration_status.json

    # Fail if pending migrations exist that aren't in this PR
    PENDING=$(jq '.pending_count' migration_status.json)
    if [ "$PENDING" -gt 0 ]; then
      echo "::error::Found $PENDING pending migrations not in this PR"
      exit 1
    fi
```

#### Add Post-Merge Migration Gate

```yaml
# .github/workflows/supabase-migrate.yml - Add post-migration validation
- name: Run prod_gate migration check
  env:
    DB_URL: ${{ secrets[steps.db-url.outputs.db_url_secret] }}
    DATABASE_URL: ${{ secrets[steps.db-url.outputs.db_url_secret] }}
  run: |
    pip install -r requirements.txt
    python -m tools.prod_gate --mode prod --env ${{ steps.db-url.outputs.environment }} --checks migrations
```

### 5.3 Drift Prevention Rules

| Rule                                  | Enforcement       | Location                 |
| ------------------------------------- | ----------------- | ------------------------ |
| No direct SQL in production           | Review policy     | CODEOWNERS, PR templates |
| All schema changes via migrations     | CI gate           | `supabase-migrate.yml`   |
| Migration files immutable after merge | Git hooks         | `.git/hooks/pre-commit`  |
| Squash requires approval              | Branch protection | `main` rules             |

---

## Part 6: Operator Checklist

### 6.1 Daily Operations

```
□ Check migration status: python -m tools.migration_status --env prod
□ Verify no pending migrations in prod_gate output
□ Review Discord alerts for migration failures
```

### 6.2 Before Deploying New Migrations

```
□ Run migrations in dev first: ./scripts/db_push.ps1 -SupabaseEnv dev
□ Verify dev prod_gate passes: python -m tools.prod_gate --env dev
□ Review migration SQL manually
□ Test rollback procedure if applicable
□ Document breaking changes in PR description
□ Merge to main (triggers auto-apply to dev)
□ Manually trigger prod migration via GitHub Actions
□ Verify prod prod_gate passes
```

### 6.3 After Manual Database Changes (Emergency)

```
□ Document change in #incidents channel
□ Create migration file to match current state
□ Run baseline tool: python -m tools.baseline_migrations --commit
□ Verify prod_gate passes
□ Update migration_manifest.yaml if using manifest mode
□ Create post-incident review
```

### 6.4 Quarterly Maintenance

```
□ Review migration count (target: <500)
□ Evaluate squash candidates
□ Audit archive retention
□ Test disaster recovery with migration replay
□ Update schema documentation
```

---

## Part 7: Migration Policy Going Forward

### 7.1 Naming Convention

```
YYYYMMDD_descriptive_name.sql
```

Examples:

- `20260118_add_plaintiff_status_column.sql`
- `20260118_create_enforcement_score_view.sql`

**Never use**:

- Sequential numbers (`0320_xxx.sql`) — causes merge conflicts
- Timestamps with time (`20260118153000_xxx.sql`) — unnecessary precision

### 7.2 Migration File Requirements

Every migration file MUST:

```sql
-- Migration: 20260118_example.sql
-- Author: <github_username>
-- Purpose: <one-line description>
-- Rollback: <rollback strategy or "Not applicable">

BEGIN;

-- Your SQL here

COMMIT;
```

### 7.3 Review Requirements

| Change Type           | Required Approvers | Additional Checks  |
| --------------------- | ------------------ | ------------------ |
| Add column (nullable) | 1 engineer         | None               |
| Add column (NOT NULL) | 2 engineers        | Backfill plan      |
| Drop column           | 2 engineers + lead | 30-day deprecation |
| Alter type            | 2 engineers        | Lock analysis      |
| Drop table            | Lead + PM          | Data export plan   |
| Create/alter RPC      | 1 engineer         | Security review    |
| Create/alter view     | 1 engineer         | Performance check  |

### 7.4 Prohibited Patterns

❌ **Never**:

- Run DDL directly in production outside migrations
- Modify migration files after merge to main
- Use `DROP ... CASCADE` without explicit approval
- Create migrations that depend on external state
- Commit migrations with hardcoded credentials

### 7.5 Breaking Change Protocol

1. Create deprecation migration (add new, keep old)
2. Update all consumers
3. Wait 30 days
4. Create removal migration
5. Document in CHANGELOG.md

---

## Part 8: Tooling Reference

| Tool                                | Purpose                 | Usage                                                           |
| ----------------------------------- | ----------------------- | --------------------------------------------------------------- |
| `tools/migration_status.py`         | Full migration report   | `python -m tools.migration_status --env prod`                   |
| `tools/baseline_migrations.py`      | Mark migrations applied | `python -m tools.baseline_migrations --commit`                  |
| `tools/repair_migration_history.py` | Fix version drift       | `python -m tools.repair_migration_history --env prod --execute` |
| `tools/prod_gate.py`                | Release gate validation | `python -m tools.prod_gate --mode prod --env prod`              |
| `scripts/db_push.ps1`               | Apply migrations        | `./scripts/db_push.ps1 -SupabaseEnv prod`                       |
| `supabase migration up`             | Supabase CLI apply      | CI-only, not for manual use                                     |

---

## Part 9: Emergency Procedures

### 9.1 Rollback a Bad Migration

```powershell
# 1. Identify the migration
$BAD_MIGRATION = "20260118_bad_change"

# 2. Execute manual rollback SQL
psql $env:DATABASE_URL -f "rollback/$BAD_MIGRATION.rollback.sql"

# 3. Remove from schema_migrations
psql $env:DATABASE_URL -c "DELETE FROM supabase_migrations.schema_migrations WHERE version = '$BAD_MIGRATION'"

# 4. Delete or rename local file
Move-Item "supabase/migrations/${BAD_MIGRATION}.sql" "archive/failed/${BAD_MIGRATION}.sql.FAILED"

# 5. Verify
python -m tools.prod_gate --env prod
```

### 9.2 Full Schema Rebuild (Disaster Recovery)

```powershell
# 1. Restore from backup or replay migrations
pg_restore --clean --if-exists -d postgres backup.dump

# 2. Re-baseline migration history
python -m tools.baseline_migrations --commit

# 3. Verify
python -m tools.prod_gate --env prod
```

---

## Appendix A: Migration Status Glossary

| Term         | Definition                                         |
| ------------ | -------------------------------------------------- |
| **Applied**  | Migration exists in both local files and DB        |
| **Pending**  | Migration exists locally but not in DB             |
| **Orphan**   | Migration exists in DB but not locally             |
| **Drift**    | Schema state doesn't match migration expectations  |
| **Baseline** | A squashed migration representing known-good state |

## Appendix B: Version History

| Date       | Author   | Change                  |
| ---------- | -------- | ----------------------- |
| 2026-01-18 | Platform | Initial policy document |

---

_End of Migration Policy Document_
