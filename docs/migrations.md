# Database Migrations

This document explains how to manage Supabase database migrations for Dragonfly Civil.

## Quick Start

```powershell
# Preview pending migrations (no changes)
.\scripts\db_migrate.ps1 -Env dev -DryRun

# Apply all pending migrations to dev
.\scripts\db_migrate.ps1 -Env dev

# Apply all pending migrations to prod
.\scripts\db_migrate.ps1 -Env prod
```

## Setting Up Your Connection String

The migration script requires a database connection string in `.env`.

### Step 1: Get Your Connection String

1. Go to [Supabase Dashboard](https://supabase.com/dashboard)
2. Select your project
3. Navigate to **Settings → Database → Connection string**
4. Copy the **URI** format (starts with `postgresql://...`)

### Step 2: Add to .env

Paste the connection string into your `.env` file:

```dotenv
# For dev environment
SUPABASE_DB_URL_DEV=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres

# For prod environment (if different)
SUPABASE_DB_URL_PROD=postgresql://postgres:YOUR_PASSWORD@db.YOUR_PROJECT.supabase.co:5432/postgres
```

**Important:** Copy the string exactly as shown in Supabase. Do not modify or re-encode it.

## Workflow

### 1. Create a New Migration

Add a new SQL file under `supabase/migrations/` with a timestamp prefix:

```
supabase/migrations/20251203160000_my_feature.sql
```

**Naming convention:** `YYYYMMDDHHMMSS_description.sql`

Use the VS Code task **"New Migration"** to auto-generate the timestamp.

### 2. Write Idempotent SQL

Always use idempotent patterns so migrations can be re-run safely:

```sql
-- Tables
CREATE TABLE IF NOT EXISTS my_table (...);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_name ON my_table(...);

-- Policies (use DO block for idempotency)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies WHERE policyname = 'my_policy'
    ) THEN
        CREATE POLICY my_policy ON my_table ...;
    END IF;
END $$;

-- Types
DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'my_type') THEN
        CREATE TYPE my_type AS (...);
    END IF;
END $$;

-- Functions (use CREATE OR REPLACE)
CREATE OR REPLACE FUNCTION my_function() ...;
```

### 3. Apply Migrations

```powershell
.\scripts\db_migrate.ps1 -Env dev
```

The script will:

1. Load environment from `.env`
2. Connect to the remote database using `--db-url`
3. List pending migrations
4. Apply all pending migrations
5. Auto-repair any "already exists" errors

### 4. Handle Already-Applied Migrations

If a migration was applied manually (e.g., via Supabase SQL Editor), the script will:

1. Detect the "already exists" error
2. Automatically mark the migration as applied via `supabase migration repair`
3. Retry applying remaining migrations

To manually repair a migration:

```powershell
# Load env first
. .\scripts\load_env.ps1

# Then repair
supabase migration repair 20251203150000 --status applied --db-url $env:SUPABASE_DB_URL_DEV
```

## Troubleshooting

### "SUPABASE_DB_URL_DEV is not set" Error

The script requires a database connection string. See "Setting Up Your Connection String" above.

### "Initialising login role..." Hangs

This happens when the Supabase CLI tries to use its linked project config instead of `--db-url`.
The `db_migrate.ps1` script avoids this by always using `--db-url` explicitly.

If you need to use other Supabase CLI commands manually:

```powershell
# Load env first
. .\scripts\load_env.ps1

# Then use --db-url explicitly
supabase migration list --db-url $env:SUPABASE_DB_URL_DEV
```

### "policy already exists" / "relation already exists" Errors

The migration contains non-idempotent SQL. The script will automatically repair these by marking the migration as applied. If you want to fix the root cause:

1. Edit the migration SQL to use idempotent patterns (see above)
2. Or manually repair: `supabase migration repair <id> --status applied --db-url $env:SUPABASE_DB_URL_DEV`

### Connection Refused / Timeout

Check your database URL in `.env`:

- Make sure you copied the exact URI from Supabase Dashboard
- The format should be: `postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres`
- If using the pooler, use port `6543` instead of `5432`

### "Tenant or user not found"

This usually means the connection string is malformed or the project reference is wrong. Re-copy the URI from Supabase Dashboard.

## Scripts Reference

| Script           | Purpose                                           |
| ---------------- | ------------------------------------------------- |
| `db_migrate.ps1` | **Canonical migration script** - use this         |
| `db_push.ps1`    | Legacy wrapper (deprecated, calls db_migrate.ps1) |
| `load_env.ps1`   | Loads `.env` into PowerShell environment          |

## Migration History

Supabase tracks applied migrations in `supabase_migrations.schema_migrations`. View status:

```powershell
. .\scripts\load_env.ps1
supabase migration list --db-url $env:SUPABASE_DB_URL_DEV
```
