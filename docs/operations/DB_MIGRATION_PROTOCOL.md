# Database Migration Protocol

> **Last Updated:** 2024-12-04  
> **Owner:** DevOps Lead  
> **Audience:** All engineers working on Dragonfly Civil

---

## Executive Summary

All database schema changes flow through **migration files** in `supabase/migrations/`. GitHub Actions CI is the **only writer** to Dev and Prod databases. Local Windows machines are **read-only** via REST API.

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Local Dev      │────▶│  GitHub Actions │────▶│  Supabase DB    │
│  (Read-Only)    │     │  (Only Writer)  │     │  (Dev / Prod)   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
     │                         │                        │
     │ REST API                │ migration up           │
     │ (status only)           │ --db-url               │
     ▼                         ▼                        ▼
  tools.migration_status    supabase-migrate.yml    Schema applied
```

---

## Roles & Responsibilities

| Role                    | Can Do                                                | Cannot Do                  |
| ----------------------- | ----------------------------------------------------- | -------------------------- |
| **CI (GitHub Actions)** | Apply migrations via `migration up --db-url`          | —                          |
| **Local Windows**       | Read migration status via REST                        | Write to database directly |
| **Supabase Studio**     | Emergency hotfixes only (must sync to migration file) | Routine schema changes     |

---

## Step-by-Step Workflow

### ✅ Step 1: Author the Migration

Create or edit SQL files in `supabase/migrations/`:

```powershell
# Naming convention: YYYYMMDDHHMMSS_short_description.sql
# Example: 20251209143000_add_customer_tier_column.sql
```

**Migration file requirements:**

- [ ] Idempotent (safe to run multiple times)
- [ ] Uses `CREATE OR REPLACE`, `DROP IF EXISTS`, or `DO $$ ... $$` guards
- [ ] No destructive operations without explicit approval
- [ ] Includes `GRANT` statements for `authenticated` and `service_role` where needed

### ✅ Step 2: Run Local Tests

```powershell
$env:SUPABASE_MODE = 'dev'
.\.venv\Scripts\python.exe -m pytest
```

Run schema-specific tests if applicable:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_migration_status_view.py -v
.\.venv\Scripts\python.exe -m pytest tests/test_enforcement_views.py -v
```

### ✅ Step 3: Commit & Push

```powershell
git add supabase/migrations/*.sql
git add <any related backend/frontend changes>
git commit -m "feat: <short description of schema change>"
git push origin main
```

**That's it.** You do NOT run any Supabase CLI commands locally.

### ✅ Step 4: Verify CI Applied the Migration

1. Open GitHub → **Actions** tab → **Supabase Migrations** workflow
2. Find the latest run for your commit
3. Check the result:

| CI Status | Meaning                        | Action                                                  |
| --------- | ------------------------------ | ------------------------------------------------------- |
| ✅ Green  | Migration applied successfully | Done!                                                   |
| ❌ Red    | Migration failed               | See [Responding to Red CI](#responding-to-a-red-ci-run) |

### ✅ Step 5: Confirm Status (Optional)

From your Windows machine, verify what's applied:

```powershell
$env:SUPABASE_MODE = 'dev'
.\.venv\Scripts\python.exe -m tools.migration_status
```

Expected output:

```
🔍 Checking migration status for: DEV
📡 Fetching from: https://xxx.supabase.co/rest/v1/v_migration_status
📂 Found 180 local migration files

================================================================================
MIGRATION STATUS
================================================================================

📦 Supabase CLI Migrations (schema_migrations)
----------------------------------------------------------------------
Version              Name                                     Status
----------------------------------------------------------------------
20251209143000       20251209143000_add_customer_tier.sql     ✅ APPLIED
20251209000000       20251209000000_migration_status_view.sql ✅ APPLIED
...

✅ Legacy: 70 applied. Supabase: 110 applied, 0 pending, 0 failed.
```

---

## 🚫 Never Do This

| Forbidden Action                   | Why                                      | What to Do Instead           |
| ---------------------------------- | ---------------------------------------- | ---------------------------- |
| `supabase db push`                 | Bypasses migration history, causes drift | Use migration files + CI     |
| `supabase migration list --linked` | Hangs/fails on Windows due to pooler DNS | Use `tools.migration_status` |
| `--linked` flag anywhere           | Same DNS issues, unreliable              | Always use `--db-url`        |
| Ad-hoc SQL in Prod Studio          | No audit trail, causes drift             | Create a migration file      |
| Direct `psql` to prod              | Bypasses all safety checks               | CI only                      |
| Editing `schema_migrations` table  | Corrupts migration history               | Never touch this table       |

### If You Must Hotfix (Emergency Only)

1. **Document the emergency** in Slack/Discord
2. Run the SQL in Supabase Studio **for dev only**
3. **Immediately** create the matching migration file
4. Commit and push so CI stays in sync
5. Post-incident review: why did we need a hotfix?

---

## Responding to a Red CI Run

When the `supabase-migrate` workflow fails:

### Step 1: Read the CI Logs

```
GitHub → Actions → Supabase Migrations → Click the failed run → Expand failed step
```

Common errors:

| Error                                            | Cause                               | Fix                                                       |
| ------------------------------------------------ | ----------------------------------- | --------------------------------------------------------- |
| `relation "X" already exists`                    | Migration not idempotent            | Add `IF NOT EXISTS` or `DROP IF EXISTS`                   |
| `column "X" does not exist`                      | Dependency order wrong              | Rename migration with earlier timestamp                   |
| `permission denied`                              | Missing GRANT                       | Add `GRANT SELECT ON ... TO authenticated, service_role;` |
| `syntax error at or near`                        | SQL typo                            | Fix the syntax                                            |
| `duplicate key value violates unique constraint` | Migration already partially applied | Use `ON CONFLICT DO NOTHING` or wrap in `DO $$` block     |

### Step 2: Fix the Migration

Edit the failing SQL file in `supabase/migrations/`:

```sql
-- BAD: Not idempotent
CREATE TABLE foo (...);

-- GOOD: Idempotent
CREATE TABLE IF NOT EXISTS foo (...);

-- GOOD: For complex changes
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_tables WHERE tablename = 'foo') THEN
        CREATE TABLE foo (...);
    END IF;
END $$;
```

### Step 3: Push the Fix

```powershell
git add supabase/migrations/<fixed_file>.sql
git commit -m "fix: make migration idempotent"
git push origin main
```

### Step 4: Verify Green

Watch the new CI run. Repeat until green.

---

## Quick Reference Card

```
┌────────────────────────────────────────────────────────────────────┐
│                    MIGRATION CHECKLIST                              │
├────────────────────────────────────────────────────────────────────┤
│ □ Create SQL file in supabase/migrations/                          │
│ □ Make it idempotent (IF NOT EXISTS, etc.)                         │
│ □ Include GRANT statements                                          │
│ □ Run pytest locally                                                │
│ □ git add + commit + push                                           │
│ □ Check GitHub Actions for green ✅                                 │
│ □ Run tools.migration_status to confirm                             │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                    FORBIDDEN COMMANDS                               │
├────────────────────────────────────────────────────────────────────┤
│ ✗ supabase db push                                                  │
│ ✗ supabase migration list --linked                                  │
│ ✗ supabase link                                                     │
│ ✗ Any command with --linked flag                                    │
│ ✗ Direct psql to production                                         │
│ ✗ Ad-hoc SQL in Supabase Studio (except emergencies)               │
└────────────────────────────────────────────────────────────────────┘

┌────────────────────────────────────────────────────────────────────┐
│                    USEFUL COMMANDS                                  │
├────────────────────────────────────────────────────────────────────┤
│ # Check migration status (REST, no DB connection)                   │
│ $env:SUPABASE_MODE = 'dev'                                          │
│ .\.venv\Scripts\python.exe -m tools.migration_status               │
│                                                                     │
│ # Run tests                                                         │
│ .\.venv\Scripts\python.exe -m pytest                               │
│                                                                     │
│ # Check for pending migrations                                      │
│ .\.venv\Scripts\python.exe -m tools.migration_status --json        │
└────────────────────────────────────────────────────────────────────┘
```

---

## Architecture Notes

### Why CI-Only Writes?

1. **Audit trail**: Every change is in git history
2. **Reproducibility**: Same migrations apply to dev, staging, prod
3. **No drift**: Local experiments can't pollute shared databases
4. **Windows compatibility**: Avoids Supabase CLI DNS issues on Windows

### Why REST for Status?

1. **Works everywhere**: No direct DB connection needed
2. **Firewall-friendly**: Uses HTTPS on port 443
3. **Service role key**: Already in `.env` for other tools

### Migration Tracking Tables

| Table                                   | Purpose                                     |
| --------------------------------------- | ------------------------------------------- |
| `supabase_migrations.schema_migrations` | Supabase CLI tracks applied migrations here |
| `public.dragonfly_migrations`           | Legacy tracker (numeric versions 0001-0070) |
| `public.v_migration_status`             | Unified view of both, exposed via REST      |

---

## Contacts

- **CI Failures**: Check Discord `#alerts` channel (auto-posted on failure)
- **Emergency Hotfixes**: Notify DevOps lead before touching prod
- **Questions**: Ask in `#engineering` Slack channel

---

_This protocol ensures zero-downtime migrations, full audit trails, and consistent schema across all environments._
