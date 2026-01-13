# DSN Contract Runbook

Production Supabase DSN requirements for Dragonfly Civil.

## Production DSN Contract

All THREE requirements MUST be met for production:

| Requirement | Value                   | Reason                          |
| ----------- | ----------------------- | ------------------------------- |
| **Host**    | `*.pooler.supabase.com` | Transaction Pooler (NOT direct) |
| **Port**    | `6543`                  | Pooler port (NOT 5432)          |
| **SSL**     | `sslmode=require`       | Encrypted connections           |

### Valid Example

```
postgresql://postgres.<ref>:<password>@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
```

### Invalid Examples

```
# ❌ Direct connection host (db.*)
postgresql://postgres:<pw>@db.abc123.supabase.co:5432/postgres

# ❌ Wrong port (5432 = direct, not pooler)
postgresql://postgres:<pw>@aws-0-us-east-1.pooler.supabase.com:5432/postgres

# ❌ Missing sslmode
postgresql://postgres:<pw>@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

---

## How to Get the Correct DSN

### Step 1: Supabase Dashboard

1. Go to [Supabase Dashboard](https://app.supabase.com)
2. Select your project
3. Navigate to **Settings** → **Database**
4. Scroll to **Connection string**

### Step 2: Select Transaction Mode

⚠️ **IMPORTANT**: Click the **Transaction** tab (NOT Session, NOT Direct)

| Mode              | Port | Use Case                                        |
| ----------------- | ---- | ----------------------------------------------- |
| **Transaction** ✓ | 6543 | API servers, workers, short-lived connections   |
| Session           | 5432 | Long-lived connections (NOT for production API) |
| Direct            | 5432 | Migrations only (NEVER for runtime)             |

### Step 3: Copy the URI

The URI should look like:

```
postgresql://postgres.abc123def:YourPasswordHere@aws-0-us-east-1.pooler.supabase.com:6543/postgres
```

### Step 4: Add sslmode=require

Append `?sslmode=require` to the end:

```
postgresql://postgres.abc123def:YourPasswordHere@aws-0-us-east-1.pooler.supabase.com:6543/postgres?sslmode=require
```

### Step 5: Update Railway

1. Go to [Railway Dashboard](https://railway.app)
2. Select your project → Service
3. Click **Variables**
4. Find or create `SUPABASE_DB_URL`
5. Paste the complete DSN (with sslmode=require)
6. Click **Redeploy**

---

## Validation Tools

### Local Validation (Before Deploy)

```bash
# Validate DSN from environment
python -m tools.validate_prod_dsn

# Validate explicit DSN
python -m tools.validate_prod_dsn "postgresql://..."

# Show runbook
python -m tools.validate_prod_dsn --runbook
```

### Production Gate (Full Check)

```bash
# Runs DSN contract check first, then all prod checks
python -m tools.prod_gate --mode prod
```

### Runtime Protection

The `config_guard` module automatically validates the DSN at startup:

- Blocks boot if DSN violates contract
- Prints operator-friendly FATAL block with fix instructions
- Exits with code 1 (prevents Railway deployment from going live)

---

## Troubleshooting

### "Host must contain .pooler.supabase.com"

You copied the **Direct** connection string instead of **Transaction**.

**Fix**: Go back to Supabase Dashboard → Settings → Database → Connection string → click **Transaction** tab.

### "Port 5432 is DIRECT connection"

You're using the direct database port, not the pooler.

**Fix**: Change `:5432` to `:6543` in your DSN.

### "sslmode is missing"

Production requires explicit SSL.

**Fix**: Append `?sslmode=require` to your DSN.

### "Application startup blocked"

The runtime detected a DSN contract violation and refused to start.

**Fix**: Follow the steps above to get the correct DSN, update Railway, and redeploy.

---

## Why This Matters

| Issue             | Risk                                          |
| ----------------- | --------------------------------------------- |
| Using direct host | Bypasses pooler, exhausts 60 connection limit |
| Using port 5432   | Direct connection, no pooling                 |
| Missing sslmode   | Credentials transmitted unencrypted           |

A single misconfigured service can lock out ALL other services from the database.

---

## Quick Reference

```
✅ CORRECT (Transaction Pooler):
postgresql://postgres.<ref>:<pw>@aws-0-<region>.pooler.supabase.com:6543/postgres?sslmode=require

❌ WRONG (Direct Connection):
postgresql://postgres:<pw>@db.<ref>.supabase.co:5432/postgres
```
